"""
Prompt caching cannot be allowed to break silently — tests/test_prompt_caching.py

A GD round is up to 26 turns, each re-sending the same ~2100-token rulebook, and it is the
most expensive feature in the product. Caching that prefix reads it at 0.1x input instead
of paying in full, which is roughly 37% off the round.

THE FAILURE MODE IS WHY THIS FILE EXISTS. If the system block stops being byte-identical —
someone adds a template placeholder to gd_panel.md, or switches the call site back to
PromptBuilder.chat — nothing breaks. The round still runs, the output is still correct, and
every single call quietly becomes a cache WRITE at 1.25x input that is never read. So the
cost goes UP by 25% instead of down by 37%, with no error, no log line and no test failure.
That is a bug you find on a bill, months later.
"""

from __future__ import annotations

import pathlib
import re

from app.prompts.prompt_loader import get_prompt_loader
from app.services.ai.base_provider import ProviderRequest
from app.services.ai.prompt_builder import PromptBuilder

BACKEND = pathlib.Path(__file__).resolve().parents[1]
PROMPTS = BACKEND / "app" / "prompts"
API = BACKEND / "app" / "api" / "v1"

#: Templates a call site marks cacheable. Each must be free of placeholders.
#:
#: `report_generator` is the newest and the largest saving. The report is the most
#: expensive call in the product — 17,059 input tokens against a 5,580-token output cap —
#: and 2,778 of those input tokens are this static rubric, previously re-sent and re-billed
#: at full price on every single report. It could not be cached before because the template
#: carried eight $placeholders (candidate name, company, track, duration, question count,
#: delivery, previous performance); those now live in a session brief in the USER message,
#: exactly as _round_brief does for gd_panel. Worth ~$0.0075 a report, ~4.5% of a warm
#: interview, and it scales the right way: a provider cache entry lives about five minutes
#: and every read refreshes it, so the hit rate rises with how busy the product is.
#:
#: `report_generator` IS NO LONGER BUILT. A report is now two prompts — `report_summary` and
#: `report_analysis` — generated concurrently, because one call whose output grew with the
#: interview could not finish a long one inside the wall-clock budget. Both are composed from
#: report_generator.md, which stays as the canonical rubric; tests/test_report_split.py pins
#: that they still contain it. Splitting the prompt IMPROVES the cache rather than diluting
#: it: a batch prompt is re-sent once per batch, so a 13-answer report reads the analysis
#: rubric from the cache twice within one report instead of never.
CACHED_TEMPLATES = ("gd_panel", "interview_panel", "report_summary", "report_analysis")


def _static_templates() -> set[str]:
    """
    Templates built with PromptBuilder.chat_static.

    Paired by parsing the chat_static call itself rather than by "any system_template in a
    file that mentions cache_system" — gd.py builds three different prompts, and the crude
    version claimed all three were cacheable.

    chat_static is the right thing to key on: it IS the mechanism for a byte-identical
    system block, so anything passing through it must be placeholder-free whether or not
    that particular call site also opts into caching.
    """
    found: set[str] = set()
    for path in [*API.glob("*.py"), *(BACKEND / "app" / "services").rglob("*.py")]:
        src = path.read_text()
        for call in re.findall(r"chat_static\(([^)]*)\)", src, re.S):
            found |= set(re.findall(r'system_template="(\w+)"', call))
    return found


def _cache_opt_in_count() -> int:
    """How many call sites pass cache_system=True."""
    total = 0
    for path in [*API.glob("*.py"), *(BACKEND / "app" / "services").rglob("*.py")]:
        total += path.read_text().count("cache_system=True")
    return total


class TestTheCachedPromptIsActuallyStatic:
    def test_the_scanner_finds_the_opt_in(self):
        # Guards every assertion below from passing vacuously. If cache_system or
        # chat_static is renamed, this fails instead of the suite silently covering
        # nothing.
        assert _cache_opt_in_count() >= 1, (
            "no call site passes cache_system=True — either caching was removed, or this "
            "scanner has stopped matching. Fix the scanner before trusting these tests."
        )
        assert _static_templates(), "no template is built with chat_static"

    def test_only_known_templates_are_built_static(self):
        # A new static template must be a deliberate act, because the cost of getting it
        # wrong is silent and permanent.
        unexpected = _static_templates() - set(CACHED_TEMPLATES)
        assert not unexpected, (
            f"these templates are built with chat_static but not listed here: "
            f"{sorted(unexpected)}. Add them to CACHED_TEMPLATES only after confirming "
            "the template has no placeholders — otherwise a call that also opts into "
            "caching costs 25% MORE and never reads."
        )

    def test_exactly_one_call_site_opts_into_caching(self):
        # Not a style rule. Every additional opt-in is another chance for a prompt to
        # regain a placeholder and start costing more, and the only symptom is the bill.
        assert _cache_opt_in_count() == len(CACHED_TEMPLATES), (
            f"{_cache_opt_in_count()} call sites pass cache_system=True but "
            f"{len(CACHED_TEMPLATES)} templates are listed. Every opt-in needs its template "
            "listed here and asserted placeholder-free below — an unlisted one costs 25% "
            "MORE per call, silently, forever."
        )

    def test_a_cached_template_has_no_placeholders(self):
        for name in CACHED_TEMPLATES:
            raw = (PROMPTS / f"{name}.md").read_text()
            placeholders = sorted(set(re.findall(r"\$[a-zA-Z_]\w*", raw)))
            assert not placeholders, (
                f"{name}.md is marked cacheable but still contains {placeholders}. "
                "Every request would then have a unique system prefix, so the cache "
                "marker would bill a 1.25x write on every call and never read. Move the "
                "variable content into the user message — see _round_brief in api/v1/gd.py."
            )

    def test_the_reports_per_session_values_survived_the_move(self):
        """
        Moving a value OUT of the prompt is only safe if it lands in the user message.

        These eight were placeholders in report_generator.md until it was made cacheable.
        Dropping one would not fail anything — the report still generates, the rubric still
        caches — it would just quietly stop telling the model the candidate's name, or how
        they spoke, or how they did last time, and every report afterwards would be a little
        more generic for a reason nobody could see.
        """
        src = (API / "reports.py").read_text()
        brief = src[src.index("session_brief = ") : src.index("messages = prompt_builder")]
        for value in (
            "candidate_name",
            "company.name",
            "track.name",
            "transcript_rows",
            "duration_minutes",
            "delivery_summary",
            "previous_performance",
            "self_assessment",
        ):
            assert value in brief, (
                f"{value} was a placeholder in report_generator.md and is not in the "
                "session brief that replaced it — the model no longer receives it"
            )

    def test_the_system_block_is_byte_identical_across_different_requests(self):
        """
        The property that actually matters, asserted end to end rather than by inspecting
        the template: two genuinely different rounds must produce the same system bytes.
        """
        builder = PromptBuilder(get_prompt_loader())
        a = builder.chat_static("gd_panel", "round one: topic A, transcript A, Sparsh")
        b = builder.chat_static("gd_panel", "round two: topic B, transcript B, Priya")

        assert a[0].role == "system" and b[0].role == "system"
        assert a[0].content == b[0].content, "the system block differs between requests"
        assert a[1].content != b[1].content, "the per-round content should differ"

    def test_every_cached_prefix_clears_the_minimum_size(self):
        # Sonnet 5 only caches prefixes of 1024 tokens or more. Below that the marker is
        # accepted and silently does nothing — no error, no saving. gd_panel.md is the
        # reason this is worth caching at all, so its size is part of the contract.
        for name in CACHED_TEMPLATES:
            approx_tokens = len((PROMPTS / f"{name}.md").read_text()) / 4
            assert approx_tokens >= 1024, (
                f"{name}.md is ~{approx_tokens:.0f} tokens, below Sonnet's 1024-token "
                "minimum cacheable prefix — the cache_control marker would do nothing."
            )


class TestCachingIsOptInPerCall:
    def test_a_request_does_not_cache_by_default(self):
        # The default has to be off. A default-on flag would cache every prompt that
        # carries per-request substitutions, which is the strictly-worse case the
        # provider-level setting was disabled to avoid.
        assert ProviderRequest(messages=[], max_tokens=10).cache_system is False

    def test_chat_static_does_not_substitute(self):
        # chat() renders the template; chat_static must not, or a caller passing a
        # variable could break byte-identity without touching the template.
        builder = PromptBuilder(get_prompt_loader())
        raw = get_prompt_loader().load("gd_panel")
        assert builder.chat_static("gd_panel", "x")[0].content == raw

    def test_the_provider_needs_both_the_flag_and_the_opt_in(self):
        """
        Neither alone may switch caching on. Asserted against the real
        _to_messages so a change to that gating is caught here.
        """
        from app.services.ai.anthropic_provider import AnthropicProvider

        provider = object.__new__(AnthropicProvider)
        msgs = [
            {"role": "system", "content": "static rules"},
            {"role": "user", "content": "this round"},
        ]

        from app.services.ai.base_provider import ProviderMessage

        def system_block(cache_system: bool, provider_flag: bool) -> dict:
            provider._prompt_caching = provider_flag  # type: ignore[attr-defined]
            req = ProviderRequest(
                messages=[ProviderMessage(**m) for m in msgs],
                max_tokens=10,
                cache_system=cache_system,
            )
            system, _turns = provider._split_messages(req)  # type: ignore[attr-defined]
            return system[0]

        assert "cache_control" in system_block(True, True)
        assert "cache_control" not in system_block(True, False), "the kill switch must win"
        assert "cache_control" not in system_block(False, True), "opt-in must be required"
