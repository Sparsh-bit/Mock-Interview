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
 * Canonical interview filler / hedge words. Kept to the words that are almost
 * always disfluencies in an interview context to limit false positives.
 * Multi-word entries are matched as phrases.
 */
export const FILLER_WORDS: string[] = [
  'um', 'umm', 'ummm', 'uh', 'uhh', 'uhhh', 'uhm', 'er', 'err', 'erm',
  'ah', 'ahh', 'hmm', 'hmmm', 'mmm', 'eh',
  'like', 'basically', 'actually', 'literally', 'seriously',
  'you know', 'i mean', 'kind of', 'sort of', 'you see',
];

const SINGLE_FILLERS = new Set(FILLER_WORDS.filter((w) => !w.includes(' ')));
const PHRASE_FILLERS = FILLER_WORDS.filter((w) => w.includes(' '));

function normalizeWord(w: string): string {
  return w.toLowerCase().replace(/[^a-z']/g, '');
}

export interface DeliveryToken {
  text: string;
  isFiller: boolean;
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

  // Pre-compute which word positions belong to a phrase filler.
  const words = raw.filter((t) => t.trim().length > 0).map(normalizeWord);
  const phraseFillerPositions = new Set<number>();
  for (const phrase of PHRASE_FILLERS) {
    const parts = phrase.split(' ');
    for (let i = 0; i + parts.length <= words.length; i++) {
      if (parts.every((p, k) => words[i + k] === p)) {
        for (let k = 0; k < parts.length; k++) phraseFillerPositions.add(i + k);
      }
    }
  }

  for (const piece of raw) {
    if (piece.trim().length === 0) {
      if (piece.length) tokens.push({ text: piece, isFiller: false, wordIndex: -1 });
      continue;
    }
    const norm = normalizeWord(piece);
    const isFiller = SINGLE_FILLERS.has(norm) || phraseFillerPositions.has(wordIndex);
    tokens.push({ text: piece, isFiller, wordIndex });
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
}

export function summarizeDelivery(opts: {
  text: string;
  seconds: number;
  pauses: PauseEvent[];
}): DeliverySummary {
  const { text, seconds, pauses } = opts;
  const fillers = countFillers(text);
  const pauseSecs = pauses.map((p) => p.seconds);
  return {
    words: wordCount(text),
    wpm: wordsPerMinute(text, seconds),
    fillerCount: fillers.total,
    fillerBreakdown: fillers.breakdown,
    pauseCount: pauses.length,
    longestPauseSec: pauseSecs.length ? Math.max(...pauseSecs) : 0,
    totalPauseSec: Math.round(pauseSecs.reduce((a, b) => a + b, 0)),
  };
}

/** A short human-readable pace verdict for the scorecard. */
export function paceVerdict(wpm: number): string {
  if (wpm === 0) return 'No speech detected';
  if (wpm < 100) return 'A little slow — try to keep momentum';
  if (wpm > 170) return 'Quite fast — slow down for clarity';
  return 'Good, natural pace';
}
