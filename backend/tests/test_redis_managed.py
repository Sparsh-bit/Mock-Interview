"""
Managed, replicated Redis readiness — tests/test_redis_managed.py

These tests exist because the move from "a Redis on localhost" to "a Redis somebody else
operates" changes three things at once, and none of them announces itself at the point of
failure:

  * the connection is TLS, and a misconfigured trust store fails as a timeout
  * the server can move underneath a live pool (failover), and a pooled socket that was
    open to the old node is indistinguishable from a healthy one until a command uses it
  * the connection budget is now (pool size x replicas) against a ceiling the provider
    enforces, not against a local machine that has no ceiling

The end-to-end TLS test runs a real RESP server behind a real self-signed CA rather than
asserting on kwargs, because "the pool was built with SSLConnection" and "a TLS handshake
to this provider actually completes and verifies" are different claims and only the second
one is the thing that breaks a cutover.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import ipaddress
import ssl
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from redis.asyncio.connection import Connection, SSLConnection
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app.db import redis as redis_module

# ─── A real TLS RESP server ───────────────────────────────────────────────────


def _write_cert_chain(tmp_path: Path) -> tuple[Path, Path, Path]:
    """
    Issue a CA and a `localhost` server certificate signed by it.

    Returns (ca_pem, server_cert_pem, server_key_pem). The CA path is what gets handed to
    REDIS_TLS_CA_CERTS, which is exactly the knob a provider with a private CA needs.
    """
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "hotseat-test-ca")])
    now = dt.datetime.now(dt.UTC)
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        # OpenSSL 3 rejects a chain whose CA carries no Subject Key Identifier with
        # "Missing Authority Key Identifier" on the leaf, so both halves are required
        # for this to be a realistic CA rather than one only a lax verifier accepts.
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )

    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]))
        .issuer_name(ca_name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    ca_pem = tmp_path / "ca.pem"
    cert_pem = tmp_path / "server.pem"
    key_pem = tmp_path / "server.key"
    ca_pem.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    cert_pem.write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))
    key_pem.write_bytes(
        server_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return ca_pem, cert_pem, key_pem


async def _read_resp_command(reader: asyncio.StreamReader) -> list[bytes] | None:
    """Read one RESP array command. None at clean EOF."""
    header = await reader.readline()
    if not header:
        return None
    if not header.startswith(b"*"):
        return []
    argc = int(header[1:].strip())
    args: list[bytes] = []
    for _ in range(argc):
        size_line = await reader.readline()
        size = int(size_line[1:].strip())
        payload = await reader.readexactly(size)
        await reader.readexactly(2)  # trailing CRLF
        args.append(payload)
    return args


class _FakeTlsRedis:
    """
    The smallest server that a redis-py client will successfully talk to over TLS.

    PING answers +PONG; everything else (CLIENT SETINFO, SELECT, the handshake chatter
    redis-py emits on connect) answers +OK. One reply per command, so a pipelined
    connect sequence lines up.
    """

    def __init__(self) -> None:
        self.commands: list[bytes] = []
        self._server: asyncio.Server | None = None

    async def start(self, cert_pem: Path, key_pem: Path) -> int:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=str(cert_pem), keyfile=str(key_pem))
        self._server = await asyncio.start_server(
            self._handle, host="127.0.0.1", port=0, ssl=context
        )
        return self._server.sockets[0].getsockname()[1]

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            while True:
                args = await _read_resp_command(reader)
                if args is None:
                    break
                if not args:
                    continue
                verb = args[0].upper()
                self.commands.append(verb)
                writer.write(b"+PONG\r\n" if verb == b"PING" else b"+OK\r\n")
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError, ssl.SSLError):
            pass
        finally:
            writer.close()

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()


@pytest.fixture
async def _clean_pool():
    """Every test gets a fresh pool, and leaves none behind for the next one."""
    await redis_module.close_redis_pool()
    yield
    await redis_module.close_redis_pool()


# ─── TLS end to end ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rediss_url_completes_a_verified_tls_handshake_end_to_end(
    tmp_path, monkeypatch, _clean_pool
):
    """
    The cutover check, run for real: rediss:// + a CA bundle, through the application's own
    pool, all the way to a PING answered over an encrypted socket whose certificate was
    verified against that CA.
    """
    ca_pem, cert_pem, key_pem = _write_cert_chain(tmp_path)
    server = _FakeTlsRedis()
    port = await server.start(cert_pem, key_pem)
    try:
        monkeypatch.setattr(
            redis_module.settings, "REDIS_URL", f"rediss://localhost:{port}/0"
        )
        monkeypatch.setattr(redis_module.settings, "REDIS_TLS_CA_CERTS", str(ca_pem))

        assert await redis_module.check_redis_connection() is True
        assert b"PING" in server.commands
    finally:
        await redis_module.close_redis_pool()
        await server.stop()


@pytest.mark.asyncio
async def test_rediss_handshake_fails_when_the_certificate_is_not_trusted(
    tmp_path, monkeypatch, _clean_pool
):
    """
    The other half of the same claim. If an untrusted certificate also "worked", the
    passing test above would prove nothing about verification.
    """
    _, cert_pem, key_pem = _write_cert_chain(tmp_path)
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    other_ca_pem, _, _ = _write_cert_chain(other_dir)
    server = _FakeTlsRedis()
    port = await server.start(cert_pem, key_pem)
    try:
        monkeypatch.setattr(
            redis_module.settings, "REDIS_URL", f"rediss://localhost:{port}/0"
        )
        monkeypatch.setattr(
            redis_module.settings, "REDIS_TLS_CA_CERTS", str(other_ca_pem)
        )

        assert await redis_module.check_redis_connection() is False
    finally:
        await redis_module.close_redis_pool()
        await server.stop()


def test_plain_redis_url_builds_a_pool_even_with_a_ca_bundle_configured(
    monkeypatch,
):
    """
    A CA path is meaningless for redis:// and redis-py's non-TLS Connection rejects
    unknown kwargs outright. Local dev must not break because production set the knob.
    """
    monkeypatch.setattr(redis_module.settings, "REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setattr(redis_module.settings, "REDIS_TLS_CA_CERTS", "/etc/ssl/ca.pem")

    pool = redis_module._create_pool()

    assert pool.connection_class is Connection
    assert "ssl_ca_certs" not in pool.connection_kwargs


def test_rediss_pool_verifies_certificates_and_hostnames(monkeypatch):
    monkeypatch.setattr(
        redis_module.settings, "REDIS_URL", "rediss://user:pw@managed.example:6380/0"
    )
    monkeypatch.setattr(redis_module.settings, "REDIS_TLS_CA_CERTS", None)

    pool = redis_module._create_pool()

    assert pool.connection_class is SSLConnection
    assert pool.connection_kwargs["ssl_cert_reqs"] == "required"
    assert pool.connection_kwargs["ssl_check_hostname"] is True


# ─── Failover behaviour ───────────────────────────────────────────────────────


def test_pool_pings_idle_connections_so_failover_stale_sockets_are_caught(monkeypatch):
    """
    Without a health check interval a socket left open to a node that has since been
    replaced is handed to the next caller and fails that caller's command.
    """
    monkeypatch.setattr(redis_module.settings, "REDIS_URL", "redis://localhost:6379/0")

    pool = redis_module._create_pool()

    assert pool.connection_kwargs["health_check_interval"] > 0


def test_retry_covers_the_errors_a_failover_actually_raises(monkeypatch):
    """
    The previous configuration listed the BUILTIN ConnectionRefusedError and TimeoutError.
    redis-py raises redis.exceptions.ConnectionError / TimeoutError, neither of which
    inherits from a builtin — so that list matched nothing it was written to match.
    """
    monkeypatch.setattr(redis_module.settings, "REDIS_URL", "redis://localhost:6379/0")

    pool = redis_module._create_pool()
    retry = pool.connection_kwargs["retry"]

    supported = retry._supported_errors
    assert RedisConnectionError in supported
    assert RedisTimeoutError in supported
    assert retry.get_retries() >= 3


def test_backoff_is_jittered_so_replicas_do_not_reconnect_in_lockstep(monkeypatch):
    """
    N replicas all losing the same server reconnect at the same instant on a deterministic
    backoff, which is the shape of a thundering herd against a just-recovered node.
    """
    monkeypatch.setattr(redis_module.settings, "REDIS_URL", "redis://localhost:6379/0")

    retry = redis_module._create_pool().connection_kwargs["retry"]
    backoff = retry._backoff

    delays = {backoff.compute(3) for _ in range(40)}
    assert len(delays) > 1, "backoff is deterministic; a failover would sync every replica"


@pytest.mark.asyncio
async def test_health_check_gives_up_within_its_deadline(monkeypatch, _clean_pool):
    """
    check_redis_connection backs Render's health check path. Connect timeout x retries plus
    backoff can run past 20s, which reads to the platform as a dead instance.
    """
    # 10.255.255.1 is RFC1918 space that blackholes rather than refusing, so the
    # connect attempt hangs instead of failing fast.
    monkeypatch.setattr(redis_module.settings, "REDIS_URL", "redis://10.255.255.1:6379/0")
    monkeypatch.setattr(redis_module.settings, "REDIS_HEALTH_PING_TIMEOUT_SECONDS", 1.0)

    loop = asyncio.get_running_loop()
    started = loop.time()
    result = await redis_module.check_redis_connection()
    elapsed = loop.time() - started

    assert result is False
    assert elapsed < 5.0, f"health check took {elapsed:.1f}s"


# ─── Configuration audit ──────────────────────────────────────────────────────


def _codes(issues) -> set[str]:
    return {issue.code for issue in issues}


def test_plaintext_redis_in_production_is_reported():
    issues = redis_module.audit_redis_configuration(
        url="redis://default:hunter2@managed.example:6379",
        environment="production",
        max_connections=20,
        replicas=1,
        ceiling=100,
    )
    assert "redis_plaintext_in_production" in _codes(issues)


def test_tls_redis_in_production_is_not_reported():
    issues = redis_module.audit_redis_configuration(
        url="rediss://default:hunter2@managed.example:6379",
        environment="production",
        max_connections=20,
        replicas=1,
        ceiling=100,
    )
    assert "redis_plaintext_in_production" not in _codes(issues)


def test_plaintext_loopback_redis_in_development_is_not_reported():
    issues = redis_module.audit_redis_configuration(
        url="redis://localhost:6379/0",
        environment="development",
        max_connections=20,
        replicas=1,
        ceiling=0,
    )
    assert issues == []


def test_pool_budget_over_the_provider_ceiling_is_reported():
    issues = redis_module.audit_redis_configuration(
        url="rediss://managed.example:6379",
        environment="production",
        max_connections=20,
        replicas=6,  # 120 connections
        ceiling=100,
    )
    assert "redis_pool_budget_over_ceiling" in _codes(issues)


def test_pool_budget_near_the_provider_ceiling_is_reported():
    issues = redis_module.audit_redis_configuration(
        url="rediss://managed.example:6379",
        environment="production",
        max_connections=20,
        replicas=4,  # 80 of 100
        ceiling=100,
    )
    assert "redis_pool_budget_near_ceiling" in _codes(issues)


def test_pool_budget_comfortably_under_the_ceiling_is_silent():
    issues = redis_module.audit_redis_configuration(
        url="rediss://managed.example:6379",
        environment="production",
        max_connections=20,
        replicas=3,  # 60 of 100
        ceiling=100,
    )
    assert issues == []


def test_an_unknown_provider_ceiling_disables_the_budget_check_rather_than_guessing():
    issues = redis_module.audit_redis_configuration(
        url="rediss://managed.example:6379",
        environment="production",
        max_connections=500,
        replicas=10,
        ceiling=0,
    )
    assert _codes(issues) == {"redis_connection_ceiling_unknown"}


def test_the_audit_message_names_the_numbers_it_is_complaining_about():
    """A warning nobody can act on is noise; the operator needs the arithmetic."""
    (issue,) = [
        i
        for i in redis_module.audit_redis_configuration(
            url="rediss://managed.example:6379",
            environment="production",
            max_connections=20,
            replicas=6,
            ceiling=100,
        )
        if i.code == "redis_pool_budget_over_ceiling"
    ]
    assert "120" in issue.message
    assert "100" in issue.message
