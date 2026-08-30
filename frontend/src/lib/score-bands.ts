/**
 * What a score means, and what colour that is — lib/score-bands.ts
 *
 * THERE WERE THREE DIFFERENT ANSWERS TO THIS QUESTION IN THE CODEBASE.
 *
 *   `composer.score_label` in the backend banded at 85 / 70 / 55 / 40 and produced the words
 *   the candidate actually reads: Excellent, Good, Satisfactory, Needs Improvement,
 *   Significant Gaps.
 *
 *   The report page's bar colours banded at 75 / 50 / 30 — a different set entirely, invented
 *   separately.
 *
 * So a 72 was printed as **Good** next to a bar the same colour as a 51, and a 76 turned green
 * while still being labelled the same as the amber 71 beside it. Nobody had decided that; two
 * people had decided two things and neither knew about the other.
 *
 * ONE SET OF NUMBERS, AND THEY ARE THE BACKEND'S. The backend's are the ones with words
 * attached, the words are what the candidate reads, and a colour that disagrees with the word
 * next to it makes the word look like a mistake. `score-bands.test.ts` reads the thresholds
 * back out of `composer.py` and fails if the two ever drift again — which is the only kind of
 * guard that survives somebody editing the Python without opening this file.
 *
 * FIVE BANDS, FIVE COLOURS, one meaning each, per the palette's own rule:
 *
 *   emerald   cleared comfortably
 *   teal      cleared
 *   indigo    neither passed nor failed — the honest colour for "satisfactory"
 *   amber     short of the bar
 *   coral     well short
 *
 * Note that green does NOT run all the way down to the middle. A 56 tinted green tells
 * somebody they are fine when the report is about to tell them they are not.
 */

export interface ScoreBand {
  /** The floor of this band, inclusive. */
  floor: number;
  /** The word the report prints. Kept identical to the backend's, deliberately. */
  label: string;
  /** Bar and solid-fill class. The BARE tone: a graphic, where 3:1 is the bar. */
  bar: string;
  /** SVG stroke, for rings and paths. Same tone as `bar`, different property. */
  stroke: string;
  /** Background + text pair for a chip or badge. Both from the same hue family. */
  chip: string;
  /**
   * Text colour on the page ground — the `-ink` tone, the only one that clears 4.5:1 at small
   * sizes.
   *
   * Carried explicitly rather than derived from `chip` by splitting on spaces and hunting for
   * the class that starts with `text-`. I wrote that version first; it typechecked badly, and
   * more importantly it made the band's text colour depend on the ORDER of two classes inside
   * an unrelated string. Reordering `chip` for readability would silently change what colour
   * the report's headline score is.
   */
  ink: string;
}

/** Ordered high to low, so the first match wins. */
export const SCORE_BANDS: readonly ScoreBand[] = [
  {
    floor: 85,
    label: 'Excellent',
    bar: 'bg-accent-emerald',
    stroke: 'stroke-accent-emerald',
    chip: 'bg-accent-emerald-soft text-accent-emerald-ink',
    ink: 'text-accent-emerald-ink',
  },
  {
    floor: 70,
    label: 'Good',
    bar: 'bg-accent-teal',
    stroke: 'stroke-accent-teal',
    chip: 'bg-accent-teal-soft text-accent-teal-ink',
    ink: 'text-accent-teal-ink',
  },
  {
    floor: 55,
    label: 'Satisfactory',
    bar: 'bg-accent-indigo',
    stroke: 'stroke-accent-indigo',
    chip: 'bg-accent-indigo-soft text-accent-indigo-ink',
    ink: 'text-accent-indigo-ink',
  },
  {
    floor: 40,
    label: 'Needs Improvement',
    bar: 'bg-accent-amber',
    stroke: 'stroke-accent-amber',
    chip: 'bg-accent-amber-soft text-accent-amber-ink',
    ink: 'text-accent-amber-ink',
  },
  {
    floor: -Infinity,
    label: 'Significant Gaps',
    bar: 'bg-accent-coral',
    stroke: 'stroke-accent-coral',
    chip: 'bg-accent-coral-soft text-accent-coral-ink',
    ink: 'text-accent-coral-ink',
  },
] as const;

/**
 * The band a score falls in. Never returns undefined — the last band's floor is -Infinity, so
 * a negative or NaN-adjacent score still resolves rather than crashing a page mid-render.
 */
export function scoreBand(score: number): ScoreBand {
  return SCORE_BANDS.find((b) => score >= b.floor) ?? SCORE_BANDS[SCORE_BANDS.length - 1];
}

/** Convenience for the common two call shapes. */
export const scoreBarTone = (score: number): string => scoreBand(score).bar;
export const scoreChipTone = (score: number): string => scoreBand(score).chip;
export const scoreInkTone = (score: number): string => scoreBand(score).ink;
