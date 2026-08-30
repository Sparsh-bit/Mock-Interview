"""
Submitting work nobody is waiting for — services/ai/batch.py

Anthropic's Message Batches API answers a set of requests whenever it gets to them, at
HALF PRICE on both input and output. docs/AI-COST-MODEL.md names it the single largest
saving left in this product, and by a wide margin: about −$0.062 a report, roughly 40% of
a warm interview, which is more than every prompt-caching win put together.

WHAT IT COSTS INSTEAD IS TIME, AND THAT IS THE WHOLE DESIGN CONSTRAINT. A batch is not
slower in the way a slow call is slower — it is answered on the provider's schedule, in
minutes, with a 24-hour ceiling. That is unusable for anything a person is sitting in
front of and free money for anything they are not.

  THE REPORT IS THE ONLY THING IN THIS PRODUCT THEY ARE NOT SITTING IN FRONT OF. The
  interview is over by the time it runs. Every other AI call — the next question, a
  cross-question, a panel turn, a quiz, a code verdict — has somebody waiting on it with
  the page open, and batching one of those would not be a cost optimisation, it would be
  a broken feature.

So this module is deliberately not a general "run this cheaply" helper. `BATCHABLE_FEATURES`
is a closed allowlist and `submit` refuses anything outside it, because the thing that goes
wrong here is not a bug in the batch code — it is somebody later reaching for the cheap path
at a call site where the candidate is waiting, which nothing else in the system would stop.

WHAT LIVES WHERE. This module knows how to submit, poll and collect. It does not know what a
report is, when to give up, or what to do when a batch dies — that is the state machine in
services/report/batch_job.py, which is pure and tested on its own.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from .base_provider import (
    BaseAIProvider,
    CostTier,
    ProviderError,
    ProviderMessage,
    ProviderRequest,
    ProviderResponse,
)
from .provider_factory import get_ai_providers

logger = structlog.get_logger(__name__)


#: The ONLY features allowed to be answered on somebody else's schedule.
#:
#: A closed allowlist rather than a flag on the request, and rather than a cost-tier rule.
#: The question "is anybody waiting for this?" is a property of the FEATURE, not of the
#: model, the price or the caller's mood — so it is answered once, here, by name.
#:
#: Both entries are halves of the same thing: `report_generation` is the summary call and
#: `report_analysis` is the per-question breakdown (services/report/composer.py splits them).
#: Adding to this set means asserting that no human being is looking at a spinner waiting
#: for it. Nothing on the interview, panel, GD, quiz or code path qualifies, and
#: test_report_batch.py pins that.
BATCHABLE_FEATURES: frozenset[str] = frozenset({"report_generation", "report_analysis"})


class BatchNotSupportedError(ProviderError):
    """The configured provider has no batch API. Not a failure — a fact to route around."""


@dataclass(frozen=True)
class BatchPart:
    """
    One request inside a batch, and the identity that survives the round trip.

    `custom_id` is the only link between a result and the work it was asked to do. The
    Batches API returns results in COMPLETION order, not submission order, so without it a
    six-question analysis could be matched to the wrong six questions and the candidate
    would read someone else's feedback under their own question. It is carried in the job
    row as well, so a poll that happens in a different process — or a different day — can
    still make the match.
    """

    custom_id: str
    feature: str
    messages: list[ProviderMessage]
    max_tokens: int
    cost_tier: CostTier = CostTier.BALANCED
    cache_system: bool = False


@dataclass(frozen=True)
class BatchStatus:
    """Where a submitted batch has got to, in the provider's own vocabulary."""

    #: "in_progress" | "canceling" | "ended". Not translated — see AnthropicProvider.
    processing_status: str
    counts: dict[str, int]

    @property
    def ended(self) -> bool:
        return self.processing_status == "ended"

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    @property
    def done(self) -> int:
        """Parts that will not change again, whatever happened to them."""
        return self.total - self.counts.get("processing", 0)


def batching_provider() -> BaseAIProvider | None:
    """
    The first provider in the configured chain that can batch, or None.

    THE FIRST, not any. The chain is ordered by preference and the fallback rungs are free
    tiers that exist to keep the app working when the paid one is refusing — a batch
    submitted to one of those would be neither cheap nor, in most cases, possible. If the
    primary cannot batch, the answer is "no batching", not "try the next one".
    """
    providers = get_ai_providers()
    if not providers:
        return None
    primary = providers[0]
    return primary if primary.supports_batching else None


async def submit(parts: list[BatchPart]) -> tuple[str, str]:
    """
    Submit `parts` as one batch. Returns (provider_name, batch_id).

    Raises BatchNotSupportedError when no provider can batch, and ProviderError when the
    submission itself fails. BOTH ARE EXPECTED and neither is an error the caller should
    surface: the only correct response to either is to do the work synchronously instead,
    which is what api/v1/reports.py does. A report must never be stuck because a cheaper
    way of producing it was unavailable.
    """
    if not parts:
        raise ProviderError("cannot submit an empty batch", provider="unknown")

    forbidden = sorted({p.feature for p in parts} - BATCHABLE_FEATURES)
    if forbidden:
        # A HARD REFUSAL, NOT A WARNING. Reaching this means a call site somebody is
        # waiting on has been pointed at the batch path, and the symptom would be a
        # candidate watching a spinner for anywhere up to 24 hours. Failing loudly in the
        # test suite is the entire value of this check — in production it can only fire
        # after that mistake has already shipped.
        raise ProviderError(
            f"features {forbidden} are not batchable. The Batches API answers on the "
            "provider's schedule (minutes, up to 24h), so it may only be used where "
            "nobody is waiting for the result. See BATCHABLE_FEATURES.",
            provider="unknown",
        )

    provider = batching_provider()
    if provider is None:
        raise BatchNotSupportedError(
            "the primary AI provider has no batch API", provider="unknown"
        )

    requests = [
        provider.build_batch_request(  # type: ignore[attr-defined]
            part.custom_id,
            ProviderRequest(
                messages=part.messages,
                json_mode=True,
                max_tokens=part.max_tokens,
                cost_tier=part.cost_tier,
                cache_system=part.cache_system,
            ),
        )
        for part in parts
    ]
    batch_id = await provider.submit_batch(requests)  # type: ignore[attr-defined]
    logger.info(
        "ai_batch_submitted",
        provider=provider.provider_name,
        batch_id=batch_id,
        parts=len(parts),
        features=sorted({p.feature for p in parts}),
    )
    return provider.provider_name, batch_id


async def poll(batch_id: str) -> BatchStatus:
    """How far along a submitted batch is. Raises ProviderError if it cannot be reached."""
    provider = batching_provider()
    if provider is None:
        raise BatchNotSupportedError(
            "the primary AI provider has no batch API", provider="unknown"
        )
    status, counts = await provider.retrieve_batch(batch_id)  # type: ignore[attr-defined]
    return BatchStatus(processing_status=status, counts=counts)


async def collect(batch_id: str) -> dict[str, ProviderResponse | str]:
    """
    Every finished part of an ended batch, keyed by custom_id.

    A succeeded part is a ProviderResponse costed at the batch rate; a failed one is a
    string naming what happened ("errored", "expired", "canceled", "refused"). Per-part
    failure is an ordinary outcome, not an exception — the report already knows how to be
    built out of the parts that landed.
    """
    provider = batching_provider()
    if provider is None:
        raise BatchNotSupportedError(
            "the primary AI provider has no batch API", provider="unknown"
        )
    return await provider.batch_results(batch_id)  # type: ignore[attr-defined]
