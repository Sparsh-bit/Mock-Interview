/**
 * Turning written technical text into something a voice can say — lib/speech/speakable.ts
 *
 * THIS CHANGES WHAT IS SPOKEN, NEVER WHAT IS SHOWN. The panel's line appears on screen
 * exactly as written; only the copy handed to the synthesiser goes through here. Two
 * reasons, and the second is the one that matters: "==" is correct on screen and wrong in
 * the ear, and a transcript that says "double equals" would then be quoted back at the
 * candidate in a follow-up and printed in their report as though somebody had typed it.
 *
 * WHAT IT FIXES.
 *
 * Reported from a real session: the panel read `==` as "equal equal" and `===` as "equal
 * equal equal", and said "oop" as a word rather than O-O-P. Both are the same class of
 * problem — a text-to-speech engine is trained on prose, and prose does not contain
 * operators or three-letter capitals that are meant to be spelled.
 *
 * ORDER IS LOAD-BEARING. The longest operators run first, or `===` is eaten by the `==`
 * rule and comes out as "double equals equals".
 */

/** Operators, longest first. */
const OPERATORS: [RegExp, string][] = [
  // Three characters before two, two before one. Getting this backwards is not a subtle
  // bug: `===` becomes "double equals equals", which is worse than the original.
  [/===/g, ' triple equals '],
  [/!==/g, ' strict not equals '],
  [/<=>/g, ' spaceship operator '],
  [/\+\+/g, ' plus plus '],
  [/--/g, ' minus minus '],
  [/==/g, ' double equals '],
  [/!=/g, ' not equals '],
  [/<=/g, ' less than or equal to '],
  [/>=/g, ' greater than or equal to '],
  [/&&/g, ' and '],
  [/\|\|/g, ' or '],
  [/=>/g, ' arrow '],
  [/->/g, ' arrow '],
  [/::/g, ' double colon '],
  [/\+=/g, ' plus equals '],
  [/-=/g, ' minus equals '],
  // Single `=` only where it is genuinely an operator — flanked by spaces. Left alone
  // inside a word or a URL, where it is not being read as a comparison anyway.
  [/\s=\s/g, ' equals '],
];

/**
 * Acronyms a synthesiser gets wrong, and how to force the letters out.
 *
 * DELIBERATELY SHORT. Most engines spell all-caps tokens correctly on their own, and
 * over-riding one that already worked makes it worse — "API" spelled as "A.P.I." can come
 * out with odd pauses. These are the ones that actually break, because they are short
 * enough to be mistaken for words:
 *
 *   OOP   read as "oop", which is what was reported
 *   JVM / JDK / JRE / JPA / ORM / IoC   short enough to be attempted as syllables
 *   DBMS / JDBC / CRUD / LIFO / FIFO    likewise
 *
 * Not included: SQL (both "sequel" and "S-Q-L" are how engineers say it, and forcing one is
 * a change nobody asked for), JSON ("jay-son" is correct and universal), HTTP and URL and
 * IDE and API (spelled correctly by every engine tested).
 *
 * Periods rather than spaces: a space-separated "O O P" is read as three separate words
 * with word-length pauses, while "O.O.P" is read as an initialism, which is the thing it is.
 */
const SPELL_OUT = [
  'OOP',
  'OOPS',
  'JVM',
  'JDK',
  'JRE',
  'JPA',
  'JDBC',
  'DBMS',
  'CRUD',
  'LIFO',
  'FIFO',
  'ORM',
  'IoC',
  'JIT',
  'GC',
  'DTO',
  'DAO',
  'MVC',
  'CDN',
];

const SPELL_RULES: [RegExp, string][] = SPELL_OUT.map((a) => [
  // Word-boundary anchored and case-SENSITIVE on the letters, so the word "gc" inside an
  // identifier is not touched. "OOPs"/"OOPS" are both how candidates write it.
  new RegExp(`\\b${a}\\b`, 'g'),
  a.toUpperCase().split('').join('.'),
]);

/**
 * The text with symbols and initialisms turned into words.
 *
 * Idempotent in the way that matters: running it twice does not double-expand, because the
 * output of each rule no longer matches its own pattern.
 */
export function toSpokenForm(text: string): string {
  if (!text) return text;
  let out = text;

  // Code fences and inline backticks are read out as "backtick backtick backtick java",
  // which is nonsense in the ear. The candidate can see the code; the voice should talk
  // about it rather than recite its punctuation.
  out = out.replace(/```[a-z]*\n?/gi, ' ').replace(/`/g, '');

  for (const [pattern, replacement] of OPERATORS) out = out.replace(pattern, replacement);
  for (const [pattern, replacement] of SPELL_RULES) out = out.replace(pattern, replacement);

  // Collapse the whitespace the operator rules introduced, and tidy the space they leave
  // before punctuation.
  return out.replace(/\s{2,}/g, ' ').replace(/\s+([,.!?;:])/g, '$1').trim();
}
