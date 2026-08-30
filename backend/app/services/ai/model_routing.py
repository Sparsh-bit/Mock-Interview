"""
Which calls are worth a smaller model — services/ai/model_routing.py

`CostTier.CHEAP` has always meant "this task is not worth paying to REASON about": no
thinking budget, low effort. What it did NOT mean, until now, was a different model. Every
tier resolved to the same one, so the cheapest tier in the product still ran on Sonnet and
the price sheet's entry for Haiku — priced, tested, correct — was never selected by anything.

Haiku 4.5 is $1/$5 per million against Sonnet 5's $3/$15. Three times cheaper on both halves,
for tasks where the prompt already contains the rubric and the answer is a short piece of
structured text.

WHY THIS IS A MODULE AND NOT A DICTIONARY IN THE PROVIDER. Two reasons, and the second is the
one that matters.

  A provider must not contain business logic — base_provider.py says so in as many words, and
  "which features deserve which model" is exactly that. `burst_rung.py` is the precedent:
  the same shape of decision (feature + cost tier -> may this call go somewhere cheaper) kept
  out of the vendor code.

  And the decision is not vendor-shaped anyway. What model NAME a cheap call gets is a fact
  about Anthropic; whether a call can TOLERATE a smaller model is a fact about the feature.
  Mixing them means a second provider with a cheap tier has to re-derive the feature list.

WHAT THE MEASUREMENT ACTUALLY SAID, because it did not say what this was expected to say.
Nine realistic panel moments, both models, identical inputs, run twice
(docs/AI-COST-MODEL.md carries the table):

  Haiku won on everything countable except the one that matters here. 60-70% cheaper, same
  latency, 9/9 parseable, no invented speakers, and BETTER than Sonnet at setting the
  `asked_question` flag.

  And it broke the panel's own rules, reproducibly. interview_panel.md says "One or two
  sentences" and "Twenty-five words". Haiku produced SIX over-length lines out of ~21 in
  each run — longest 46 words, then 41 — where Sonnet produced ZERO in both. It used the
  candidate's name in a turn whose brief said in capitals not to. On a wrong answer it
  explained ConcurrentModificationException rather than asking the follow-up, which is
  exactly the lecturing that prompt was rewritten to stop and that
  tests/test_panel_brevity.py exists to guard.

SO THE ROUTING SHIPS SWITCHED OFF. ANTHROPIC_CHEAP_MODEL defaults to empty, and everything
here is inert until somebody sets it. This module is not the decision; it is the mechanism,
and the decision is a value in the environment because it is a trade — a real saving against
a measured regression — and a trade is not a default.

THE ALLOWLIST IS STILL NARROW, and would be even if the numbers had come out clean. The
other CHEAP call sites SCORE things — a GD round, a communication drill — and a scoring
model that is subtly more generous is a worse product in a way nobody notices from a diff.
Two more write into caches shared with every other candidate on the track. Panel dialogue
is the only CHEAP feature where being slightly worse costs a slightly flatter interviewer
rather than somebody's grade.
"""

from __future__ import annotations

from .base_provider import CostTier

#: Features whose CHEAP calls may run on the cheap model.
#:
#: BOTH OF THESE ARE PANEL DIALOGUE, and dialogue is the right first case for a smaller
#: model for a reason that is worth stating: the output is three or four spoken lines of
#: under twenty-five words each, the rules for them are spelled out at length in the system
#: prompt, and the failure mode of getting one slightly wrong is a slightly flatter
#: interviewer — not a wrong score on somebody's report.
#:
#: WHAT IS DELIBERATELY NOT HERE, and why each was left out:
#:
#:   gd_evaluation, communication_evaluation — these SCORE a candidate. A cheaper model that
#:     marks half a point more generously produces a report that is wrong in a direction
#:     nobody can see, on the thing the candidate came for. Not a latency or a formatting
#:     risk; a correctness one.
#:   question_bank — the shared pool. One weak batch is cached and served to EVERY candidate
#:     on that track until it ages out, so a quality regression here does not stay with the
#:     session that caused it.
#:   study_resources — writes into a globally shared cache, same argument as question_bank.
#:
#: Adding to this set is a measurement, not an opinion. The comparison harness that produced
#: the numbers in AI-COST-MODEL.md is the bar — and note that panel dialogue itself did not
#: clear it. These two are listed because they are the only features a smaller model could
#: ever be appropriate for, not because it has been shown to be good enough for them.
CHEAP_MODEL_FEATURES: frozenset[str] = frozenset(
    {
        "gd_panel_turn",
        "interview_panel_turn",
    }
)

#: The only tier eligible. A call asking for BALANCED or DEEP is saying the answer matters,
#: whatever its feature name is on the allowlist above.
CHEAP_MODEL_COST_TIER = CostTier.CHEAP


def wants_cheap_model(*, feature: str | None, cost_tier: CostTier) -> bool:
    """
    May this call run on the provider's cheap model?

    BOTH GATES, and neither is sufficient alone — the same structure as burst_rung_allows,
    and for the same reason. A cost tier alone would route every CHEAP call, including the
    two that score a candidate. A feature alone would route a panel turn that had been
    deliberately raised to BALANCED because something about it needed more.

    `feature` is None for a call that did not declare one. Answers False: an unnamed call
    cannot be on an allowlist, and defaulting to the configured model is the direction where
    being wrong costs money rather than quality.
    """
    return bool(feature) and cost_tier == CHEAP_MODEL_COST_TIER and feature in CHEAP_MODEL_FEATURES
