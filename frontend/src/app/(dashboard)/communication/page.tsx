'use client';

import { Fragment, useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { Mic, MicOff, RefreshCw, RotateCcw, Send, MessageSquare, BookOpen, Timer } from 'lucide-react';
import { toast } from 'sonner';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { AIWorkingIndicator } from '@/components/ui/ai-working-indicator';
import { DeliveryTranscript } from '@/components/interview/DeliveryTranscript';
import { useSpeechRecognition } from '@/hooks/useSpeech';
import {
  useCommunicationPrompts,
  useReadingPassages,
  useEvaluateCommunication,
  useCommunicationCrossQuestion,
  type CommunicationResult,
} from '@/hooks/useCommunication';
import { summarizeDelivery, type PauseEvent } from '@/lib/speech/delivery';
import { scoreBand } from '@/lib/score-bands';
import { fadeUp, staggerContainer } from '@/lib/motion';
import { cn } from '@/lib/utils';
import { PageHeader } from '@/components/ui/page-header';
import { Paywall, paywallFromError, type PaywallInfo } from '@/components/billing/Paywall';
import { CreditMeter } from '@/components/billing/CreditMeter';

export const runtime = 'edge';

type Mode = 'speaking' | 'reading';

/**
 * The threshold at which a count turns coral.
 *
 * THREE IS NOT A NEW NUMBER. This page already drew the pause chip and the live filler chip
 * red above three; naming it once stops the result view and the live view drifting apart the
 * way the score bands did (M12 in docs/MISTAKES.md). If it should move, it moves here.
 */
const COUNT_ALERT = 3;

/**
 * The colour of a words-per-minute figure.
 *
 * THE BOUNDARIES ARE `paceVerdict`'s OWN — 100 and 170, from lib/speech/delivery.ts — and not
 * a second set chosen here. The sentence the candidate reads beside this number comes from
 * that function (or from the server, which bands the same way), and a figure tinted amber next
 * to the words "Good, natural pace" makes one of the two look like a bug. That is exactly the
 * failure the score-bands module exists to record.
 */
function paceTone(wpm: number): string {
  if (wpm <= 0) return 'text-muted-foreground';
  return wpm < 100 || wpm > 170 ? 'text-accent-amber-ink' : 'text-accent-emerald-ink';
}

function countTone(n: number): string {
  return n > COUNT_ALERT ? 'text-accent-coral-ink' : 'text-foreground';
}

/**
 * A figure and what it is. Mono, tabular, quiet label underneath.
 *
 * Every number on this page is one a candidate compares against their own number from last
 * week, and proportional digits give two three-digit numbers two different widths.
 */
function Figure({
  value,
  unit,
  label,
  tone,
}: {
  value: string;
  unit?: string;
  label: string;
  tone?: string;
}) {
  return (
    <div className="min-w-0">
      <p
        className={cn(
          'font-mono text-xl font-bold leading-none tabular-nums',
          tone ?? 'text-foreground',
        )}
      >
        {value}
        {unit && <span className="ml-0.5 text-[11px] font-medium text-muted-foreground">{unit}</span>}
      </p>
      <p className="mt-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
    </div>
  );
}

/**
 * THE SONGLINE — the one ornament this product allows itself, and only here.
 *
 * DESIGN-LANGUAGE §2 permits a waveform in exactly one situation: where audio genuinely
 * happened, drawn from real data. This is that situation, and every pixel of it is measured:
 *
 *   • a bar is an unbroken RUN of speech. Its WIDTH is how long that run took — the run's word
 *     count at the answer's own measured words-per-minute — and its HEIGHT is how long the run
 *     is against the longest one, so the silhouette is the shape of your fluency.
 *   • a gap is a real detected silence. Its WIDTH is the seconds it lasted, on the same time
 *     axis as the bars, with a coral hairline where the candidate stopped.
 *
 * WHAT IT DELIBERATELY DOES NOT DRAW: amplitude. We never capture loudness, and a wiggle
 * standing in for one would be the decoration this whole document exists to prevent. Heights
 * vary only where a real quantity varies.
 *
 * Square-rooted because a 60-word run is not six times more impressive than a 10-word one, and
 * a linear map flattens every short run into a stub you cannot see.
 */
function Songline({
  words,
  wpm,
  pauses,
  className,
}: {
  words: number;
  wpm: number;
  pauses: PauseEvent[];
  className?: string;
}) {
  // No words or no measured rate means no time axis, and a time axis is the whole drawing.
  if (words <= 0 || wpm <= 0) return null;

  const secPerWord = 60 / wpm;
  const ordered = [...pauses]
    .filter((p) => p.seconds > 0)
    .sort((a, b) => a.wordIndex - b.wordIndex);

  const runs: number[] = [];
  const gaps: number[] = [];
  let cursor = 0;
  for (const p of ordered) {
    // Clamped, because a pause index from the recogniser can land past the finalized
    // transcript's last word; unclamped that turns a run negative and the bar draws inside-out.
    const at = Math.max(cursor, Math.min(words, p.wordIndex));
    runs.push(at - cursor);
    gaps.push(p.seconds);
    cursor = at;
  }
  runs.push(Math.max(0, words - cursor));

  const total =
    runs.reduce((a, r) => a + r * secPerWord, 0) + gaps.reduce((a, s) => a + s, 0);
  if (total <= 0) return null;

  const longest = Math.max(...runs, 1);
  const silence = Math.round(gaps.reduce((a, s) => a + s, 0));

  return (
    <div
      // Said in words as well as drawn, because a screen reader gets nothing at all from a row
      // of divs — and the sentence is the actual finding, not a courtesy.
      role="img"
      aria-label={
        ordered.length === 0
          ? `Delivery: ${words} words spoken without a detected pause.`
          : `Delivery: ${words} words in ${runs.length} unbroken runs, broken by ${ordered.length} pauses totalling ${silence} seconds.`
      }
      className={cn('flex h-11 w-full items-center', className)}
    >
      {runs.map((run, i) => (
        <Fragment key={i}>
          <span
            className="min-w-px rounded-full bg-accent-teal/70"
            style={{
              width: `${((run * secPerWord) / total) * 100}%`,
              height: `${26 + 74 * Math.sqrt(run / longest)}%`,
            }}
          />
          {i < gaps.length && (
            <span
              className="relative h-full min-w-[3px] shrink-0"
              style={{ width: `${(gaps[i] / total) * 100}%` }}
            >
              <span className="absolute inset-y-[30%] left-1/2 w-px -translate-x-1/2 bg-accent-coral" />
            </span>
          )}
        </Fragment>
      ))}
    </div>
  );
}

function ScoreBar({ label, value }: { label: string; value: number }) {
  /*
   * ONE SET OF BANDS, AND IT IS THE BACKEND'S.
   *
   * This bar used to be a fixed `from-primary to-accent-violet` gradient — a gradient between
   * two adjacent hues, which DESIGN-RULES bans by name, and which failed its own test: a 3.1
   * and a 9.4 were painted the same colour and the length carried everything.
   *
   * The four sub-scores are 0–10 where `score-bands` is 0–100, so ×10 is the entire
   * conversion. Worth stating plainly given M12: unlike the report, this endpoint returns no
   * label of its own for these four, so there is no backend word here for the colour to
   * contradict. The colour is the only verdict, which is why it has to be the shared one.
   */
  const band = scoreBand(value * 10);
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-xs font-semibold">{label}</span>
        <span className="font-mono text-xs font-bold tabular-nums">
          {value.toFixed(1)}
          <span className="font-medium text-muted-foreground">/10</span>
        </span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <motion.div
          className={cn('h-full rounded-full', band.bar)}
          initial={{ width: 0 }}
          animate={{ width: `${Math.min(value * 10, 100)}%` }}
          transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
        />
      </div>
    </div>
  );
}

function fmt(s: number) {
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toString().padStart(2, '0')}`;
}

/**
 * The communication round.
 *
 * @lit-exclusive-views — two whole screens live in this file and only one is ever rendered:
 * the STAGE, where the prompt, the mic and the transcript are, and the SCORECARD that
 * replaces it once feedback comes back. Each is a complete view with a single subject, so
 * each carries its own `.lit` element. Declared because lit-hierarchy.test.ts otherwise
 * enforces one per file.
 */
export default function CommunicationPage() {
  // Only `data` was destructured here before. The extra fields are read off the SAME query —
  // no new call, no new key — because a page cannot have a real error state while the only
  // thing it can see is whether data happens to be undefined.
  const {
    data: prompts,
    error: promptsError,
    refetch: refetchPrompts,
    isFetching: promptsFetching,
  } = useCommunicationPrompts();
  const {
    data: passages,
    isLoading: passagesLoading,
    error: passagesError,
    refetch: refetchPassages,
    isFetching: passagesFetching,
  } = useReadingPassages();
  const evaluate = useEvaluateCommunication();
  const crossQ = useCommunicationCrossQuestion();
  const stt = useSpeechRecognition();

  const [mode, setMode] = useState<Mode>('speaking');
  const [promptIdx, setPromptIdx] = useState(0);
  const [passageIdx, setPassageIdx] = useState(0);
  const [answer, setAnswer] = useState('');
  const [result, setResult] = useState<CommunicationResult | null>(null);
  //: Set from the server's 402, never from a cached balance — see the note in the
  //: interview setup page for why the request is always attempted first.
  const [paywall, setPaywall] = useState<PaywallInfo | null>(null);
  // Cross-question follow-up (speaking mode): the AI probes the candidate's
  // answer; their follow-up appends to the same transcript so delivery analysis
  // naturally covers both answers.
  const [crossQuestion, setCrossQuestion] = useState<string | null>(null);
  const startRef = useRef<number | null>(null);
  const elapsedRef = useRef(0);

  // Reading-mode countdown.
  const [secondsLeft, setSecondsLeft] = useState(0);
  /*
   * The countdown, mirrored in a ref.
   *
   * The interval needs to know the CURRENT value to decide when time is up, and it cannot read
   * `secondsLeft` — the closure it captured when `setInterval` was called holds the value from
   * that render, forever. Reaching for the updater form to get around that is what caused the
   * bug documented at the interval below, so the value is mirrored here instead: a ref is
   * readable from a stale closure and writing to it is not a render concern.
   */
  const secondsRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const promptText = prompts?.[promptIdx]?.text ?? 'Tell me about yourself.';
  const passage = passages?.[passageIdx];

  useEffect(() => {
    if (stt.transcript) setAnswer(stt.transcript);
  }, [stt.transcript]);

  const clearTimer = () => {
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = null;
  };
  useEffect(() => () => clearTimer(), []);

  const stopRecording = () => {
    stt.stop();
    clearTimer();
    if (startRef.current) elapsedRef.current += (Date.now() - startRef.current) / 1000;
    startRef.current = null;
  };

  const startRecording = () => {
    if (!answer) stt.reset();
    startRef.current = Date.now();
    stt.start();
    // In reading mode, run a countdown for the passage's time budget.
    if (mode === 'reading' && passage) {
      setSecondsLeft(passage.seconds);
      secondsRef.current = passage.seconds;
      clearTimer();
      /*
       * THE SIDE EFFECTS MOVED OUT OF THE STATE UPDATER, and this was a real bug.
       *
       * `clearTimer()`, `stopRecording()` and the toast used to live inside
       * `setSecondsLeft(s => { ... })`. A React state updater must be a PURE function of the
       * previous state: React is allowed to call it more than once for a single update, and
       * with `reactStrictMode: true` in next.config.ts it deliberately does so in development.
       *
       * So when the passage ran out, the candidate's microphone was stopped twice and they
       * were told "Time's up" twice — on the one screen in the product where the mic state is
       * the whole interaction.
       *
       * The interval callback is the right home for all three: it already IS an effect, it
       * fires exactly once per tick, and it can read the live value from `secondsRef` rather
       * than from a closure that was captured a minute ago.
       */
      timerRef.current = setInterval(() => {
        const next = secondsRef.current - 1;
        secondsRef.current = next;
        setSecondsLeft(next > 0 ? next : 0);
        if (next <= 0) {
          clearTimer();
          stopRecording();
          toast.info("Time's up — submit to see how you did.");
        }
      }, 1000);
    }
  };

  const toggleMic = () => {
    if (stt.listening) stopRecording();
    else startRecording();
  };

  const reset = () => {
    stt.stop();
    stt.reset();
    clearTimer();
    setAnswer('');
    setResult(null);
    setCrossQuestion(null);
    elapsedRef.current = 0;
    startRef.current = null;
    setSecondsLeft(0);
    // Kept in step with the state it mirrors: a ref that drifts from its own state is worse
    // than no ref, because the next countdown would start from the previous passage's total.
    secondsRef.current = 0;
  };

  // Ask the AI for ONE follow-up that probes the candidate's answer. Their
  // reply appends to the same transcript, then they submit for feedback.
  const askFollowUp = () => {
    if (stt.listening) stopRecording();
    crossQ.mutate(
      { prompt_text: promptText, transcript: answer },
      {
        onSuccess: (q) => {
          setCrossQuestion(q);
          toast.info('Follow-up added — tap the mic and answer it too.');
        },
        onError: (err: Error) => toast.error(err.message || 'Could not generate a follow-up.'),
      }
    );
  };

  const next = () => {
    reset();
    if (mode === 'speaking' && prompts?.length) setPromptIdx((i) => (i + 1) % prompts.length);
    if (mode === 'reading' && passages?.length) setPassageIdx((i) => (i + 1) % passages.length);
  };

  const switchMode = (m: Mode) => {
    if (m === mode) return;
    reset();
    setMode(m);
  };

  const handleSubmit = () => {
    if (stt.listening) stopRecording();
    const seconds = Math.max(1, Math.round(elapsedRef.current));
    const summary = summarizeDelivery({ text: answer, seconds, pauses: stt.pauses });
    evaluate.mutate(
      {
        prompt_text:
          mode === 'reading'
            ? `Read this passage aloud clearly and fluently: ${passage?.text ?? ''}`
            : crossQuestion
              ? `${promptText}\n\nFollow-up asked: ${crossQuestion}`
              : promptText,
        transcript: answer,
        duration_seconds: seconds,
        filler_count: summary.fillerCount,
        words_per_minute: summary.wpm,
        pause_count: summary.pauseCount,
        total_pause_seconds: summary.totalPauseSec,
        mode,
      },
      {
        onSuccess: setResult,
        onError: (err: Error) => {
          // The allowance is spent. Shown as a panel rather than a toast: this is not a
          // transient failure to dismiss, and the candidate has just spoken a whole answer —
          // they are owed an explanation and a next step, not a message that fades.
          const blocked = paywallFromError(err);
          if (blocked) {
            setPaywall(blocked);
            return;
          }
          toast.error(err.message || 'Could not evaluate your answer.');
        },
      }
    );
  };

  const summary = summarizeDelivery({
    text: answer,
    seconds: Math.max(1, Math.round(elapsedRef.current)),
    pauses: stt.pauses,
  });

  // ─── Result view ──────────────────────────────────────────────────────────
  if (result) {
    /*
     * THE VERDICT COLOUR COMES FROM THE SHARED BANDS, not from the ad-hoc 7/4 thresholds this
     * file used to carry. Those were a fourth answer to "what does this score mean" in a
     * codebase that has already been burned three times by having more than one (M12): a 6.9
     * was tinted the same amber as a 4.1, and a 7.0 jumped to the same green as a 9.8.
     *
     * ×10 is the whole conversion — the bands are 0–100 and this round scores 0–10. The band's
     * word is printed beside the number because the colour on its own is a hint; the word is
     * the verdict, and DESIGN-LANGUAGE §6 asks for verdicts, not decoration.
     */
    const band = scoreBand(result.overall_score * 10);

    return (
      <motion.div
        initial="hidden"
        animate="visible"
        variants={staggerContainer(0.06)}
        className="mx-auto max-w-4xl space-y-6 pb-12"
      >
        <motion.div variants={fadeUp}>
          <PageHeader
            eyebrow="Spoken round"
            title={mode === 'reading' ? 'How that read' : 'How that came out'}
            description="The panel hears the delivery before it hears the answer. This is the delivery."
          />
        </motion.div>

        {/* ─── THE SCORECARD. The one thing on this page that is ahead of everything else.
            Elevated, wider than the rest of the stack's rhythm, and carrying the songline —
            everything below it is evidence for this number, and is drawn flat so it reads
            that way. A page where the score and the tip are the same white card at the same
            height is a page where nothing was decided. */}
        <motion.div variants={fadeUp}>
          <Card
            variant="outline"
            padding="none"
            // `.lit` rather than the hand-rolled elevated-plus-teal-ring this had. Same
            // intent — one surface ahead of everything else — but expressed in the class the
            // rest of the product uses, so the light is identical in every room and
            // lit-hierarchy.test.ts can see it. The light is warm everywhere; what changes
            // per page is the accent, which the teal rule below already carries.
            className="lit overflow-hidden"
          >
            {/* The long horizontal rule, in the round's own colour. Same mark as the eyebrow's
                dash, at page width — a rule the eye can follow, not a header flourish. */}
            <div aria-hidden className="h-0.5 w-full bg-accent-teal" />

            <div className="p-6 sm:p-8">
              <p className="font-mono text-[11px] uppercase tracking-[0.22em] text-accent-teal-ink">
                {mode === 'reading' ? 'Reading fluency' : 'Communication score'}
              </p>

              <div className="mt-4 flex flex-wrap items-end gap-x-8 gap-y-5">
                <div className="flex items-end gap-3">
                  <p className="font-mono text-[52px] font-bold leading-[0.8] tracking-[-0.04em] tabular-nums sm:text-[64px]">
                    {result.overall_score.toFixed(1)}
                    <span className="text-2xl font-medium text-muted-foreground">/10</span>
                  </p>
                  <span
                    className={cn(
                      'mb-1.5 shrink-0 rounded-full px-2.5 py-1 text-[11px] font-semibold',
                      band.chip,
                    )}
                  >
                    {band.label}
                  </span>
                </div>

                <div className="flex flex-1 flex-wrap items-start gap-x-7 gap-y-4">
                  <Figure
                    value={String(result.words_per_minute)}
                    unit="wpm"
                    label="pace"
                    tone={paceTone(result.words_per_minute)}
                  />
                  <Figure
                    value={String(result.filler_count)}
                    label="fillers"
                    tone={countTone(result.filler_count)}
                  />
                  <Figure
                    value={String(result.pause_count)}
                    unit={result.total_pause_seconds ? `· ${result.total_pause_seconds}s` : undefined}
                    label="pauses"
                    tone={countTone(result.pause_count)}
                  />
                  {result.eye_contact_pct !== null && (
                    <Figure
                      value={String(result.eye_contact_pct)}
                      unit="%"
                      label="eye contact"
                    />
                  )}
                </div>
              </div>

              {/* THE PAUSE MAP. `stt.pauses` and the local word count are the exact figures
                  that were posted to the scorer, so the drawing and the numbers above it
                  cannot disagree — reading the shape off `result` instead would have meant
                  two sources for one picture. */}
              {summary.words > 0 && (
                <div className="mt-7">
                  <Songline words={summary.words} wpm={summary.wpm} pauses={stt.pauses} />
                  <p className="mt-2 font-mono text-[11px] tabular-nums text-muted-foreground">
                    {summary.words} words
                    {stt.pauses.length > 0
                      ? ` · ${summary.pauseCount} pauses · ${summary.totalPauseSec}s of silence`
                      : ' · no pauses long enough to notice'}
                  </p>
                </div>
              )}

              <div className="mt-7 flex flex-wrap gap-2">
                <Button variant="secondary" onClick={reset}><RotateCcw className="h-4 w-4" /> Try again</Button>
                <Button onClick={next}><RefreshCw className="h-4 w-4" /> Next</Button>
              </div>
            </div>
          </Card>
        </motion.div>

        {/* Deliberately NOT another equal row of three. The four sub-scores are a narrow
            column and the transcript is the wide one, because the transcript is the thing a
            candidate actually rereads. */}
        <div className="grid gap-4 lg:grid-cols-5">
          <motion.div variants={fadeUp} className="lg:col-span-2">
            <Card variant="flat" className="h-full space-y-4 p-5">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                The four marks
              </p>
              <ScoreBar label="Clarity" value={result.clarity_score} />
              <ScoreBar label="Structure" value={result.structure_score} />
              <ScoreBar label="Confidence" value={result.confidence_score} />
              <ScoreBar label="Conciseness" value={result.conciseness_score} />
            </Card>
          </motion.div>

          {/* Transcript with fillers in red + pause markers */}
          <motion.div variants={fadeUp} className="lg:col-span-3">
            <Card variant="flat" className="h-full space-y-2 p-5">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Your delivery (filler words in <span className="text-accent-coral-ink">red</span>, pauses marked)
              </p>
              <div className="rounded-lg border border-border/50 bg-surface-elevated p-4 text-sm">
                <DeliveryTranscript text={answer} pauses={stt.pauses} />
              </div>
            </Card>
          </motion.div>
        </div>

        <motion.div variants={fadeUp}>
          <Card variant="flat" className="space-y-4 p-5 sm:p-6">
            <p className="text-sm leading-relaxed text-foreground/85">{result.feedback}</p>

            {/* THE EMOJI ARE GONE. A speaking-head glyph and a speech-bubble glyph used to sit
                in front of these two lines. They rendered at a different size on every
                platform and were the clearest tell on the page that nobody had chosen the
                typography. A mono label in the round's colour says the same thing, and unlike
                a glyph it lines the two notes up with each other. */}
            {(result.pace_feedback || result.filler_feedback) && (
              <div className="space-y-2">
                {result.pace_feedback && (
                  <p className="flex gap-3 rounded-lg border border-border/50 bg-surface p-3 text-xs text-muted-foreground">
                    <span className="shrink-0 font-mono text-[10px] uppercase tracking-[0.18em] text-accent-teal-ink">
                      Pace
                    </span>
                    <span className="min-w-0">{result.pace_feedback}</span>
                  </p>
                )}
                {result.filler_feedback && (
                  <p className="flex gap-3 rounded-lg border border-border/50 bg-surface p-3 text-xs text-muted-foreground">
                    <span className="shrink-0 font-mono text-[10px] uppercase tracking-[0.18em] text-accent-teal-ink">
                      Fillers
                    </span>
                    <span className="min-w-0">{result.filler_feedback}</span>
                  </p>
                )}
              </div>
            )}

            <div className="grid gap-5 sm:grid-cols-2">
              {result.strengths.length > 0 && (
                <div>
                  <p className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-accent-emerald-ink">Strengths</p>
                  <ul className="space-y-1 text-sm text-foreground/80">
                    {result.strengths.map((s, i) => <li key={i} className="flex gap-2"><span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-accent-emerald" />{s}</li>)}
                  </ul>
                </div>
              )}
              {result.improvements.length > 0 && (
                <div>
                  <p className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-accent-amber-ink">To improve</p>
                  <ul className="space-y-1 text-sm text-foreground/80">
                    {result.improvements.map((s, i) => <li key={i} className="flex gap-2"><span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-accent-amber" />{s}</li>)}
                  </ul>
                </div>
              )}
            </div>
          </Card>
        </motion.div>
      </motion.div>
    );
  }

  // ─── Blocked: the communication allowance is spent ────────────────────────
  //
  // The answer is deliberately NOT cleared. They spoke it, and if they upgrade in another tab
  // and come back, throwing away a transcript they cannot easily reproduce would be its own
  // small betrayal.
  if (paywall) {
    return (
      <div className="mx-auto mt-10 max-w-2xl space-y-6">
        <Paywall
          info={paywall}
          /* CLEARING IT IS THE RETRY. The paywall is shown because the SERVER refused with a
             402; once an item lands on the account that refusal is stale, so dismissing the
             wall puts the candidate back on the page they were stopped on with the thing they
             just bought available. Nothing is auto-started — buying and starting are two
             decisions, and the second one is theirs. */
          onPurchased={() => setPaywall(null)}
        />
        <div className="text-center">
          <button
            type="button"
            onClick={() => setPaywall(null)}
            className="text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
          >
            Back to your answer
          </button>
        </div>
      </div>
    );
  }

  // In reading mode there is nothing to read until the passages land, and "there are none"
  // must not look like "still fetching" — see the empty and error branches inside the stage.
  // Keyed on the PASSAGE rather than on the error, for the reason spelled out at the error
  // branch below: a failed background refetch keeps the data, and a passage on screen is a
  // passage you can still read aloud.
  const readingBlocked = mode === 'reading' && !passage;

  // ─── Answer / reading view ──────────────────────────────────────────────────
  return (
    <motion.div initial="hidden" animate="visible" variants={staggerContainer(0.08)} className="mx-auto max-w-3xl space-y-6">
      {/* THE HEADER MOVED ABOVE THE CREDIT METER. The eyebrow is wayfinding — it is how you
          check which of fourteen destinations you are in — and it cannot do that job from
          underneath a balance panel. The meter still sits above the stage, which is the whole
          point of it: the number has to be known before an answer is spoken, not after the
          server refuses one. */}
      <motion.div variants={fadeUp} className="border-b border-border pb-6">
        <PageHeader
          eyebrow="Spoken round"
          title="Communication Round"
          description="Say it out loud. We count the pace, the pauses and the words you fall back on — the three things a panel registers before it registers your answer."
        />
      </motion.div>

      {/* Mode tabs — a segmented control, not two competing cards. `aria-pressed` rather than
          role="tab": these swap the content of the page below without a tablist/tabpanel pair
          to point at, and a half-wired tab role is worse for a screen reader than an honest
          toggle. min-h-11 holds the 44px tap target. */}
      <motion.div variants={fadeUp} className="flex gap-1.5 rounded-xl border border-border bg-surface p-1.5">
        <button
          onClick={() => switchMode('speaking')}
          aria-pressed={mode === 'speaking'}
          className={cn(
            'flex min-h-11 flex-1 items-center justify-center gap-2 rounded-lg px-4 text-sm font-semibold transition-colors',
            mode === 'speaking'
              ? 'bg-accent-teal-soft text-accent-teal-ink shadow-elev-1'
              : 'text-muted-foreground hover:text-foreground'
          )}
        >
          <MessageSquare className="h-4 w-4" /> Speaking Prompts
        </button>
        <button
          onClick={() => switchMode('reading')}
          aria-pressed={mode === 'reading'}
          className={cn(
            'flex min-h-11 flex-1 items-center justify-center gap-2 rounded-lg px-4 text-sm font-semibold transition-colors',
            mode === 'reading'
              ? 'bg-accent-teal-soft text-accent-teal-ink shadow-elev-1'
              : 'text-muted-foreground hover:text-foreground'
          )}
        >
          <BookOpen className="h-4 w-4" /> Reading Comprehension
        </button>
      </motion.div>

      <motion.div variants={fadeUp}>
        <CreditMeter />
      </motion.div>

      {/* ─── THE STAGE. Everything else on this page is flat or bare; this is the only
          elevated surface, and it is where the whole task happens. */}
      <motion.div variants={fadeUp}>
        <Card
          variant="outline"
          padding="none"
          // See the note on the scorecard above: same treatment, and the two are mutually
          // exclusive views of this route.
          className="lit overflow-hidden"
        >
          <div aria-hidden className="h-0.5 w-full bg-accent-teal" />

          <div className="p-6 sm:p-8">
            {mode === 'speaking' ? (
              <>
                <div className="mb-3 flex items-center justify-between gap-3">
                  <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-accent-teal-ink">
                    Prompt
                  </span>
                  {!!prompts?.length && (
                    <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
                      {promptIdx + 1}/{prompts.length}
                    </span>
                  )}
                </div>
                <h2 className="text-[clamp(1.25rem,2.4vw,1.6rem)] font-medium leading-[1.25] tracking-[-0.02em]">
                  {promptText}
                </h2>
                {/* The follow-up is indigo, not teal: teal is this round, indigo is the panel
                    speaking. Painting it the round's own colour would make it read as more
                    prompt text rather than as a second question aimed at what you just said. */}
                {crossQuestion && (
                  <div className="mt-4 rounded-lg border border-accent-indigo/30 bg-accent-indigo-soft p-3">
                    <p className="mb-1 font-mono text-[10px] uppercase tracking-[0.18em] text-accent-indigo-ink">
                      Follow-up (answer this too)
                    </p>
                    <p className="text-sm font-medium text-foreground/90">{crossQuestion}</p>
                  </div>
                )}
                {/* Prompts failing is not the same as having none. The fallback prompt above
                    keeps the round usable either way, so this is a quiet line with a retry
                    rather than a full-page DataError — a page-level takeover here would remove
                    the mode switch and the mic along with the error. */}
                {promptsError && (
                  <p className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-accent-coral/30 bg-accent-coral-soft p-3 text-xs text-accent-coral-ink">
                    <span>
                      We could not reach the prompt bank, so this is the one we always start with.
                    </span>
                    <button
                      type="button"
                      onClick={() => refetchPrompts()}
                      className="font-semibold underline underline-offset-4"
                    >
                      {promptsFetching ? 'Fetching…' : 'Try again'}
                    </button>
                  </p>
                )}
              </>
            ) : (
              <>
                <div className="mb-3 flex items-center justify-between gap-3">
                  <span className="font-mono text-[11px] uppercase tracking-[0.22em] text-accent-teal-ink">
                    Read aloud
                  </span>
                  <div className="flex items-center gap-3">
                    {!!passages?.length && (
                      <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
                        {passageIdx + 1}/{passages.length}
                      </span>
                    )}
                    <span
                      className={cn(
                        'flex items-center gap-1 rounded-full border px-2.5 py-1 font-mono text-[11px] font-semibold tabular-nums',
                        secondsLeft > 0 && secondsLeft <= 10
                          ? 'border-accent-coral/40 bg-accent-coral-soft text-accent-coral-ink'
                          : 'border-border text-muted-foreground'
                      )}
                    >
                      <Timer className="h-3 w-3" />
                      {secondsLeft > 0 ? fmt(secondsLeft) : `${passage?.seconds ?? 0}s`}
                    </span>
                  </div>
                </div>

                {/* `&& !passage`, NOT `passagesError` alone. In TanStack v5 a failed
                    BACKGROUND refetch sets `error` while keeping the data that is already on
                    screen, so testing the error first would replace a passage the candidate is
                    part-way through reading — and take the mic, the transcript and the
                    feedback button with it. Not reachable today (refetchOnWindowFocus is off,
                    staleTime is 30 min, and the only manual refetch lives inside this error
                    panel) but it costs one condition to make it unreachable on purpose rather
                    than by the current settings. */}
                {passagesError && !passage ? (
                  /* A REAL ERROR STATE, WHICH IS NOT AN EMPTY ONE. "No passage" and "we could
                     not fetch the passage" are opposite messages and this branch exists so
                     they never share a screen. */
                  <div className="rounded-lg border border-accent-coral/30 bg-accent-coral-soft p-5">
                    <p className="text-sm font-semibold text-accent-coral-ink">
                      The passages did not load
                    </p>
                    <p className="mt-1 text-xs text-accent-coral-ink/85">
                      {(passagesError as { message?: string }).message?.trim() ||
                        'Something went wrong fetching them. This is usually temporary.'}
                    </p>
                    <div className="mt-4 flex flex-wrap gap-2">
                      <Button variant="secondary" onClick={() => refetchPassages()} loading={passagesFetching}>
                        <RefreshCw className="h-4 w-4" /> Try again
                      </Button>
                      <Button variant="ghost" onClick={() => switchMode('speaking')}>
                        Speak a prompt instead
                      </Button>
                    </div>
                  </div>
                ) : passagesLoading ? (
                  <p className="rounded-lg border border-border/50 bg-surface-elevated p-5 text-sm text-muted-foreground">
                    The panel is warming up…
                  </p>
                ) : !passage ? (
                  /* A REAL EMPTY STATE: what happened, what to do, and the way out. The old
                     page printed "Loading passage…" here forever, which told a candidate with
                     an empty bank that the app was still working. */
                  <div className="rounded-lg border border-dashed border-border p-6">
                    <h3 className="text-sm font-semibold">Nothing to read aloud yet</h3>
                    <p className="mt-1 max-w-md text-xs leading-relaxed text-muted-foreground">
                      The reading bank came back empty. The speaking prompts measure the same
                      pace, pauses and filler words, so nothing about your delivery goes
                      unmeasured while this is being filled.
                    </p>
                    <Button variant="secondary" size="sm" className="mt-4" onClick={() => switchMode('speaking')}>
                      <MessageSquare className="h-3.5 w-3.5" /> Speak a prompt instead
                    </Button>
                  </div>
                ) : (
                  <>
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                      {passage.title}
                    </p>
                    <p className="mt-2 rounded-lg border border-border/50 bg-surface-elevated p-4 text-base leading-relaxed text-foreground/90">
                      {passage.text}
                    </p>
                  </>
                )}
              </>
            )}

            {!stt.supported ? (
              <p className="mt-6 rounded-lg border border-accent-amber/30 bg-accent-amber-soft p-3 text-sm text-accent-amber-ink">
                Your browser doesn&apos;t support speech recognition. Please use Chrome or Edge for the spoken round.
              </p>
            ) : readingBlocked ? null : (
              <div className="mt-8 flex flex-col items-center gap-5">
                <button
                  onClick={toggleMic}
                  disabled={evaluate.isPending}
                  // The button's own label changes with its state, and an icon-only control
                  // announces as nothing without this. `aria-pressed` is what tells a screen
                  // reader the mic is currently live.
                  aria-label={stt.listening ? 'Stop recording' : 'Start recording'}
                  aria-pressed={stt.listening}
                  className={cn(
                    'relative flex h-24 w-24 items-center justify-center rounded-full transition-[color,background-color,border-color,box-shadow,transform,opacity] disabled:opacity-50',
                    stt.listening ? 'bg-destructive text-destructive-foreground shadow-glow' : 'bg-primary text-primary-foreground shadow-glow hover:shadow-glow-lg'
                  )}
                >
                  {stt.listening && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-destructive opacity-40 motion-reduce:animate-none" />}
                  {stt.listening ? <MicOff className="h-9 w-9" /> : <Mic className="h-9 w-9" />}
                </button>
                <p className="text-sm font-medium text-muted-foreground">
                  {stt.listening
                    ? 'Listening… tap to stop'
                    : answer
                      ? 'Tap to continue, or submit for feedback'
                      : mode === 'reading'
                        ? 'Tap the mic and read the passage aloud'
                        : 'Tap the mic and answer aloud'}
                </p>

                {/* THE MIC'S OWN ERROR WAS COMPUTED AND RENDERED NOWHERE. `stt.error` is set
                    for a denied permission or a missing device — the two cases where tapping
                    the mic does nothing at all — and a candidate staring at an empty
                    transcript had no way to learn that the browser had refused. */}
                {stt.error && (
                  <p className="w-full rounded-lg border border-accent-coral/30 bg-accent-coral-soft p-3 text-xs text-accent-coral-ink">
                    {stt.error}
                  </p>
                )}

                {/* Live transcript with fillers in red + pause markers */}
                <div className="min-h-[96px] w-full rounded-lg border border-border/50 bg-surface-elevated p-4 text-sm">
                  <DeliveryTranscript text={answer} pauses={stt.pauses} interim={stt.listening ? stt.interim : ''} />
                </div>

                {/* THE SONGLINE IS DRAWN ONLY ONCE THE MIC STOPS, and that is not a taste
                    call. `elapsedRef` accumulates on stop, so mid-recording the summary is
                    computed against a one-second floor and the measured rate is nonsense —
                    the bars would be hairlines beside enormous pause gaps. A picture of a
                    number that is wrong is worse than no picture. */}
                {answer && !stt.listening && (
                  <div className="w-full">
                    <Songline words={summary.words} wpm={summary.wpm} pauses={stt.pauses} />
                  </div>
                )}

                {/* Live delivery mini-stats */}
                {answer && (
                  <div className="flex w-full flex-wrap items-start justify-center gap-x-8 gap-y-4 border-t border-border/60 pt-5">
                    <Figure value={String(summary.words)} label="words" />
                    <Figure value={String(summary.wpm)} unit="wpm" label="pace" tone={paceTone(summary.wpm)} />
                    <Figure value={String(summary.fillerCount)} label="fillers" tone={countTone(summary.fillerCount)} />
                    <Figure
                      value={String(summary.pauseCount)}
                      unit={summary.totalPauseSec ? `· ${summary.totalPauseSec}s` : undefined}
                      label="pauses"
                      tone={countTone(summary.pauseCount)}
                    />
                  </div>
                )}

                {evaluate.isPending ? (
                  <AIWorkingIndicator messages={['Analyzing your delivery…', 'Scoring clarity & pauses…', 'Writing feedback…']} />
                ) : crossQ.isPending ? (
                  <AIWorkingIndicator messages={['Thinking of a follow-up question…']} />
                ) : (
                  <div className="flex w-full flex-wrap items-center justify-end gap-2">
                    <Button variant="ghost" onClick={next}>Skip</Button>
                    {mode === 'speaking' && !crossQuestion && (
                      <Button variant="secondary" onClick={askFollowUp} disabled={!answer.trim()}>
                        <MessageSquare className="h-4 w-4" /> Ask me a follow-up
                      </Button>
                    )}
                    <Button onClick={handleSubmit} disabled={!answer.trim()}>
                      <Send className="h-4 w-4" /> Get feedback
                    </Button>
                  </div>
                )}
              </div>
            )}
          </div>
        </Card>
      </motion.div>

      {/* The tip, set as a footnote rather than a centred card — it is the quietest thing
          here and it should look it. The teal dash is the same mark as the eyebrow's. */}
      <motion.div variants={fadeUp} className="flex gap-3 pb-4">
        <span aria-hidden className="mt-2 h-px w-3.5 shrink-0 bg-accent-teal" />
        <p className="max-w-xl text-xs leading-relaxed text-muted-foreground">
          {mode === 'reading'
            ? 'Read at a steady, natural pace. Long silences and the words you fall back on are marked in the transcript as you go.'
            : 'Aim for a shape: a one-line opening, the point with one concrete example, a one-line close. Structure is scored separately from what you said.'}
        </p>
      </motion.div>
    </motion.div>
  );
}
