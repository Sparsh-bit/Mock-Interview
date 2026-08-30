"""
Multi-replica safety — tests/test_multi_replica.py

The audit behind these is docs/MULTI-REPLICA.md, which classifies every piece of
in-process state in the backend. Most of it is safe under N replicas or is a tradeoff that
is already written down. These tests cover the two things that were not.

  1. THE BOOT CHAIN. The container's CMD is
     `alembic upgrade head && (seed_db) && (seed_research) && uvicorn`, and every replica
     runs it. Two replicas booting a deploy that carries a migration both try to apply the
     same DDL; the second gets "relation already exists", the `&&` short-circuits, and that
     replica never starts Uvicorn at all. The seeds have the same shape one level down —
     SELECT-then-INSERT with no lock.

  2. THE JWKS CACHE. Keys are held for 600s with no way to refresh early, so a Supabase key
     rotation is up to ten minutes of 401s. That is true of one replica too; what N replicas
     add is that each holds its own timer, so the failure stops being "everybody is logged
     out for ten minutes" and becomes "logins fail at random", which is a far harder page.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
import yaml

from app.core.config import Settings
from app.db.boot_lock import BOOT_LOCK_KEY, boot_lock

REPO_ROOT = Path(__file__).resolve().parents[2]


# ─── 1. The boot chain must be safe to run in every replica at once ───────────


@pytest.mark.asyncio
async def test_two_replicas_booting_together_do_not_run_migrations_at_the_same_time():
    """
    The whole point. Whoever gets the lock migrates; the other waits and finds the work
    already done, rather than racing it and dying on "relation already exists".
    """
    order: list[str] = []

    async def replica(name: str, hold: float) -> None:
        async with boot_lock(wait_seconds=30) as acquired:
            assert acquired, f"{name} never got the lock"
            order.append(f"{name}:enter")
            await asyncio.sleep(hold)
            order.append(f"{name}:exit")

    await asyncio.gather(replica("a", 0.4), replica("b", 0.0))

    # Whichever ran first, its exit must precede the other's entry. Interleaving is the
    # failure this exists to prevent.
    first = order[0].split(":")[0]
    second = "b" if first == "a" else "a"
    assert order == [
        f"{first}:enter",
        f"{first}:exit",
        f"{second}:enter",
        f"{second}:exit",
    ], f"boot work interleaved: {order}"


@pytest.mark.asyncio
async def test_the_lock_is_released_even_when_the_boot_work_raises():
    """
    A failed migration must not leave the advisory lock held. If it did, every other
    replica would block until its wait expired and then boot unmigrated.
    """
    with pytest.raises(RuntimeError):
        async with boot_lock(wait_seconds=5) as acquired:
            assert acquired
            raise RuntimeError("migration blew up")

    async with boot_lock(wait_seconds=5) as acquired:
        assert acquired, "the lock survived the failure that released it"


@pytest.mark.asyncio
async def test_a_replica_that_cannot_get_the_lock_in_time_says_so_rather_than_racing():
    """
    Reports False instead of proceeding. A caller that pushed on anyway would reintroduce
    exactly the concurrent-DDL race the lock exists to remove.
    """
    async with boot_lock(wait_seconds=30) as held:
        assert held
        started = time.monotonic()
        async with boot_lock(wait_seconds=1) as second:
            assert second is False
        assert time.monotonic() - started < 10, "the waiter did not respect wait_seconds"


@pytest.mark.asyncio
async def test_the_lock_key_is_stable():
    """
    The key is what makes two processes agree they are contending for the same thing.
    Deriving it from anything environment-dependent would silently give each replica its
    own lock, which is the same as having none.
    """
    assert isinstance(BOOT_LOCK_KEY, int)
    assert -(2**63) <= BOOT_LOCK_KEY < 2**63


# ─── 2. A rotated signing key must not cost ten minutes of logins ─────────────


@pytest.mark.asyncio
async def test_an_unknown_key_id_refetches_the_jwks_instead_of_waiting_out_the_ttl(
    monkeypatch,
):
    """
    Supabase rotates; the cache must be able to catch up on demand. Without this the only
    recovery is the 600s timer, and under N replicas each replica runs its own.
    """
    from app.core import security

    fetches: list[int] = []

    async def fake_fetch() -> list[dict]:
        fetches.append(1)
        # First call returns the old key set, every call after it the rotated one.
        return [{"kid": "old"}] if len(fetches) == 1 else [{"kid": "new"}]

    monkeypatch.setattr(security, "_fetch_jwks", fake_fetch)
    security.reset_jwks_cache()

    assert await security.get_signing_keys() == [{"kid": "old"}]
    # Cached — a second call for a kid we already hold must not hit the network.
    assert await security.get_signing_keys(kid="old") == [{"kid": "old"}]
    assert len(fetches) == 1

    refreshed = await security.get_signing_keys(kid="new")
    assert {"kid": "new"} in refreshed, "a rotated kid did not trigger a refetch"
    assert len(fetches) == 2


@pytest.mark.asyncio
async def test_an_unknown_key_id_does_not_refetch_twice_in_a_row(monkeypatch):
    """
    A cooldown, because the refetch is triggered by attacker-supplied input: a token can
    carry any `kid` at all, and without this every forged token would be a request to
    Supabase's JWKS endpoint.
    """
    from app.core import security

    fetches: list[int] = []

    async def fake_fetch() -> list[dict]:
        fetches.append(1)
        return [{"kid": "old"}]

    monkeypatch.setattr(security, "_fetch_jwks", fake_fetch)
    security.reset_jwks_cache()

    await security.get_signing_keys()
    for _ in range(20):
        await security.get_signing_keys(kid="does-not-exist")

    assert len(fetches) == 2, (
        f"{len(fetches)} JWKS fetches for 20 unknown key ids — a forged token is a "
        f"free request to Supabase"
    )


# ─── 3. The replica count and everything that must move with it ───────────────


class TestReplicaCountIsConsistent:
    """
    The replica count is not one number. It sets the Postgres connection budget, the Redis
    connection budget, and the fleet-wide report concurrency — and `WEB_REPLICA_COUNT` is
    what every startup audit multiplies by. A blueprint whose numbers disagree produces
    audits that are wrong in the optimistic direction, which is the failure mode where
    nothing warns you.
    """

    @staticmethod
    def _service() -> dict:
        blueprint = REPO_ROOT / "render.yaml"
        return yaml.safe_load(blueprint.read_text())["services"][0]

    def test_more_than_one_instance_requires_an_instance_type_that_allows_it(self):
        """
        Render's Free compute plan lists "Scaling beyond a single instance" as unsupported,
        so `numInstances: 2` on `plan: free` is a blueprint that cannot deploy.
        """
        service = self._service()
        if service.get("numInstances", 1) > 1:
            assert service.get("plan") != "free", (
                "numInstances > 1 with plan: free — Render Free cannot scale beyond one "
                "instance, so this blueprint will not deploy"
            )

    def test_the_replica_count_is_declared_to_the_application(self):
        """
        The startup audits multiply per-process budgets by WEB_REPLICA_COUNT. If the
        blueprint scales past one instance without declaring it, every one of those audits
        under-reports.
        """
        service = self._service()
        declared = {e["key"] for e in service["envVars"]}
        if service.get("numInstances", 1) > 1:
            assert "WEB_REPLICA_COUNT" in declared, (
                "numInstances > 1 but WEB_REPLICA_COUNT is not declared — the Redis and "
                "database connection audits will silently assume a single replica"
            )

    def test_the_default_replica_count_matches_the_application_default(self):
        """
        Nothing sets WEB_REPLICA_COUNT for a single-instance deploy, so its default has to
        be the truth for that case.
        """
        service = self._service()
        if "WEB_REPLICA_COUNT" not in {e["key"] for e in service["envVars"]}:
            assert (
                Settings.model_fields["WEB_REPLICA_COUNT"].default
                == service.get("numInstances", 1)
            )
