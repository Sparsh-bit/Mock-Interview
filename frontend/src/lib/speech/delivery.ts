/**
 * Speech-delivery analysis — lib/speech/delivery.ts
 *
 * Shared, framework-agnostic helpers for analysing how a candidate *delivered*
 * a spoken answer: filler words ("uh", "um", "you know"…) and pauses. Used
 * across the interview, communication and group-discussion rounds so the
 * transcript can highlight fillers in red and mark pauses, and the scorecards
 * can report delivery metrics.
 *
 * Note on limitations: the browser Web Speech API often silently drops pure
 * disfluencies like "uh"/"um", so pause detection (timing-based, captured in
 * the speech hook) is the more reliable disfluency signal — the two are
 * complementary.
 */

/** A detected silence while the candidate was recording. */
export interface PauseEvent {
  /** Word index in the finalized transcript that this pause precedes. */
  wordIndex: number;
  /** Length of the silence, in seconds. */
  seconds: number;
}

/**
 * Canonical interview filler / hedge words. Multi-word entries match as phrases.
 *
 * WHY "uh" AND "um" ALMOST NEVER GET MARKED, even though they are listed first.
 * Chrome's recogniser treats pure disfluencies as non-speech and strips them
 * before we ever see the text, so the transcript genuinely does not contain them.
 * They stay in the list because Safari and some Android builds DO emit them, and
 * a word we cannot detect costs nothing to keep.
 *
 * That is why the list below is long. The fillers a browser actually transcribes
 * are the WORD-shaped ones — "like", "basically", "so", "right", "I guess" — so
 * those are what this can catch, and the more of them it knows the closer the
 * count gets to what a human interviewer would notice. Hesitation that never
 * reaches the transcript is caught by pause detection instead, which is
 * timing-based and unaffected by the recogniser.
 *
 * Every addition here is a word that is a filler in an interview and rarely
 * anything else. Deliberately NOT included: "well" (a legitimate sentence
 * opener), "right" as a question tag versus "right?" — we cannot tell them apart
 * without punctuation, and marking a correct answer as filler is worse than
 * missing one.
 */
export const FILLER_WORDS: string[] = [
  // Vocalised pauses. Mostly stripped by Chrome; kept for other engines.
  'um', 'umm', 'ummm', 'uh', 'uhh', 'uhhh', 'uhm', 'er', 'err', 'erm',
  'ah', 'ahh', 'hmm', 'hmmm', 'mmm', 'eh', 'uhhuh', 'mhm',
  // Discourse fillers the recogniser DOES transcribe — the ones that actually
  // show up in a candidate's answer.
  'like', 'basically', 'actually', 'literally', 'seriously', 'obviously',
  'honestly', 'anyway', 'anyways', 'okay', 'ok', 'yeah', 'yep', 'nope',
  // Hedges. These are the ones that make an answer sound uncertain, which is
  // what a real interviewer is listening for.
  'maybe', 'probably', 'somewhat', 'somehow', 'whatever',
  // Multi-word hedges and verbal tics.
  'you know', 'i mean', 'kind of', 'sort of', 'you see', 'i guess',
  'i think so', 'something like that', 'stuff like that', 'and all that',
  'or something', 'and so on', 'so on', 'and stuff', 'like that',
  'more or less', 'to be honest', 'at the end of the day',
];

/**
 * Language that would end a real interview.
 *
 * Counted separately from fillers, not lumped in with them, because they are not
 * the same mistake: a filler is a habit worth trimming, this is a single event
 * that loses the offer. It gets its own count so the report can say so once,
 * plainly, rather than burying it in a filler tally.
 *
 * Masked spellings are included because Chrome's recogniser censors profanity by
 * default and returns forms like "f***" — so the obvious check for the plain word
 * misses the very case this exists to catch.
 *
 * Kept to unambiguous terms. Words that are profanity in one sense and ordinary
 * in another are excluded: flagging "hell" in "what the hell does this do" is a
 * false positive on a candidate thinking aloud about code.
 */
export const UNPROFESSIONAL_WORDS: string[] = [
  'fuck', 'fucking', 'fucked', 'fuckin', 'f***', 'f**k', 'fk',
  'shit', 'shitty', 's***', 'bullshit',
  'bitch', 'bastard', 'asshole', 'arsehole', 'dickhead',
  'crap', 'damn', 'goddamn', 'bloody hell',
  'wtf', 'stfu',
];

const SINGLE_FILLERS = new Set(FILLER_WORDS.filter((w) => !w.includes(' ')));
const PHRASE_FILLERS = FILLER_WORDS.filter((w) => w.includes(' '));
const SINGLE_UNPROFESSIONAL = new Set(UNPROFESSIONAL_WORDS.filter((w) => !w.includes(' ')));
const PHRASE_UNPROFESSIONAL = UNPROFESSIONAL_WORDS.filter((w) => w.includes(' '));

function normalizeWord(w: string): string {
  return w.toLowerCase().replace(/[^a-z']/g, '');
}

/**
 * Like normalizeWord but keeps asterisks, so a censored "f***" survives.
 *
 * normalizeWord strips every non-letter, which turns "f***" into "f" — and "f"
 * matches nothing, so every censored word slipped through the check that exists
 * precisely to catch them.
 */
function normalizeMasked(w: string): string {
  return w.toLowerCase().replace(/[^a-z'*]/g, '');
}

export interface DeliveryToken {
  text: string;
  isFiller: boolean;
  /** Language that would end a real interview. Marked separately from fillers. */
  isUnprofessional: boolean;
  /** Word index (only meaningful for word tokens, not whitespace). */
  wordIndex: number;
}

/**
 * Split a transcript into tokens, marking which ones are filler words. Phrase
 * fillers ("you know") mark each of their constituent words. Whitespace is
 * preserved as its own tokens so the caller can render the text faithfully.
 */
export function tokenizeWithFillers(text: string): DeliveryToken[] {
  const raw = text.split(/(\s+)/); // keep the separators
  const tokens: DeliveryToken[] = [];
  let wordIndex = 0;

  // Pre-compute which word positions belong to a phrase.
  const words = raw.filter((t) => t.trim().length > 0).map(normalizeWord);
  const maskedWords = raw.filter((t) => t.trim().length > 0).map(normalizeMasked);

  const markPhrases = (phrases: string[], source: string[]) => {
    const hits = new Set<number>();
    for (const phrase of phrases) {
      const parts = phrase.split(' ');
      for (let i = 0; i + parts.length <= source.length; i++) {
        if (parts.every((pt, k) => source[i + k] === pt)) {
          for (let k = 0; k < parts.length; k++) hits.add(i + k);
        }
      }
    }
    return hits;
  };
  const phraseFillerPositions = markPhrases(PHRASE_FILLERS, words);
  const phraseUnprofessionalPositions = markPhrases(PHRASE_UNPROFESSIONAL, maskedWords);

  for (const piece of raw) {
    if (piece.trim().length === 0) {
      if (piece.length) {
        tokens.push({ text: piece, isFiller: false, isUnprofessional: false, wordIndex: -1 });
      }
      continue;
    }
    const norm = normalizeWord(piece);
    const masked = normalizeMasked(piece);
    const isUnprofessional =
      SINGLE_UNPROFESSIONAL.has(masked) || phraseUnprofessionalPositions.has(wordIndex);
    // Profanity wins. A word cannot be both, and reporting "fuck" as a filler
    // would bury the one thing in the transcript that actually costs an offer.
    const isFiller =
      !isUnprofessional && (SINGLE_FILLERS.has(norm) || phraseFillerPositions.has(wordIndex));
    tokens.push({ text: piece, isFiller, isUnprofessional, wordIndex });
    wordIndex += 1;
  }
  return tokens;
}

/** Count filler words and give a per-word breakdown. */
export function countFillers(text: string): { total: number; breakdown: Record<string, number> } {
  const breakdown: Record<string, number> = {};
  let total = 0;
  for (const tok of tokenizeWithFillers(text)) {
    if (tok.isFiller) {
      total += 1;
      const key = normalizeWord(tok.text);
      breakdown[key] = (breakdown[key] ?? 0) + 1;
    }
  }
  return { total, breakdown };
}

/**
 * Count unprofessional language, with the words found.
 *
 * Separate from countFillers because the advice is different: fillers are a habit
 * to trim, this is one event to never repeat.
 */
export function countUnprofessional(text: string): {
  total: number;
  words: string[];
} {
  const found: string[] = [];
  for (const tok of tokenizeWithFillers(text)) {
    if (tok.isUnprofessional) found.push(normalizeMasked(tok.text));
  }
  return { total: found.length, words: [...new Set(found)] };
}

export function wordCount(text: string): number {
  return text.trim() ? text.trim().split(/\s+/).length : 0;
}

export function wordsPerMinute(text: string, seconds: number): number {
  if (seconds <= 0) return 0;
  return Math.round((wordCount(text) / seconds) * 60);
}

export interface DeliverySummary {
  words: number;
  wpm: number;
  fillerCount: number;
  fillerBreakdown: Record<string, number>;
  pauseCount: number;
  longestPauseSec: number;
  totalPauseSec: number;
  /** Unprofessional language. Non-zero is a single, serious note in the report. */
  unprofessionalCount: number;
  unprofessionalWords: string[];
}

export function summarizeDelivery(opts: {
  text: string;
  seconds: number;
  pauses: PauseEvent[];
}): DeliverySummary {
  const { text, seconds, pauses } = opts;
  const fillers = countFillers(text);
  const unprofessional = countUnprofessional(text);
  const pauseSecs = pauses.map((p) => p.seconds);
  return {
    words: wordCount(text),
    wpm: wordsPerMinute(text, seconds),
    fillerCount: fillers.total,
    fillerBreakdown: fillers.breakdown,
    pauseCount: pauses.length,
    longestPauseSec: pauseSecs.length ? Math.max(...pauseSecs) : 0,
    totalPauseSec: Math.round(pauseSecs.reduce((a, b) => a + b, 0)),
    unprofessionalCount: unprofessional.total,
    unprofessionalWords: unprofessional.words,
  };
}

/** A short human-readable pace verdict for the scorecard. */
export function paceVerdict(wpm: number): string {
  if (wpm === 0) return 'No speech detected';
  if (wpm < 100) return 'A little slow — try to keep momentum';
  if (wpm > 170) return 'Quite fast — slow down for clarity';
  return 'Good, natural pace';
}
