/**
 * The panel's stage directions, for the eye — lib/speech/gesture.ts
 *
 * THE REPORT: "i cannot see the panaelist laugh and a sort of smile and all the gestures that
 * the normal human do in an interview".
 *
 * The panel was already laughing. Rule 5 of `prompts/interview_panel.md` tells it to and
 * gives the exact format — `*(laughs)* No, fair enough.`, `*(both laugh)*` — so the model was
 * doing as it was told. Two different things then failed to happen with the result:
 *
 *   THE EAR got the marker verbatim, so a panelist said the WORD "laughs" where a person
 *   would have laughed. Fixed in `speakable.ts`, which strips it before the vendor sees it.
 *
 *   THE EYE got it verbatim too. `PanelThread` rendered `line.text` straight into a <p>, so
 *   the candidate read the literal characters `*(laughs)*` — raw markup in the middle of a
 *   conversation. Which is why the panel read as a machine at precisely the moments written
 *   to make it read as human.
 *
 * This module is the eye's half: it splits a line into the words that were said and the
 * directions that were performed, so the thread can render a laugh as a laugh instead of as
 * punctuation. One parser, shared, because the alternative is the screen and the voice
 * disagreeing about what counts as a gesture — and that disagreement is exactly how the
 * marker survived to the vendor in the first place.
 *
 * WHY NOT JUST DELETE THEM FROM THE SCREEN TOO. Because they are real information: a
 * candidate rereading the thread should be able to see that the room laughed there, the same
 * way a script tells an actor. Shown as an aside, in the panel's own voice, never spoken.
 */

/** One piece of a panel line: either words that were said, or something that was done. */
export interface LinePart {
  kind: 'said' | 'gesture';
  text: string;
}

/*
 * ONE PATTERN, USED BY BOTH HALVES, and it is deliberately narrow.
 *
 * The asterisk-wrapped form is what the prompt asks for and is unambiguous. The bare form is
 * an allowlist rather than "any parentheses", because an unrestricted `(...)` would silently
 * eat real parenthetical speech — "the JDK (which includes the compiler)" is content the
 * candidate needs, not an aside. Getting that wrong would turn a cosmetic bug into a
 * comprehension one.
 *
 * Kept in step with the equivalent rules in speakable.ts by the shared test for both.
 */
const GESTURE =
  /\*\(([^)]{0,40})\)\*|\((\s*(?:both\s+)?(?:laughs?|laughing|chuckles?|chuckling|smiles?|smiling|grins?|sighs?|pauses?)\s*)\)/gi;

/**
 * Split a panel line into what was said and what was done, in order.
 *
 * Returns a single `said` part for the overwhelmingly common case of a line with no
 * directions in it, so the caller needs no special path for it.
 */
export function splitGestures(text: string): LinePart[] {
  if (!text) return [];
  const parts: LinePart[] = [];
  let cursor = 0;

  // `matchAll` rather than a while-loop over `exec`, so there is no shared `lastIndex` to
  // leak between calls — a stateful regex reused across renders is a bug that only appears
  // on the second line.
  for (const match of text.matchAll(GESTURE)) {
    const at = match.index ?? 0;
    const said = text.slice(cursor, at).trim();
    if (said) parts.push({ kind: 'said', text: said });
    const inner = (match[1] ?? match[2] ?? '').trim();
    if (inner) parts.push({ kind: 'gesture', text: inner });
    cursor = at + match[0].length;
  }

  const tail = text.slice(cursor).trim();
  if (tail) parts.push({ kind: 'said', text: tail });
  return parts;
}

/** True when a line contains any stage direction at all. */
export function hasGesture(text: string): boolean {
  // A fresh regex, because the module-level one carries `g` and therefore `lastIndex`.
  return new RegExp(GESTURE.source, 'i').test(text || '');
}
