"""
The scanning workflows, and the properties that make them worth having.

WHY A TEST FOR YAML. Nothing else reads these files. Ruff, mypy, eslint and tsc all ignore
`.github/`, so a workflow can be silently disarmed — an `exit-code` flipped to `0`, an
ecosystem deleted, `severity` narrowed to CRITICAL — and every check in the repository still
passes. The failure mode is identical to the one `docs/MISTAKES.md` spends most of its length
on: a guard that cannot fail, reporting success.

These assert the DECISIONS, not the syntax. That the Trivy step gates rather than reports,
that Dependabot covers the ecosystem people forget, that nothing auto-merges. Each is a thing
somebody could reasonably change without realising it turns the check off.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# A PLAIN IMPORT, NOT `importorskip`. pyyaml is a hard dependency in pyproject.toml, so it is
# always there — and `importorskip` would turn a broken environment into a silently skipped
# file, which is the exact "a skipped test is not a passing test" trap the CI workflow warns
# about at the top.
import yaml

GITHUB = Path(__file__).resolve().parents[2] / ".github"


def _load(rel: str) -> dict:
    return yaml.safe_load((GITHUB / rel).read_text())


def _raw(rel: str) -> str:
    return (GITHUB / rel).read_text()


def _triggers(rel: str) -> dict:
    """The `on:` block. See the note in the schedule test for why it is not `config["on"]`."""
    config = _load(rel)
    return config.get("on") or config[True]


class TestDependabot:
    def test_it_covers_all_three_ecosystems(self):
        """
        `github-actions` IS THE ONE PEOPLE FORGET, and it is the one that matters most here:
        a pinned action is code that runs with a token on every push, and it goes stale
        exactly like a library. A repository that scans its dependencies with a two-year-old
        runner has the problem it thinks it is solving.
        """
        config = _load("dependabot.yml")
        ecosystems = {u["package-ecosystem"] for u in config["updates"]}
        assert ecosystems == {"npm", "pip", "github-actions"}

    def test_npm_points_at_the_workspace_root(self):
        # An npm workspaces monorepo has ONE root package-lock.json. Pointing Dependabot at
        # /frontend makes it resolve against a lockfile that is not there, and it reports
        # nothing rather than erroring.
        config = _load("dependabot.yml")
        npm = next(u for u in config["updates"] if u["package-ecosystem"] == "npm")
        assert npm["directory"] == "/"

    def test_pip_points_at_the_backend(self):
        config = _load("dependabot.yml")
        pip = next(u for u in config["updates"] if u["package-ecosystem"] == "pip")
        assert pip["directory"] == "/backend"
        assert (Path(__file__).resolve().parents[1] / "pyproject.toml").exists()

    def test_nothing_auto_merges(self):
        """
        A dependency update is a code change that reaches production. CI is the check, not a
        substitute for somebody reading the diff — auto-merging on green is how a compromised
        release gets in on a Sunday.
        """
        raw = _raw("dependabot.yml")
        for marker in ("auto-merge", "automerge", "gh pr merge"):
            assert marker not in raw.lower().replace("no auto-merge", "")

    def test_the_model_sdk_majors_are_held_back_with_a_reason(self):
        # `anthropic` and `zhipuai` majors change request and response shapes, and there is a
        # response parser, a JSON validator, a prompt cache and a cost ledger keyed to those.
        # That is a piece of work with its own tests, not a PR to rubber-stamp.
        config = _load("dependabot.yml")
        pip = next(u for u in config["updates"] if u["package-ecosystem"] == "pip")
        held = {i["dependency-name"] for i in pip.get("ignore", [])}
        assert {"anthropic", "zhipuai"} <= held
        for entry in pip["ignore"]:
            # Held back for MAJORS ONLY. Ignoring the whole package would silently stop
            # security patches, which is the opposite of the intent.
            assert entry["update-types"] == ["version-update:semver-major"]


class TestCodeQL:
    def test_it_analyses_both_languages_this_repository_contains(self):
        config = _load("workflows/codeql.yml")
        langs = {
            m["language"]
            for m in config["jobs"]["analyze"]["strategy"]["matrix"]["include"]
        }
        assert langs == {"javascript-typescript", "python"}

    def test_one_language_failing_does_not_hide_the_other(self):
        config = _load("workflows/codeql.yml")
        assert config["jobs"]["analyze"]["strategy"]["fail-fast"] is False

    def test_it_can_write_to_the_security_tab(self):
        # Without `security-events: write` the analysis runs and the results go nowhere,
        # which reads as a passing workflow and an empty Security tab.
        config = _load("workflows/codeql.yml")
        assert config["permissions"]["security-events"] == "write"

    def test_it_runs_on_a_schedule_and_not_only_on_push(self):
        # Most findings on a stable repository come from new QUERIES, not new code. A
        # push-only scan stops finding anything the week development slows down.
        #
        # `_triggers` rather than `config["on"]`: YAML 1.1 parses a bare `on` as the boolean
        # True, so `config["on"]` raises KeyError and the obvious spelling of this assertion
        # fails for a reason that has nothing to do with the schedule.
        assert _triggers("workflows/codeql.yml").get("schedule")

    def test_it_scans_the_code_we_write(self):
        raw = _raw("workflows/codeql.yml")
        assert "frontend/src" in raw
        assert "backend/app" in raw


class TestImageScan:
    def test_it_scans_the_image_rather_than_the_repository(self):
        """
        The Dockerfile installs with `uv sync --no-dev`, so a filesystem scan of the repo
        would report pytest, ruff and mypy — which are not in production. Noise that trains
        people to ignore the report is worse than no report.
        """
        raw = _raw("workflows/image-scan.yml")
        assert "docker build" in raw
        assert "image-ref: interviewos-backend:scan" in raw

    def test_it_builds_from_the_repository_root(self):
        # The Dockerfile copies database/ for the Alembic migrations, so a build context of
        # backend/ fails. Its own header says so.
        raw = _raw("workflows/image-scan.yml")
        assert "-f Dockerfile ." in raw

    def test_a_high_or_critical_finding_fails_the_build(self):
        """
        THE ASSERTION THE WHOLE WORKFLOW EXISTS FOR. A scan step with `exit-code: 0` runs,
        prints a table, and passes — which looks identical to a clean scan in the checks list.
        """
        config = _load("workflows/image-scan.yml")
        gates = [
            s
            for s in config["jobs"]["trivy"]["steps"]
            if isinstance(s.get("with"), dict) and s["with"].get("exit-code") == "1"
        ]
        assert gates, "no Trivy step fails the build — the gate is decorative"
        severity = gates[0]["with"]["severity"]
        assert "HIGH" in severity and "CRITICAL" in severity

    def test_the_findings_are_reported_even_when_the_gate_passes(self):
        # The gating step stops at the first HIGH, so without a report-everything pass the
        # log shows one finding and hides the other forty.
        config = _load("workflows/image-scan.yml")
        reporters = [
            s
            for s in config["jobs"]["trivy"]["steps"]
            if isinstance(s.get("with"), dict) and s["with"].get("exit-code") == "0"
        ]
        assert reporters, "nothing reports the full inventory"

    def test_a_failing_scan_still_records_what_it_found(self):
        # Without `always()`, the one run that found something is the one run with no record
        # of what it found.
        config = _load("workflows/image-scan.yml")
        uploads = [s for s in config["jobs"]["trivy"]["steps"] if "sarif" in str(s).lower()]
        assert uploads
        assert all(s.get("if") == "always()" for s in uploads)

    def test_nothing_is_allowlisted_without_a_written_reason(self):
        """
        `ignore-unfixed` is the only narrowing, and it is a narrowing rather than an
        allowlist: a vulnerability with no released fix cannot be actioned here, so gating on
        it leaves only bad options — allowlist the CVE (and keep it allowlisted after the fix
        ships) or stop looking. It is still reported and still reaches the Security tab.

        A `.trivyignore` file, by contrast, is a real allowlist and must not appear without
        one reason per entry.
        """
        raw = _raw("workflows/image-scan.yml")
        assert "ignore-unfixed: true" in raw
        # And the reasoning is written down next to it, not carried in somebody's head.
        assert "cannot be actioned" in raw

        trivyignore = GITHUB.parent / ".trivyignore"
        if trivyignore.exists():
            for line in trivyignore.read_text().splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    pytest.fail(
                        f"{stripped!r} is allowlisted in .trivyignore with no comment "
                        f"above it giving the reason"
                    )


class TestRenderBlueprint:
    """
    The deploy configuration, in version control.

    THE POINT OF THESE IS THE ONE THAT CANNOT BE UNDONE BY A COMMIT. A secret pasted into
    render.yaml is in git history from that moment, and rotating the credential is the only
    remedy — `git rm` does not help. So the test is not "did somebody remember"; it is a gate
    that fails before the commit lands.
    """

    BLUEPRINT = GITHUB.parent / "render.yaml"

    def _service(self) -> dict:
        return yaml.safe_load(self.BLUEPRINT.read_text())["services"][0]

    def test_no_secret_value_is_committed(self):
        """
        Every variable is declared BY NAME with `sync: false`, except a handful whose values
        are public settings rather than credentials. Anything that looks like a credential —
        a key, a token, a URL with a password in it — fails here.
        """
        allowed_literals = {
            "ENVIRONMENT",
            "LOG_FORMAT",
            "LOG_LEVEL",
            "CODE_EXEC_PROVIDER",
            "GRIEVANCE_RESPONSE_DAYS",
        }
        for entry in self._service()["envVars"]:
            if "value" not in entry:
                assert entry.get("sync") is False, (
                    f"{entry['key']} declares neither a value nor `sync: false` — Render "
                    f"would treat it as unmanaged and the Blueprint would be incomplete"
                )
                continue
            assert entry["key"] in allowed_literals, (
                f"{entry['key']} has a literal value in render.yaml. If it is a credential "
                f"it is now in git history and rotating it is the only remedy; if it is a "
                f"public setting, add it to allowed_literals with a reason."
            )
            value = str(entry["value"])
            assert len(value) < 40, f"{entry['key']} carries a suspiciously long literal"
            for marker in ("://", "@", "sk-", "rzp_", "eyJ"):
                assert marker not in value, f"{entry['key']} looks like a credential"

    def test_every_setting_with_no_default_is_declared(self):
        """
        The five that make `Settings` refuse to start. Missing one is a deploy that fails at
        boot — which is the intended behaviour, but finding out from a crash loop rather than
        from this file is the avoidable half.
        """
        from app.core.config import Settings

        required = {n for n, f in Settings.model_fields.items() if f.is_required()}
        declared = {e["key"] for e in self._service()["envVars"]}
        assert required <= declared, f"undeclared required settings: {sorted(required - declared)}"

    def test_every_declared_variable_is_a_real_setting(self):
        """
        The other direction, and the one that rots quietly: a variable left here after the
        setting was renamed or removed is an instruction to set something that does nothing.
        """
        from app.core.config import Settings

        known = set(Settings.model_fields)
        declared = {e["key"] for e in self._service()["envVars"]}
        assert declared <= known, (
            f"render.yaml names settings that core/config.py does not have: "
            f"{sorted(declared - known)}"
        )

    def test_the_health_check_path_is_the_one_that_exists(self):
        """
        A bare `/health` 404s — the router mounts it under the versioned prefix — and Render
        would mark the service permanently unhealthy while the application runs fine.
        Asserted against the real route table rather than against the string.
        """
        from app.main import app

        # `app.openapi()` rather than `app.routes`. Included routers are held lazily as
        # `_IncludedRouter` objects that carry no `.path`, so walking app.routes finds only
        # the docs endpoints and this assertion would fail for a reason unrelated to the
        # health check. The OpenAPI document is the flattened, authoritative path list.
        paths = set(app.openapi()["paths"])
        assert self._service()["healthCheckPath"] in paths, (
            f"healthCheckPath is not a route this app serves. Health routes found: "
            f"{sorted(p for p in paths if 'health' in p)}"
        )

    def test_the_build_context_is_the_repository_root(self):
        # alembic.ini points script_location at repo-root database/migrations, so the image
        # copies both backend/ and database/. A context of backend/ cannot see the migrations
        # and the container dies on its first `alembic upgrade head`.
        service = self._service()
        assert service["dockerContext"] == "."
        assert service["dockerfilePath"] == "./Dockerfile"

    def test_the_authentication_bypass_is_not_named(self):
        """
        ALLOW_UNVERIFIED_JWT is a full auth bypass. It is inert while ENVIRONMENT=production,
        but naming it in the Blueprint puts it one dashboard edit away from being set.
        """
        declared = {e["key"] for e in self._service()["envVars"]}
        assert "ALLOW_UNVERIFIED_JWT" not in declared
        assert "DB_ECHO" not in declared, (
            "DB_ECHO logs every statement including parameters — on this schema that is "
            "answers and resume text in the log stream"
        )

    def test_it_does_not_override_the_start_command(self):
        # The Dockerfile's CMD runs `alembic upgrade head` before Uvicorn. A startCommand here
        # would silently skip migrations on every deploy.
        assert "startCommand" not in self._service()
