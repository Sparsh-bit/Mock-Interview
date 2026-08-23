"""
A panelist's name is recognised however the model wrote it — tests/test_panel_speaker_names.py

NOT THE CAUSE OF "priya is not speaking", and worth saying so plainly: a census of eight real
generated turns came back with 5 "Anil" and 13 "Priya", every one spelled canonically, so the
model is not the thing that was dropping her. That bug was in the browser (see
frontend/src/hooks/useSpeech.silent-voice.test.ts).

But the filter this pins WAS a silent drop waiting to happen, and it fails in exactly the shape
that took two rounds of reports to find: `c.speaker in INTERVIEWER_NAMES` was an exact,
case-sensitive membership test, so a contribution written as "priya" or "Priya:" was discarded
with no log, no fallback and no trace. It also fails ASYMMETRICALLY — whichever name a model
capitalises consistently keeps working — so it presents as one person going quiet rather than
as anything being broken.
"""

from __future__ import annotations

import pytest

from app.api.v1.panel import INTERVIEWER_NAMES, canonical_speaker


class TestAKnownPanelistIsAlwaysRecognised:
    @pytest.mark.parametrize("name", INTERVIEWER_NAMES)
    def test_the_canonical_spelling(self, name: str):
        assert canonical_speaker(name) == name

    @pytest.mark.parametrize(
        "written",
        [
            "priya",
            "PRIYA",
            "PrIyA",
            " Priya ",
            "Priya:",
            "Priya :",
            "Priya-",
            "Priya.",
            "Priya,",
            "\tPriya\n",
        ],
    )
    def test_however_the_model_wrote_it(self, written: str):
        assert canonical_speaker(written) == "Priya", (
            f"{written!r} is Priya. Dropping it silently removes a panelist from the "
            "interview, which is how a two-person panel becomes one."
        )

    def test_the_canonical_spelling_is_returned_not_the_input(self):
        # The browser hands this name straight to /tts/speak to resolve a voice, and it goes
        # into the stored transcript and the report. Passing "priya" through would put a
        # lowercase name on screen.
        assert canonical_speaker("priya") == "Priya"
        assert canonical_speaker("anil") == "Anil"


class TestAnyoneElseIsStillRejected:
    @pytest.mark.parametrize(
        "written",
        [
            "",
            "   ",
            ":",
            "Sparsh",
            "the candidate",
            "Interviewer",
            "Priya Sharma",
            "Anil and Priya",
        ],
    )
    def test_not_a_panelist(self, written: str):
        # Normalising must not become "accept anything". The candidate's own name appearing as
        # a speaker would put words in their mouth in their own transcript, and the prompt
        # explicitly forbids it — so this filter is the enforcement.
        assert canonical_speaker(written) is None
