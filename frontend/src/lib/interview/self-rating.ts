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

/**
 * Ratings given as a WORD rather than a number, which is most of them.
 *
 * Adding this is a deliberate softening of the "never guess" rule at the top of this file,
 * and it is worth being precise about why, because the rule is still right.
 *
 * The rule exists to stop the parser inventing a number out of a sentence that does not
 * contain one — reading "I have 2 years of experience" as a 2. That is a guess: nothing in
 * the sentence is a self-assessment. "I'd say I'm average" is not that. It IS a
 * self-assessment, said plainly; it simply is not arithmetic. Returning null there does not
 * avoid a wrong answer, it just throws away a right one and puts a slider on screen — which
 * is the seam this whole feature exists to remove, and it was the reported complaint.
 *
 * So: only words that are unambiguously a level, mapped to the middle of the band they name.
 * Anything hedged, directional or vague ("not great", "depends", "okay-ish at some things")
 * still returns null and still gets the slider, because those genuinely are guesses.
 *
 * FIRST MATCH WINS, SO THE ORDER IS THE SPECIFICITY ORDER. Every qualified phrase must be
 * tested before the bare word it contains: "very good" before "good", "below average" before
 * "average", "very basic" before "basic". Get that backwards and the qualifier is silently
 * dropped — an 8 recorded as a 7, a 3 recorded as a 5 — which is precisely the class of quiet
 * wrongness this file refuses to produce.
 */
const LEVEL_WORDS: Array<[RegExp, number]> = [
  [/\bexpert\b|\bexcellent\b|\bmaster(?:ed)?\b|\bvery strong\b/, 9],
  [/\bvery good\b|\bvery confident\b|\badvanced\b|\bstrong\b/, 8],
  [/\babove average\b|\bfairly (?:good|confident)\b|\bpretty good\b/, 7],
  [/\bcomfortable\b|\bconfident\b|\bgood\b|\bsolid\b/, 7],
  [/\bbelow average\b|\bweak\b|\bpoor\b/, 3],
  [/\baverage\b|\bmoderate\b|\bmedium\b|\bdecent\b|\bintermediate\b|\bokay\b|\bfair\b/, 5],
  [/\bvery basic\b|\b(?:complete(?:ly)? )?beginner\b|\bjust start(?:ed|ing)\b/, 2],
  [/\bbasic(?:s|ally)?\b|\bnovice\b|\belementary\b/, 3],
];

/**
 * Negation, which inverts a level word and must therefore veto it.
 *
 * "not very good" contains "very good" and would otherwise be recorded as an 8 — the single
 * worst output this function can produce, since it is both wrong and confidently high. There
 * is no reliable way to read a NUMBER out of a negated self-assessment ("not great" is
 * somewhere below average and no more precise than that), so a negated answer falls back to
 * null and the candidate taps a button. That is the honest failure the header describes.
 *
 * Only applied to the word path. A negation alongside an explicit number — "I'm not being
 * modest, I'd say 8" — is not a negated rating, and the number said out loud is the answer.
 */
const NEGATED = /\bnot\b|\bn't\b|\bhardly\b|\bbarely\b|\bnothing\b|\bno\s+(?:idea|clue)\b/;

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

  /*
   * SPOKEN DECIMALS, COLLAPSED TO ONE TOKEN BEFORE ANYTHING COUNTS NUMBERS.
   *
   * "seven point five" is three tokens, two of which are numbers, and the last-number-wins
   * rule below therefore read it as a FIVE — a candidate who rated themselves 7.5 was filed
   * as halfway down the scale. Same shape of bug as the "out of ten" trap this function
   * already guards: a rating phrase that contains a second number the reader mistakes for
   * the answer.
   *
   * Done as a rewrite rather than another special case in the matcher so that everything
   * downstream — the scale pattern, the range rule, the 1-10 bound — sees a single ordinary
   * number and needs to know nothing about how it was said. "and a half" is the same claim
   * in different words and collapses the same way.
   */
  const joinDecimal = (s: string): string =>
    s
      .replace(
        new RegExp(String.raw`\b(${NUM})\s+point\s+(\d|one|two|three|four|five|six|seven|eight|nine)\b`, 'g'),
        (_m, whole: string, frac: string) => ` ${WORDS[whole] ?? whole}.${WORDS[frac] ?? frac} `,
      )
      .replace(
        new RegExp(String.raw`\b(${NUM})\s+and\s+a\s+half\b`, 'g'),
        (_m, whole: string) => ` ${(WORDS[whole] ?? Number(whole)) + 0.5} `,
      );

  /*
   * "ON TEN" IS THE SAME PHRASE AS "OUT OF TEN", AND MISSING IT WAS RECORDING A 10.
   *
   * "seven on ten" is how a very large share of this product's users say this — it is
   * standard Indian English for the construction, more common in speech here than "out of".
   * It was not in this pattern, so the denominator survived into the sentence and the
   * last-number-wins pass below read the "ten". Every candidate who phrased it that way was
   * silently filed as a 10/10, which then raised the difficulty of every question they were
   * asked and the bar their report judged them against.
   *
   * That is the exact failure the header of this file says must never happen, and it was
   * reachable through the single most likely phrasing. `upon` is included for the same
   * reason — it is a common spoken variant — and both are anchored to a 10/ten denominator,
   * so an ordinary "on" ("I worked on 3 projects") cannot trigger it.
   */
  const scale = new RegExp(String.raw`(${NUM})\s*(?:out\s*of|\/|upon|on)\s*(?:10|ten)`);
  const spoken = joinDecimal(text);
  const explicit = spoken.match(scale);
  const searchable = explicit ? spoken.replace(scale, ` ${explicit[1]} `) : spoken;

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
    /*
     * Anything left, digits or words, LAST one wins — people correct themselves forwards
     * ("six, no, seven") and answer in ranges ("maybe 6 or 7", where the top is the claim).
     * Bounded to 1-10 so "I have 2 years of experience" is not read as a rating.
     *
     * THE TRAILING BOUNDARY IS ASYMMETRIC, AND IT HAS TO BE. A closing `\b` after a digit
     * fails on "8ish" — 8 and i are both word characters, so there is no boundary between
     * them and the number was not found at all. "eight-ish" said out loud is transcribed
     * that way often enough to matter. Digits therefore end on "not another digit or a
     * decimal point" instead, which admits the suffix.
     *
     * Word numbers keep the real `\b`, because relaxing theirs reads "ten" out of "tenant"
     * and "one" out of "money" — the suffix that helps a digit is the prefix of a wrong
     * answer for a word.
     */
    const anyNumber = new RegExp(
      String.raw`\b(?:(\d{1,2}(?:\.\d+)?)(?![\d.])|(one|two|three|four|five|six|seven|eight|nine|ten)\b)`,
      'g',
    );
    const all = [...searchable.matchAll(anyNumber)]
      .map((m) => asNumber(m[1] ?? m[2]))
      .filter((n): n is number => n !== null && n >= 1 && n <= 10);
    if (all.length) rating = all[all.length - 1];
  }

  /*
   * NO NUMBER ANYWHERE — TRY THE WORD THEY USED INSTEAD.
   *
   * Reached when the candidate answered the question without arithmetic: "average",
   * "I'm comfortable with the basics", "intermediate". Those are answers, and the previous
   * behaviour of returning null on all of them is what put a slider in front of somebody who
   * had just said their level out loud.
   *
   * Negation vetoes the whole path rather than inverting it — see NEGATED. And this runs
   * LAST on purpose: a spoken number always beats a spoken adjective, so "I'm average but
   * I'd say 7" is a 7, not a 5.
   */
  if (rating === null && !NEGATED.test(text)) {
    for (const [pattern, level] of LEVEL_WORDS) {
      if (pattern.test(text)) {
        rating = level;
        break;
      }
    }
  }

  if (rating === null || rating < 1 || rating > 10) return null;

  const strengths = TOPIC_HINTS.filter((t) => text.includes(t))
    // Deduplicate the overlapping hints so "spring boot" does not also record "spring".
    .filter((t, _i, all) => !all.some((other) => other !== t && other.includes(t)))
    .slice(0, 8);

  return { rating, strengths };
}
