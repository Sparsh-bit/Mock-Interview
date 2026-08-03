/**
 * Clause segmentation for spoken delivery — lib/speech/prosody.ts
 *
 * THE PROBLEM. speechSynthesis gives no SSML and no phoneme control. Utterance
 * boundaries and the silence between them are therefore the ONLY pause control
 * that exists, and a trailing comma is the only intonation control: an utterance
 * ending in a comma is read with a continuing contour, one ending bare gets the
 * falling contour of a full stop. Both facts are load-bearing below.
 *
 * Before this, a whole contribution was handed to the engine as one utterance, so
 * there was no pause anywhere inside it — which is most of why the panel read as
 * text-to-speech rather than people. A real speaker breathes between sentences and
 * holds a beat where they pivot.
 *
 * SEPARATE FROM `toSpeechChunks` (hooks/useSpeech.ts) ON PURPOSE. That function
 * merges any chunk under 12 characters into its neighbour to avoid choppiness,
 * which is right for reading a written question aloud and exactly wrong here:
 * "Hold on" standing alone as its own utterance IS the effect we want. Its exact
 * output is also pinned by useSpeech.voice.test.ts, so it stays as it is.
 */

/**
 * Rate shaping for one chunk, relative to the speaker's own tempo.
 *
 * 'urgent'   — a short pivot ("Hold on", "Right, but", "Wait"), clipped and fast.
 *              That is how you take a floor that is not yours.
 * 'weighted' — ONLY the chunk immediately after an urgent one: the clause the
 *              interjection bought, delivered below the speaker's baseline. The
 *              contrast is the emphasis, and rate contrast is the only emphasis
 *              speechSynthesis can express without SSML.
 */
export type Emphasis = 'urgent' | 'weighted' | null;

export interface ProsodyChunk {
  /** Text for one utterance, with any continuation comma already appended. */
  text: string;
  /** Silence to hold after this utterance, ms. */
  pauseAfterMs: number;
  isQuestion: boolean;
  /** Last chunk of the contribution. */
  isFinal: boolean;
  emphasis: Emphasis;
}

const SENTENCE_SPLIT = /(?<=[.!?])\s+/;

/**
 * Mid-sentence breaks a person genuinely pauses at.
 *
 * Deliberately narrow. Commas are handled acceptably by every engine and
 * splitting on them is what turns speech staccato. A spaced hyphen is excluded
 * because it collides with number ranges ("10 - 15 percent").
 */
const CLAUSE_SPLIT = /(\s*[—–]\s*|\s*\.\.\.\s*|\s*…\s*|\s*[:;]\s+)/;

/** A person pivots mid-sentence once, occasionally twice. Never five times. */
const MAX_PARTS_PER_SENTENCE = 3;

const SENTENCE_PAUSE_MS = 320; //: spontaneous inter-sentence pauses run 300-500ms
const DASH_PAUSE_MS = 200; //: a dash is a snap-off, shorter than a full stop
const TRAIL_OFF_PAUSE_MS = 420; //: "the thing is…" — the pause IS the ellipsis
const COLON_PAUSE_MS = 260;
const MID_QUESTION_PAUSE_MS = 440;
const FINAL_QUESTION_PAUSE_MS = 700; //: you wait for the answer

/**
 * Openers that mark an actual PIVOT — a speaker turning against what was just
 * said. Deliberately narrower than the full verbal-gesture list in gd_panel.md.
 *
 * That prompt instructs the model to open roughly one turn in three with a verbal
 * gesture: "Hmm,", "See,", "Okay so,", "Actually,". Matching all of those would
 * tag and re-time a third of every contribution — and because CLAUSE_SPLIT does
 * not split on commas, "See, the thing is that juniors lose the mentoring nobody
 * costs in." is one 60-character chunk, so it would be a WHOLE SENTENCE delivered
 * slow for no reason but its first word. That is not emphasis, it is a mannerism,
 * and a mannerism on a third of the output becomes the character. "Hmm", "see",
 * "look", "okay so", "honestly" and bare "right"/"true" are therefore out: they
 * are throat-clearing, not pivots.
 */
const CONTRAST_OPENER =
  /^(but|though|however|actually|hold on|wait|no but|true, though|right, but|the thing is)\b/i;

/** Above this length an opener is an argument, not an interjection. */
const URGENT_MAX_CHARS = 24;

function pauseForSeparator(sep: string): number {
  if (/…|\.\.\./.test(sep)) return TRAIL_OFF_PAUSE_MS;
  if (/[—–]/.test(sep)) return DASH_PAUSE_MS;
  return COLON_PAUSE_MS;
}

interface SentencePart {
  text: string;
  pauseAfterMs: number;
  /** Was this clause cut off by an em dash? Changes the continuation rule. */
  dash: boolean;
}

function splitSentence(sentence: string): SentencePart[] {
  // The capturing group means split() returns [body, sep, body, sep, …].
  const pieces = sentence.split(CLAUSE_SPLIT);
  const parts: SentencePart[] = [];
  for (let i = 0; i < pieces.length; i += 2) {
    const body = (pieces[i] ?? '').trim();
    const sep = pieces[i + 1] ?? '';
    // A leading separator yields an empty body; skipping it also drops a pause
    // with nothing in front of it, which is what we want.
    if (!/[a-z0-9]/i.test(body)) continue;
    parts.push({
      text: body,
      pauseAfterMs: sep ? pauseForSeparator(sep) : 0,
      dash: /[—–]/.test(sep),
    });
  }
  if (parts.length <= MAX_PARTS_PER_SENTENCE) return parts;
  // Merge the overflow into the last kept part. The intervening separators are
  // lost, which is why the cap is 3 rather than 2 — rare enough to accept.
  const head = parts.slice(0, MAX_PARTS_PER_SENTENCE - 1);
  const tail = parts.slice(MAX_PARTS_PER_SENTENCE - 1);
  const lastTail = tail[tail.length - 1];
  head.push({
    text: tail.map((t) => t.text).join(' '),
    pauseAfterMs: lastTail.pauseAfterMs,
    dash: lastTail.dash,
  });
  return head;
}

export interface ProsodyOptions {
  /**
   * The chosen voice is cloud-backed (Edge "Online (Natural)", Chrome "Google ").
   *
   * These fetch audio PER UTTERANCE, so every extra utterance is an extra network
   * round trip inserted mid-sentence. Clause splitting would therefore double the
   * number of gaps we do NOT control while shortening the ones we do — on a slow
   * connection a three-clause sentence gains two unpredictable ~1s holes and the
   * panelist sounds like they are buffering rather than thinking. This matters
   * specifically here: the audience is students in India, often on mobile data,
   * and `scoreVoice` deliberately ranks exactly these voices first.
   *
   * So on network voices we split at SENTENCE boundaries only and hold no explicit
   * pause at all: the engine's own fetch gap is the beat. Local synthesis has no
   * fetch, so it gets the full clause table, which is exact.
   */
  networkVoice?: boolean;
  /**
   * Silence after the last chunk when it is not a question.
   *
   * The GD panel passes 0 because the next speaker's lead-in owns that gap; the
   * 1-on-1 interviewer has no next speaker, so it passes ~250. Explicit rather
   * than implied, because getting it wrong is silent — contributions just butt
   * together again with no sign that anything is off.
   */
  finalPauseMs?: number;
}

/** Split a contribution into utterances, with the silence to hold after each. */
export function toProsodyChunks(text: string, opts: ProsodyOptions = {}): ProsodyChunk[] {
  const clean = text.replace(/\s+/g, ' ').trim();
  if (!clean) return [];
  const network = opts.networkVoice === true;
  const finalPause = opts.finalPauseMs ?? 0;

  const sentences = clean.split(SENTENCE_SPLIT).filter((s) => /[a-z0-9]/i.test(s));
  const out: ProsodyChunk[] = [];

  sentences.forEach((sentence, si) => {
    const lastSentence = si === sentences.length - 1;
    const parts = network
      ? [{ text: sentence.trim(), pauseAfterMs: 0, dash: false }]
      : splitSentence(sentence);

    parts.forEach((part, pi) => {
      const lastPart = pi === parts.length - 1;
      const isFinal = lastSentence && lastPart;
      const isQuestion = /\?$/.test(part.text);

      // THE COMMA TRICK, narrowed. A clause broken off mid-sentence gets a comma
      // appended so the engine reads it as continuing; without it, splitting one
      // thought produces a list of flat statements, which is worse than not
      // splitting. But it is WRONG after an em dash: the dash in this prompt is
      // always a snap-off ("Hold on—", "Wait—", "True, though—") and a comma both
      // drawls the clause out and makes the engine insert its own 150-250ms on
      // top of DASH_PAUSE_MS, turning a 200ms clip into a 400ms sag. Bare and
      // clipped is what an interruption actually sounds like.
      const needsContinuation = !lastPart && !part.dash && !/[,.!?;:]$/.test(part.text);
      const spoken = needsContinuation ? `${part.text},` : part.text;

      // A question's pause survives on network voices; a plain sentence gap does
      // not. The two are doing different jobs: the sentence gap only stands in for
      // a breath, and a cloud voice's fetch already supplies one, but the pause
      // after a question is a deliberate "the floor is yours" cue that nothing else
      // provides. Zeroing that too would mean the panel asks the candidate
      // something and immediately carries on.
      const pauseAfterMs = isFinal
        ? isQuestion
          ? FINAL_QUESTION_PAUSE_MS
          : finalPause
        : isQuestion
          ? MID_QUESTION_PAUSE_MS
          : network
            ? 0
            : lastPart
              ? SENTENCE_PAUSE_MS
              : part.pauseAfterMs;

      // 'weighted' is only ever the chunk directly after an 'urgent' one. A long
      // opener gets nothing — see the note on CONTRAST_OPENER for why tagging it
      // would slow a whole sentence because of its first word.
      const opensPivot = CONTRAST_OPENER.test(part.text);
      const emphasis: Emphasis =
        opensPivot && part.text.length <= URGENT_MAX_CHARS
          ? 'urgent'
          : out[out.length - 1]?.emphasis === 'urgent'
            ? 'weighted'
            : null;

      out.push({
        text: spoken,
        pauseAfterMs: Math.round(pauseAfterMs),
        isQuestion,
        isFinal,
        emphasis,
      });
    });
  });

  return out;
}

/**
 * Rate multiplier for a chunk, given its emphasis and position.
 *
 * Kept here rather than inline in the hook so the compounding is testable. Every
 * slow factor stacks on the same panelist: local synthesis 0.94 × the
 * synthesiser's 0.92 tempo × a question's 0.94 × weighted 0.94 is 0.76, and a
 * neural Indian voice at 0.76 does not sound considered — it sounds like it is
 * buffering, which is the exact impression voice-ranking.ts was rewritten to
 * escape. So the SHAPING is floored at 0.90 before it ever reaches the rate.
 */
export function shapingFor(chunk: Pick<ProsodyChunk, 'isQuestion' | 'isFinal' | 'emphasis'>): number {
  // A speaker slows on the clause they are ending on; that lengthening is the cue
  // that the floor is free, which is the one thing a candidate has to learn to
  // hear. A question goes further, because it is being handed to a named person.
  // 6% is at the edge of consciously noticeable and reads as deliberate; 15% reads
  // as the engine struggling.
  const position = chunk.isQuestion ? 0.94 : chunk.isFinal ? 0.97 : 1;
  const weight = chunk.emphasis === 'urgent' ? 1.09 : chunk.emphasis === 'weighted' ? 0.94 : 1;
  return Math.max(0.9, position * weight);
}
