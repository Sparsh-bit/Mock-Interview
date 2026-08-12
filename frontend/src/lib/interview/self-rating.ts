/**
 * Reading a self-rating out of speech — lib/interview/self-rating.ts
 *
 * The panel asks "out of ten, how would you rate yourself in Java?" and the candidate SAYS
 * the answer. So the number arrives as a transcript, not as a slider, and it arrives in
 * whatever shape a nervous student says it in:
 *
 *     "seven"                        "I'd say around 7 out of 10"
 *     "maybe 6 or 7"                 "7.5"
 *     "I'm decent, maybe eight"      "sir, 6 out of 10, mostly collections and OOP"
 *
 * WHY NOT JUST SHOW A SLIDER. Because the whole redesign is about the room, and a form
 * control appearing mid-conversation to collect an answer somebody just said out loud is
 * exactly the seam this product is trying to remove. The slider still exists as the fallback
 * — see the session page — for when this cannot find a number, which is the honest failure
 * rather than guessing at one.
 *
 * FAILING MEANS RETURNING null, never a guess. A wrong rating is worse than no rating: it
 * silently changes which questions the candidate is asked and what their report judges them
 * against, and it does so invisibly. When in doubt, ask.
 */

/** Words for numbers, because people say "seven" more often than they say "7". */
const WORDS: Record<string, number> = {
  one: 1,
  two: 2,
  three: 3,
  four: 4,
  five: 5,
  six: 6,
  seven: 7,
  eight: 8,
  nine: 9,
  ten: 10,
};

export interface SelfRating {
  /** 1-10. */
  rating: number;
  /** Topics they named, in their own words, lightly cleaned. */
  strengths: string[];
}

/**
 * Topic words worth steering on, matched loosely.
 *
 * Loosely on purpose: "collections", "collection framework" and "java collections" are one
 * claim, and the orchestrator only uses these as keyword-overlap hints for ranking, never as
 * an exact match against a topic name. A near miss costs a slightly worse-ranked question;
 * demanding precision from a spoken sentence would cost the feature entirely.
 */
const TOPIC_HINTS = [
  'oop',
  'object oriented',
  'collections',
  'collection',
  'string',
  'exception',
  'multithreading',
  'thread',
  'concurrency',
  'jvm',
  'memory',
  'lambda',
  'stream',
  'java 8',
  'spring',
  'spring boot',
  'hibernate',
  'jpa',
  'jdbc',
  'sql',
  'rest',
  'api',
  'dsa',
  'data structure',
  'algorithm',
  'design pattern',
  'solid',
];

export function parseSelfRating(transcript: string): SelfRating | null {
  const text = (transcript || '').toLowerCase().trim();
  if (!text) return null;

  let rating: number | null = null;

  /*
   * "OUT OF TEN" IS STRIPPED BEFORE ANYTHING ELSE IS READ, and this is not a tidying step.
   *
   * "seven out of ten" parsed as 10 until it was: the digit pattern found nothing, so the
   * word pass ran, and the word pass takes the LAST number word — which is the "ten" in the
   * denominator, not the "seven" the candidate said. Every scale phrase has that trap in it,
   * and the only robust answer is to remove the denominator from the sentence before looking
   * for a rating at all.
   *
   * The scale is also matched on WORDS as well as digits for the same reason: people say the
   * whole thing out loud, and the explicit form is the one you least want to misread.
   */
  const NUM = String.raw`\d{1,2}(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten`;
  const scale = new RegExp(String.raw`(${NUM})\s*(?:out\s*of|\/)\s*(?:10|ten)`);
  const explicit = text.match(scale);
  const searchable = explicit ? text.replace(scale, ` ${explicit[1]} `) : text;

  const asNumber = (raw: string): number | null => {
    const word = WORDS[raw];
    if (word !== undefined) return word;
    const n = Number(raw);
    // Rounded, not truncated. "7.5" is an eight to the person who said it, and taking the
    // integer part would quietly round every half-claim down.
    return Number.isFinite(n) ? Math.round(n) : null;
  };

  if (explicit) rating = asNumber(explicit[1]);

  if (rating === null) {
    // Anything left, digits or words, LAST one wins — people correct themselves forwards
    // ("six, no, seven") and answer in ranges ("maybe 6 or 7", where the top is the claim).
    // Bounded to 1-10 so "I have 2 years of experience" is not read as a rating.
    const all = [...searchable.matchAll(new RegExp(String.raw`\b(${NUM})\b`, 'g'))]
      .map((m) => asNumber(m[1]))
      .filter((n): n is number => n !== null && n >= 1 && n <= 10);
    if (all.length) rating = all[all.length - 1];
  }

  if (rating === null || rating < 1 || rating > 10) return null;

  const strengths = TOPIC_HINTS.filter((t) => text.includes(t))
    // Deduplicate the overlapping hints so "spring boot" does not also record "spring".
    .filter((t, _i, all) => !all.some((other) => other !== t && other.includes(t)))
    .slice(0, 8);

  return { rating, strengths };
}
