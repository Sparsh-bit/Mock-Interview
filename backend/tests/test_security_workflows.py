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
        assert "image-ref: hotseat-backend:scan" in raw

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
