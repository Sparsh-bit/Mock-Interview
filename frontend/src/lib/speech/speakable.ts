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
/*
 * PANELIST NAMES, RESPELLED FOR THE EAR ONLY.
 *
 * REPORTED: "one of them is saying raya insted of riya". Correct — the vendor reads "Riya" with
 * a long English i, which is a different name. A panel that cannot say its own members' names
 * is the single most obviously wrong thing it can do, and it happens on the very first turn
 * where they greet each other.
 *
 * RESPELLED RATHER THAN PHONEME-TAGGED. Fish's markup for pronunciation is model-specific and
 * undocumented for these voices, and a tag the model does not understand gets READ OUT — which
 * is how "*(laughs)*" became a spoken word. A respelling is plain text: every engine, neural or
 * browser, pronounces "Reeya" the way "Riya" is meant to sound, and no engine can recite the
 * hint itself.
 *
 * SPOKEN FORM ONLY. `PanelThread` renders `line.text`, so the screen still says Riya. This
 * substitution exists between the written line and the vendor, which is the only place it is
 * correct — a transcript that said "Reeya" would be quoted back in a report.
 *
 * Word-boundary anchored and case-preserving on the first letter, so "Priya" cannot be matched
 * inside by the "Riya" rule — the longer names are listed first for the same reason. Only names
 * this product actually uses; a general transliteration table would be a large source of new
 * ways to be wrong.
 */
const NAME_SOUNDS: Array<[RegExp, string]> = [
  // Longest first: "Priya" contains "riya".
  [/\bPriya\b/g, 'Preeya'],
  [/\bRiya\b/g, 'Reeya'],
  /*
   * ANIL: "Aneel", NOT "Uh-neel". The hyphenated version was my first attempt and it made
   * things worse, which is the whole lesson here.
   *
   * Reported as the panel "not taking the names of Priya and Anil correct", and rendering the
   * spoken form showed why: "Thanks Uh-neel." A synthesiser reads "Uh" as a HESITATION FILLER
   * and a hyphen as a PAUSE, so it says "Thanks uh… neel" — a stammer in the middle of a
   * greeting, which is worse than the original mispronunciation because it sounds like the
   * speaker forgot the name.
   *
   * TWO RULES FOR EVERY RESPELLING IN THIS TABLE, learned from that:
   *   NO HYPHENS. They are read as pauses, not as syllable hints.
   *   NO SYLLABLE THAT IS ALSO AN ENGLISH FILLER — uh, um, er, ah, hmm. A respelling has to
   *   survive being read by something that knows nothing about why it is spelled that way.
   * A test asserts both, because the mistake is invisible in the table and only audible in the
   * room.
   *
   * "Aneel" is one word, has no filler syllable, and puts the stress where the name has it:
   * ah-NEEL rather than the AY-nil several engines default to.
   */
  [/\bAnil\b/g, 'Aneel'],
  /*
   * ARJUN AND MEERA WERE PASS-THROUGH, WHICH MEANT THEY WERE NEVER FIXED.
   *
   * They were listed with themselves as the replacement — "listed so the set is complete and
   * reviewable in one place" — which reads as deliberate and did nothing at all. Reported as
   * "in some places the AI agents are pronouncing the names of themselves wrong". A table entry
   * that is a no-op is worse than a missing one: it makes the name look considered.
   *
   * ARJUN is the one that is actually wrong. English readers put the stress on the first
   * syllable and rhyme the second with "June" — AR-june. The name is ar-JUN, with a short
   * vowel. "Arjoon" produces that on every engine tested.
   *
   * MEERA is usually right, and it gets an explicit respelling anyway because "Meera" is also
   * read as MEE-ruh with a swallowed final vowel. "Meerah" holds the vowel open without
   * changing the stress, which is the smaller of the two risks.
   *
   * Both are ear-only, like the rest of this table: the screen and the transcript keep the real
   * spelling, because a report that quotes "Arjoon" back at somebody is a worse bug than a
   * mispronounced name.
   */
  [/\bArjun\b/g, 'Arjoon'],
  [/\bMeera\b/g, 'Meerah'],
];

export function toSpokenForm(text: string): string {
  if (!text) return text;
  let out = text;

  /*
   * STAGE DIRECTIONS ARE PERFORMED, NOT PRONOUNCED.
   *
   * THE REPORT: "i cannot see the panaelist laugh and a sort of smile and all the gestures
   * that the normal human do in an interview". The panel was already laughing — rule 5 of
   * prompts/interview_panel.md instructs it to, and gives the exact format: "*(laughs)* No,
   * fair enough.", "*(both laugh)*". The model was obeying.
   *
   * Nothing translated the marker. So the vendor received the literal string `*(laughs)*` and
   * a panelist SAID THE WORD "laughs" — or read the asterisks as punctuation — where a human
   * would have laughed. That is worse than no laughter at all: it is uncanny, and it is why
   * the panel reads as a machine at exactly the moments meant to make it read as people.
   *
   * REMOVED RATHER THAN CONVERTED, deliberately. Fish's marker syntax is model-specific and
   * undocumented for the voices this product uses, so emitting a guess would risk the same
   * failure in a new costume — a voice reading out whatever token we invented. Removing it
   * leaves a real pause where the laugh was, which the surrounding words already carry
   * ("Ha — okay, that's one way to put it" is funny without an annotation), and it is
   * verifiable today whereas a marker cannot be tested without vendor credit.
   *
   * ONLY THE ASTERISK-WRAPPED FORM, plus a short allowlist of the bare forms the model
   * actually produces. An unrestricted `\(...\)` strip would silently delete real
   * parenthetical speech — "the JDK (which includes the compiler)" is content a candidate
   * needs to hear, not an aside.
   */
  // Names before anything else: the operator and spell rules below can split a word, and a
  // name that has been split is a name this cannot match any more.
  for (const [pattern, sound] of NAME_SOUNDS) out = out.replace(pattern, sound);

  out = out.replace(/\*\(([^)]{0,40})\)\*/g, ' ');
  out = out.replace(
    /\((?:both\s+)?(?:laughs?|laughing|chuckles?|chuckling|smiles?|smiling|grins?|sighs?|pauses?)\)/gi,
    ' ',
  );

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
