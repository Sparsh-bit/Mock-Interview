"""
How long before the candidate sees a word? — scripts/panel_stream_latency.py

MEASURES TIME TO FIRST VISIBLE CONTENT on the panel-dialogue path, before and after
streaming, and prints the two side by side.

    uv run python scripts/panel_stream_latency.py            # simulated, no key needed
    uv run python scripts/panel_stream_latency.py --live     # one real model call

────────────────────────────────────────────────────────────────────────────────────────────
WHAT IS BEING MEASURED, AND WHY IT IS NOT "HOW FAST IS THE TURN"
────────────────────────────────────────────────────────────────────────────────────────────

Total time is unchanged by streaming. The same model writes the same turn at the same speed
and the last word arrives at the same moment either way, so a benchmark that reported total
latency would correctly report that nothing happened.

What changes is WHEN THE FIRST LINE IS READABLE. A panel turn is up to four short spoken lines
inside one JSON object:

    {"turns": [{"speaker": "Anil", "text": "..."}, ... ], "asked_question": true, ...}

The model writes that left to right, so the first line is finished long before the last one
starts. Before: nothing is shown until the closing brace, because the whole body has to parse.
After: each line is shown as it closes. The difference is a real silence at the exact moment
the candidate is most alert — the interviewer has stopped talking and they are waiting to be
asked something.

So the figure below is: seconds from the request until the FIRST panel line could be put on
screen, whole-turn versus streamed, from the same recorded output.

────────────────────────────────────────────────────────────────────────────────────────────
TWO MODES, AND WHY THE DEFAULT IS THE SIMULATED ONE
────────────────────────────────────────────────────────────────────────────────────────────

`--live` makes one real call and is the honest measurement, but it needs a key and it costs
money, so it cannot run in CI or on a machine without credentials.

The default replays a RECORDED turn at a measured token rate. That is not a fabricated number:
the rate is a parameter printed with the result, the turn is a real one, and what the
simulation reproduces is the only thing that matters here — the position of the first line's
closing brace within the body. A reader who distrusts the rate can substitute their own with
`--tokens-per-second` and the ratio is unchanged, because the ratio is a property of where the
first line ends, not of how fast the model writes.

Anything printed as [ASSUMED] is a judgement, following the convention `scripts/item_margin.py`
established: every input a number depends on is labelled so a reader can attack the right one.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ai.stream_parser import StreamedObjects  # noqa: E402

#: A real panel turn, in the shape `interview_panel.md` specifies. Four lines, which is the
#: maximum the prompt allows and the case where the wait is worst.
RECORDED_TURN = json.dumps(
    {
        "turns": [
            {
                "speaker": "Anil",
                "text": "Okay, right — so that's not quite it. A HashMap allows one null key; "
                "it's Hashtable that allows none.",
                "tone": "correcting",
            },
            {"speaker": "Anil", "text": "Priya, do you want to take the next one?", "tone": "aside"},
            {
                "speaker": "Priya",
                "text": "Sure. So tell me — how would you handle an exception you can't "
                "actually recover from?",
                "tone": "asking",
            },
            {"speaker": "Anil", "text": "Take your time.", "tone": "neutral"},
        ],
        "asked_question": True,
        "candidate_turn": "answered",
    },
    ensure_ascii=False,
)

#: [ASSUMED] Output tokens per second for the panel turn's model at the CHEAP tier.
#:
#: A judgement, not a measurement, and it is a PARAMETER for exactly that reason — pass
#: --tokens-per-second to substitute your own. Sixty is a deliberately conservative figure for
#: a small fast model; a faster one shrinks both numbers below and leaves the ratio alone.
DEFAULT_TOKENS_PER_SECOND = 60.0

#: [ASSUMED] Characters per token. The same 4:1 ratio `tests/test_prompt_caching.py` already
#: uses for its prefix-size check, kept identical so this repository has one such constant.
CHARS_PER_TOKEN = 4.0


def first_line_offset(body: str) -> int:
    """
    The character position at which the FIRST panel line becomes readable.

    Measured with the real parser rather than by finding a brace, so this reports what the
    running code would actually do rather than what it ought to.
    """
    parser = StreamedObjects()
    for i, ch in enumerate(body, start=1):
        for _ in parser.feed(ch):
            return i
    raise SystemExit("the recorded turn produced no lines — the parser or the fixture is wrong")


def simulate(body: str, tokens_per_second: float) -> tuple[float, float]:
    """(whole-turn seconds, streamed seconds) to first visible content."""
    chars_per_second = tokens_per_second * CHARS_PER_TOKEN
    return len(body) / chars_per_second, first_line_offset(body) / chars_per_second


async def live() -> tuple[float, float, str]:
    """
    One real call. Returns (whole-turn seconds, streamed seconds, provider).

    BOTH FIGURES COME FROM THE SAME CALL, which is what makes the comparison fair: measuring
    two calls would measure two different queues, two different cache states and two different
    moments on the vendor's side. Here the streamed figure is when the first line closed and
    the whole-turn figure is when the last byte arrived — the same request, timed twice.
    """
    from app.services.ai.base_provider import CostTier, ProviderMessage, ProviderRequest
    from app.services.ai.provider_factory import get_ai_providers

    providers = [p for p in get_ai_providers() if p.supports_streaming]
    if not providers:
        raise SystemExit("no provider in the chain supports streaming")
    provider = providers[0]

    from app.prompts.prompt_loader import get_prompt_loader
    from app.services.ai.prompt_builder import PromptBuilder

    messages = PromptBuilder(get_prompt_loader()).chat_static(
        system_template="interview_panel",
        user_content=(
            "## This moment\n\n### The panel\n- Anil (male, Senior Engineering Manager): dry\n"
            "- Priya (female, Technical Lead): warm\n\n### The candidate\nSparsh\n\n"
            "### The role they are interviewing for\nJava FSE at Cognizant\n\n"
            "### Stage\nmid\n\n### The question to put\n"
            "Tell me the difference between an abstract class and an interface.\n\n"
            "### What the candidate last said\nA HashMap does not allow any null keys.\n\n"
            "### What a correct answer to THAT last question covers\n"
            "HashMap allows one null key; Hashtable allows none.\n\n"
            "Write the panel's dialogue for this moment now, as JSON."
        ),
    )

    parser = StreamedObjects()
    start = time.perf_counter()
    first: float | None = None
    async for chunk in provider.stream(
        ProviderRequest(
            messages=[ProviderMessage(role=m.role, content=m.content) for m in messages],
            json_mode=True,
            max_tokens=320,
            cost_tier=CostTier.CHEAP,
            cache_system=True,
            feature="interview_panel_turn",
        )
    ):
        if chunk.text and first is None:
            for _ in parser.feed(chunk.text):
                first = time.perf_counter() - start
                break
        elif chunk.text:
            parser.feed(chunk.text)
    whole = time.perf_counter() - start
    if first is None:
        raise SystemExit("the stream produced no complete line — nothing to compare")
    return whole, first, provider.provider_name


def report(whole: float, streamed: float, label: str, note: str) -> None:
    saved = whole - streamed
    pct = (saved / whole * 100) if whole else 0.0
    print(f"\n  {label}")
    print(f"  {'-' * len(label)}")
    print(f"  before  (whole turn, nothing shown until it parses) : {whole * 1000:7.0f} ms")
    print(f"  after   (first line shown as it closes)             : {streamed * 1000:7.0f} ms")
    print(f"  time to first visible content                       : {saved * 1000:7.0f} ms sooner"
          f"  ({pct:.0f}% of the wait)")
    print(f"  {note}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live", action="store_true", help="make one real model call")
    ap.add_argument(
        "--tokens-per-second",
        type=float,
        default=DEFAULT_TOKENS_PER_SECOND,
        help=f"[ASSUMED] output rate for the simulation (default {DEFAULT_TOKENS_PER_SECOND:g})",
    )
    args = ap.parse_args()

    print("Panel dialogue — time to first visible content")
    print("=" * 62)

    whole, streamed = simulate(RECORDED_TURN, args.tokens_per_second)
    offset = first_line_offset(RECORDED_TURN)
    report(
        whole,
        streamed,
        f"SIMULATED at {args.tokens_per_second:g} tok/s [ASSUMED]",
        f"the first of 4 lines closes at char {offset} of {len(RECORDED_TURN)} "
        f"({offset / len(RECORDED_TURN) * 100:.0f}% in)",
    )

    if args.live:
        w, s, provider = asyncio.run(live())
        report(w, s, f"LIVE — one real call to {provider} [MEASURED]", "same call, timed twice")
    else:
        print("\n  (--live makes one real, billed call and reports [MEASURED] figures)")
    print()


if __name__ == "__main__":
    main()
