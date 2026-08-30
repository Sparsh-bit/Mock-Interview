"""
Reading a JSON answer while it is still being written — services/ai/stream_parser.py

THE PROBLEM. The panel's answer is a JSON object:

    {"turns": [{"speaker": "Anil", "text": "...", "tone": "asking"}, ...],
     "asked_question": true, "candidate_turn": "answered"}

and the candidate waits for the WHOLE of it before a word appears on screen. On a four-line
turn that is most of a second of nothing, at the moment they are most alert — the interviewer
has stopped talking and they are waiting to be asked something.

The model writes that object left to right. The first line is finished long before the last
one starts. This class reads the deltas as they arrive and hands back each `{speaker, text,
tone}` the moment it closes, so the room can start speaking while the rest is still being
written.

WHAT IT IS EMPHATICALLY NOT. It is not a JSON parser, it does not replace one, and nothing it
emits is allowed to be saved, cached or scored. `generate_structured` still parses and
validates the COMPLETE body through the same `InterviewPanelTurn` schema as before, and that
result is the one that counts. This produces provisional text for display, and the
distinction is the whole safety argument:

    half a JSON object parses as NOTHING, which is safe.
    half a JSON object that happens to parse is the dangerous case, and it is exactly what a
    naive "try json.loads on every prefix" would produce — a turn with two of its four lines,
    indistinguishable from a turn that only had two.

So the contract is: emit early, believe late. A caller renders what comes out of here and then
RECONCILES against the validated object. `api/v1/panel.py` does that, and
`tests/test_panel_streaming.py` pins that an interrupted stream leaves nothing saved.

WHY HAND-WRITTEN RATHER THAN A LIBRARY. What is needed is narrow — find complete objects
inside one known array — and the alternatives are not. A partial-JSON library returns a
best-effort object for any prefix, which means it returns the dangerous case by design; using
one would mean writing this discrimination on top of it anyway.

IT IS DELIBERATELY CONSERVATIVE. Anything it cannot read with certainty it simply does not
emit, and the reconcile at the end fills the gap. The worst outcome available to it is that
nothing appears early and the turn arrives as it does today — which is exactly the behaviour
being improved on, so its own failure mode is the status quo.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field

#: The array whose elements are emitted as they complete. Named rather than discovered so this
#: cannot start emitting objects out of some other part of a response it was not asked about.
_ARRAY_KEY = "turns"


@dataclass
class StreamedObjects:
    """
    Feed it text deltas; it yields each complete object inside `"turns": [...]`.

    Stateful and single-use, like the stream it reads. Not thread-safe and does not need to
    be: one instance belongs to one response.
    """

    #: Everything seen so far. Kept whole because the validated parse at the end needs it, and
    #: because an object can straddle any number of deltas — a delta is often a few characters.
    buffer: str = ""
    #: Where scanning resumed last time. Without it every delta would re-scan the whole buffer,
    #: which is quadratic in the length of the answer for no benefit.
    _cursor: int = 0
    #: True once the opening bracket of the array has been seen.
    _in_array: bool = False
    _emitted: int = 0
    #: Objects already emitted, so a caller can reconcile without keeping its own copy.
    seen: list[dict] = field(default_factory=list)

    def feed(self, delta: str) -> Iterator[dict]:
        """
        Add a delta and yield any objects that completed because of it.

        Yields plain dicts, NOT validated models. Validation happens once, at the end, on the
        whole body — see the module docstring on why a validated partial is the dangerous
        thing rather than the safe one.
        """
        self.buffer += delta
        yield from self._drain()

    def _drain(self) -> Iterator[dict]:
        if not self._in_array:
            start = self._find_array_start()
            if start is None:
                return
            self._in_array = True
            self._cursor = start

        while True:
            obj_start = self.buffer.find("{", self._cursor)
            if obj_start == -1:
                return
            end = _match_object(self.buffer, obj_start)
            if end is None:
                # Incomplete. Leave the cursor where it is so the next delta re-tries from
                # the same opening brace rather than skipping past a half-written object.
                return
            raw = self.buffer[obj_start:end]
            self._cursor = end
            try:
                parsed = json.loads(raw)
            except ValueError:
                # Not our shape, or an escape this scanner mis-measured. Skipping is the
                # conservative move: the reconcile at the end has the real object.
                continue
            if isinstance(parsed, dict):
                self._emitted += 1
                self.seen.append(parsed)
                yield parsed

    def _find_array_start(self) -> int | None:
        """
        The index just after `"turns": [`, or None while it has not arrived yet.

        Anchored on the key rather than on the first `[` in the body, so a bracket inside a
        string earlier in the object — or a different array entirely — cannot start emission.
        """
        match = re.search(rf'"{_ARRAY_KEY}"\s*:\s*\[', self.buffer)
        return match.end() if match else None


def _match_object(text: str, start: int) -> int | None:
    """
    The index one past the `}` closing the object that opens at `start`, or None if it has not
    closed yet.

    STRING-AWARE, AND THAT IS THE ENTIRE REASON THIS IS NOT `text.find("}")`. Interview
    dialogue is full of braces and quotes — a panelist saying "then the `{` closes the block",
    a correction quoting code — and counting braces without knowing which are inside a string
    closes the object early and emits a truncated line. Backslash escapes are honoured for the
    same reason: `\\"` inside a quoted line is not the end of that line.
    """
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            # Only meaningful inside a string, but harmless outside one: valid JSON has no
            # backslash between tokens, so this can never skip a structural character.
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return None
