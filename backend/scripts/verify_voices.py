"""
Check every configured TTS voice against the catalogue — scripts/verify_voices.py

    cd backend && uv run python scripts/verify_voices.py

WHY THIS EXISTS.

Meera has been given a male voice twice. Both times it shipped, both times a candidate
heard it before anyone here did, and the second time was after it had supposedly been
fixed. That is not a mistake worth being careful about — being careful is what already
failed. It is a mistake worth making checkable.

The genders are not written down here. They are read from `PANELISTS` in api/v1/gd.py and
`INTERVIEWERS` in api/v1/panel.py, which are the same declarations the prompt and the
transcript use. A second list would only be a second thing to get out of step with the
first — which is the whole failure mode.

WHAT IT CHECKS, per configured speaker:

  * the voice id resolves at all — a typo'd id is a 400 from the vendor, not a fallback
  * the vendor's own gender tag matches the gender the panel declares
  * the accent is neutral English: not British, not any other regional variant. Requested
    directly, and it also keeps a stray en-GB voice out of an Indian campus panel.
  * it is not tagged `old` — the voice previously assigned to Anil was, and "old" is what a
    senior engineering manager was actually hearing rather than "senior"

NOT run in CI, and deliberately. It needs a live FISH_API_KEY and it spends nothing but it
does hit the vendor; CI has neither the key nor a reason to. Run it whenever TTS_VOICE_IDS
changes — that is the only moment it can catch anything.

Exit status is 0 when every voice passes and 1 otherwise, so it can gate a deploy script.
"""

from __future__ import annotations

import asyncio
import sys

import httpx

from app.api.v1.gd import PANELISTS
from app.api.v1.panel import INTERVIEWERS
from app.core.config import settings
from app.services.tts.factory import panel_voice_id

_MODEL_API = "https://api.fish.audio/model"

#: Accent markers that disqualify a voice, checked against title, description and tags.
#:
#: "british" and friends are here by request — a British interviewer is the wrong character
#: for an Indian campus panel, more incongruous than a neutral American one. The rest are
#: here because a voice tagged for one specific elsewhere is a voice tagged for the wrong
#: elsewhere; neutral is what was asked for.
_BAD_ACCENTS = (
    "british",
    "england",
    "scottish",
    "irish",
    "australian",
    "cockney",
    "german",
    "french",
    "spanish",
    "turkish",
    "russian",
    "japanese",
    "korean",
    "chinese",
    "arabic",
    "african",
    "filipino",
)


def _expected_genders() -> dict[str, str]:
    """Speaker name → the gender the panel declares. Read from the panels themselves."""
    out = {p.name: p.gender.lower() for p in PANELISTS}
    out.update({i.name: i.gender.lower() for i in INTERVIEWERS})
    return out


async def _fetch(client: httpx.AsyncClient, voice_id: str) -> dict | None:
    try:
        r = await client.get(
            f"{_MODEL_API}/{voice_id}",
            headers={"Authorization": f"Bearer {settings.FISH_API_KEY}"},
        )
    except httpx.HTTPError as exc:
        print(f"    request failed: {exc}")
        return None
    if r.status_code != 200:
        print(f"    catalogue lookup returned {r.status_code}")
        return None
    return r.json()


async def main() -> int:
    if not settings.FISH_API_KEY:
        print("FISH_API_KEY is not set — nothing to verify.")
        return 1
    if settings.TTS_PROVIDER != "fish":
        print(f"TTS_PROVIDER is {settings.TTS_PROVIDER!r}; this script only knows Fish.")
        return 1

    expected = _expected_genders()
    failures = 0

    async with httpx.AsyncClient(timeout=30.0) as client:
        for name, want in sorted(expected.items()):
            voice_id = panel_voice_id(name)
            if not voice_id:
                # Not a failure. A speaker with no voice falls back to browser speech for
                # that speaker alone, which is a deliberate, working degradation.
                print(f"  --   {name:<12} no voice configured (browser speech)")
                continue

            model = await _fetch(client, voice_id)
            if model is None:
                print(f"  FAIL {name:<12} {voice_id} is not a usable voice id")
                failures += 1
                continue

            tags = {t.lower() for t in (model.get("tags") or [])}
            title = model.get("title", "")
            blob = f"{title} {model.get('description') or ''} {' '.join(tags)}".lower()

            problems = []
            # Exactly one gender tag. Both or neither means the catalogue cannot answer the
            # question, and an unanswerable check must fail rather than pass quietly — that
            # is how the Meera mismatch survived a review in the first place.
            if ("male" in tags) == ("female" in tags):
                problems.append("catalogue does not state a single gender")
            else:
                got = "female" if "female" in tags else "male"
                if got != want:
                    problems.append(f"gender is {got}, panel says {want}")

            bad = [a for a in _BAD_ACCENTS if a in blob]
            if bad:
                problems.append(f"non-neutral accent: {', '.join(bad)}")
            if "old" in tags:
                problems.append("tagged 'old' — reads as tired rather than senior")

            if problems:
                failures += 1
                print(f"  FAIL {name:<12} {title[:34]!r}")
                for p in problems:
                    print(f"         - {p}")
            else:
                print(f"  ok   {name:<12} {want:<6} {title[:34]!r}")

    print()
    if failures:
        print(f"{failures} voice(s) wrong. Fix TTS_VOICE_IDS before deploying.")
        return 1
    print("Every configured voice matches its speaker.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
