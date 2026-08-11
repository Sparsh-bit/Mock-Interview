'use client';

import { useInterview } from '@/hooks/useInterview';
import { useParams } from 'next/navigation';
import { useState, useEffect, useMemo, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { AlertTriangle, Loader2, Mic, MicOff, RefreshCw, Send, Sparkles, StopCircle, Volume2, WifiOff } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { CodingWorkspace } from '@/components/interview/CodingWorkspace';
import { PresenceMonitor } from '@/components/interview/PresenceMonitor';
import { DeliveryTranscript } from '@/components/interview/DeliveryTranscript';
import type { CodeLanguage } from '@/hooks/useCode';
import { useSpeechRecognition, useSpeechSynthesis, usePanelVoices } from '@/hooks/useSpeech';
import { useCandidateName } from '@/hooks/useCandidateName';
import { useInterviewPanel, useInterviewers, type PanelLine } from '@/hooks/useInterviewPanel';
import { countUnprofessional, summarizeDelivery } from '@/lib/speech/delivery';
import { fadeUp, scalePop, staggerContainer } from '@/lib/motion';
import { cn } from '@/lib/utils';

export const runtime = 'edge';

/**
 * Full-panel "generating the next question" animation. Scoring is deferred to
 * the final report, so between questions the candidate sees this calm indicator
 * (never a raw spinner or a blank screen) while the AI prepares what's next.
 */
function GeneratingQuestion({ label }: { label: string }) {
  return (
    <motion.div
      initial="hidden"
      animate="visible"
      variants={scalePop}
      className="flex flex-col items-center gap-5 py-16 text-center"
    >
      <div className="relative flex h-16 w-16 items-center justify-center">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary/20" />
        <span className="absolute inline-flex h-12 w-12 rounded-full bg-primary/10" />
        <Sparkles className="relative h-7 w-7 text-primary" />
      </div>
      <div className="flex items-center gap-1.5">
        {[0, 1, 2].map((i) => (
          <motion.span
            key={i}
            className="h-2 w-2 rounded-full bg-primary"
            animate={{ opacity: [0.3, 1, 0.3], y: [0, -3, 0] }}
            transition={{ duration: 0.9, repeat: Infinity, delay: i * 0.15 }}
          />
        ))}
      </div>
      <p className="text-sm font-medium text-muted-foreground">{label}</p>
    </motion.div>
  );
}

export default function LiveSessionPage() {
  const params = useParams();
  const sessionId = params.id as string;
  const { useNextQuestion, submitAnswer, completeSession } = useInterview();

  const { data, isLoading, isFetching, isError, refetch } = useNextQuestion(sessionId);
  const [answer, setAnswer] = useState('');
  const [answered, setAnswered] = useState(0);
  // Voice is the primary way to answer; typing is a fallback when the mic or
  // browser can't do speech recognition, so a candidate is never stuck.
  const [typing, setTyping] = useState(false);

  const stt = useSpeechRecognition();
  const tts = useSpeechSynthesis();

  /*
   * THE PANEL. Two interviewers rather than one voice reading questions.
   *
   * It wraps the question the orchestrator already chose — none of the adaptive selection,
   * per-session ownership or cross-question scoping changes. What it adds is who says it,
   * what they say to each other around it, and a correction on the spot when the last answer
   * was wrong.
   *
   * It also solves the "same question every time" complaint from the other direction: the
   * panel puts the question IN ITS OWN WORDS, so even a repeated question from the bank
   * arrives phrased differently, by a different person, with different framing.
   *
   * Everything here degrades: no panel turns means the bare question is shown and read by the
   * single voice, exactly as before. A presentation failure must not cost somebody their
   * interview.
   */
  // Same precedence the dashboard and the GD round use — profile name, then signup metadata,
  // then the email local part — reduced to something a person would say out loud.
  const { first: candidateName } = useCandidateName();
  const { data: interviewers } = useInterviewers();
  const { turn: panelTurn } = useInterviewPanel();
  const panelVoices = usePanelVoices(
    useMemo(
      () => (interviewers ?? []).map((i) => ({ name: i.name, gender: i.gender, stance: i.disposition })),
      [interviewers],
    ),
  );
  const [panelLines, setPanelLines] = useState<PanelLine[]>([]);
  //: True from the moment a question arrives until the panel either speaks or gives up. It
  //: is what stops the question text appearing seconds before the voice that says it.
  const [panelPending, setPanelPending] = useState(false);
  //: The question we have already run the panel for, so a re-render does not buy a second
  //: turn for the same question.
  const panelForRef = useRef<string | null>(null);
  // Track how long the candidate actually spoke this answer, for pace/delivery.
  const speakStartRef = useRef<number | null>(null);
  const speakSecondsRef = useRef(0);

  const question = data?.question ?? null;
  const isCoding = question?.type === 'coding';
  const questionText = question?.content;
  const useTyping = typing || !stt.supported;

  /**
   * Words a real panel would have heard you say and could not un-hear.
   *
   * Derived from `stt.transcript`, NOT from `answer`. Said is said — but only what
   * the recogniser actually heard: `answer` is an editable textarea, so deriving
   * this from it would put a permanent conduct flag on a student who typed a word
   * into the fallback box and deleted it before submitting. The transcript is the
   * panel's memory, and it is not user-editable.
   *
   * Reset per question, so it never leaks across answers.
   */
  const [sworn, setSworn] = useState<string[]>([]);
  useEffect(() => {
    const found = countUnprofessional(stt.transcript).words;
    if (!found.length) return;
    setSworn((prev) =>
      found.every((w) => prev.includes(w)) ? prev : [...new Set([...prev, ...found])],
    );
  }, [stt.transcript]);
  useEffect(() => {
    setSworn([]);
  }, [question?.id]);

  /**
   * Twelve seconds of the mic being open with the engine reporting no audio at all.
   *
   * Not "no words yet" — no SOUND. A candidate composing an answer in a quiet room
   * still trips soundstart on their own breathing long before this; a muted input
   * or a wrong device selected never does. Keying off the transcript instead would
   * fire on the normal path — a student thinking for seven seconds about
   * transaction propagation is not a hardware fault — and would tell them their
   * microphone is broken at the moment of maximum concentration.
   */
  const [micSilent, setMicSilent] = useState(false);
  useEffect(() => {
    if (!stt.listening || stt.error || stt.heardSound) {
      setMicSilent(false);
      return;
    }
    const t = setTimeout(() => setMicSilent(true), 12_000);
    return () => clearTimeout(t);
  }, [stt.listening, stt.error, stt.heardSound]);

  // Show the generating animation while the next question is being prepared
  // (initial load, refetch after submit, or a live cross-question being built).
  const preparing = isLoading || (isFetching && !question) || submitAnswer.isPending;

  /**
   * HANDS-FREE. The mic opens itself when the interviewer stops talking, and closes
   * itself when the candidate stops.
   *
   * In a real interview nobody presses anything: the panel finishes their question
   * and you answer. Tapping a button before and after every answer is the single
   * biggest thing standing between this and a real room, and it also breaks the
   * illusion at the worst moment — right when the candidate should be thinking about
   * Spring transaction propagation, they are thinking about a UI control.
   *
   * Opt-out rather than opt-in, because the point is that you forget it exists. The
   * button still works and still stops it — an explicit stop pins the mic closed
   * until the next question, so a candidate who wants manual control gets it by
   * using it.
   */
  const [handsFree, setHandsFree] = useState(true);
  //: The open/close actions, held in refs so the hands-free effects can call them
  //: without listing them as dependencies — `answer` is in their closure and would
  //: otherwise re-run the arming effect on every transcribed word.
  const openMicRef = useRef<(() => void) | null>(null);
  const closeMicRef = useRef<(() => void) | null>(null);
  //: Set when the candidate stops the mic themselves. Cleared on a new question, so
  //: opting out is per-answer rather than a mode they have to remember to undo.
  const pinnedClosedRef = useRef(false);
  //: The question we have already auto-opened for, so re-renders do not re-open a
  //: mic the candidate has deliberately closed.
  const armedForRef = useRef<string | null>(null);

  useEffect(() => {
    pinnedClosedRef.current = false;
    armedForRef.current = null;
  }, [question?.id]);

  useEffect(() => {
    if (!handsFree || useTyping || preparing) return;
    if (!question?.id || !stt.supported) return;
    // Wait for the interviewer to finish. Opening the mic while TTS is still
    // playing means the question gets transcribed into the answer.
    // Wait for whoever is actually talking — the panel when it is in use, the single voice
    // otherwise. Opening the mic while either is mid-sentence transcribes the interviewer
    // into the candidate's answer.
    if (tts.speaking || panelVoices.speakingNow || panelVoices.takingFloor) return;
    if (stt.listening || stt.error) return;
    if (pinnedClosedRef.current || armedForRef.current === question.id) return;
    armedForRef.current = question.id;
    // A beat after they stop, the way you do not start talking the instant someone's
    // last word lands.
    const t = setTimeout(() => {
      if (pinnedClosedRef.current) return;
      openMicRef.current?.();
    }, 550);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handsFree, useTyping, preparing, question?.id, tts.speaking, panelVoices.speakingNow, panelVoices.takingFloor, stt.supported, stt.listening, stt.error]);

  /**
   * END OF ANSWER. Sustained silence after they have actually said something.
   *
   * Deliberately long: 4.5s is well past a thinking pause mid-answer, and the cost
   * of being wrong is asymmetric — closing early truncates an answer, closing late
   * costs nothing because the transcript is still theirs to submit. The mic closing
   * is also NOT a submit: the candidate still reviews and sends, because auto-sending
   * a possibly-mistranscribed answer is not something to do on someone's behalf.
   */
  useEffect(() => {
    if (!handsFree || !stt.listening || !answer.trim()) return;
    const t = setTimeout(() => {
      closeMicRef.current?.();
    }, 4500);
    return () => clearTimeout(t);
    // `answer` in the deps is the point — every new word restarts the timer.
  }, [handsFree, stt.listening, answer]);

  // Read each new question aloud (voice-first feel) unless typing. Coding
  // questions are read too — a real interviewer states the problem out loud,
  // and they were previously the one type left silent.
  useEffect(() => {
    if (!questionText || !question?.id || useTyping) return;
    if (panelForRef.current === question.id) return;
    panelForRef.current = question.id;
    setPanelLines([]);
    setPanelPending(true);

    void (async () => {
      const result = await panelTurn.mutateAsync({
        session_id: sessionId,
        // The first question is a greeting and introductions; everything after is normal
        // flow, where a wrong previous answer gets corrected before the next question.
        stage: answered === 0 ? 'opening' : 'mid',
        question: questionText,
        candidate_name: candidateName,
      });

      setPanelPending(false);
      if (result.turns.length) {
        // Reveal each line AS ITS VOICE STARTS, not all at once — the same lesson the GD
        // round taught. Showing both lines immediately and then speaking them in sequence
        // means the candidate reads the second interviewer while the first is still talking.
        for (const line of result.turns) {
          await panelVoices.speakAs(line.speaker, line.text, {
            onStart: () => setPanelLines((prev) => [...prev, line]),
            // Tagged by the panel itself, per line. This is what makes a correction sound
            // like one — slower and lower — instead of being read out in the same voice as
            // the greeting, which was the giveaway that nobody was really in the room.
            tone: line.tone,
          });
        }
        return;
      }

      // No panel — provider down, or it returned nothing usable. Fall back to the single
      // voice reading the question, which is exactly the old behaviour.
      if (tts.supported) tts.speak(questionText);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [questionText, question?.id, useTyping]);

  useEffect(() => {
    if (stt.transcript) setAnswer(stt.transcript);
  }, [stt.transcript]);

  const closeMic = () => {
    stt.stop();
    if (speakStartRef.current) {
      speakSecondsRef.current += (Date.now() - speakStartRef.current) / 1000;
      speakStartRef.current = null;
    }
  };

  const openMic = () => {
    if (!answer) {
      stt.reset();
      speakSecondsRef.current = 0;
    }
    speakStartRef.current = Date.now();
    stt.start();
  };
  openMicRef.current = openMic;
  closeMicRef.current = closeMic;

  /** The button. An explicit stop also pins the mic closed for this question. */
  const toggleMic = () => {
    if (stt.listening) {
      // Deliberate: the candidate reaching for the button to stop is them asking for
      // manual control, so hands-free does not immediately re-open it. Cleared when
      // the next question arrives, so they never have to undo a mode.
      pinnedClosedRef.current = true;
      closeMic();
    } else {
      pinnedClosedRef.current = false;
      openMic();
    }
  };

  // Submit the answer, then immediately advance to the next question — no
  // per-question score is shown (all scoring appears at the end in the report).
  const submitContent = (content: string) => {
    if (!content.trim() || !question) return;
    stt.stop();
    tts.cancel();
    if (speakStartRef.current) {
      speakSecondsRef.current += (Date.now() - speakStartRef.current) / 1000;
      speakStartRef.current = null;
    }

    // Delivery metrics for the end-of-interview report (skip for coding, where
    // "speaking" doesn't apply).
    const seconds = Math.max(1, Math.round(speakSecondsRef.current));
    const summary = summarizeDelivery({ text: content, seconds, pauses: stt.pauses });
    const delivery = isCoding
      ? undefined
      : {
          filler_count: summary.fillerCount,
          // Everything the panel heard across this answer, including anything the
          // candidate later edited out of the textarea. One occurrence is a real
          // event with a real cost, unlike a filler, which is a habit.
          unprofessional_count: sworn.length,
          unprofessional_words: sworn,
          pause_count: summary.pauseCount,
          total_pause_seconds: summary.totalPauseSec,
          words: summary.words,
          speaking_seconds: seconds,
          // The individual pauses, not just the count. The detailed analysis
          // replays the answer with hesitations marked in position, which a
          // total cannot reconstruct — and this is the only moment the
          // positions exist, so dropping them here loses them for good.
          pauses: stt.pauses,
        };

    submitAnswer.mutate(
      { sessionId, questionId: question.id, content, delivery },
      {
        onSuccess: (res) => {
          setAnswered(res.questions_answered);
          setAnswer('');
          stt.reset();
          speakSecondsRef.current = 0;
          refetch();
        },
        onError: (err: Error) => {
          toast.error(err.message || 'Failed to submit answer. Please try again.');
        },
      }
    );
  };

  const handleSubmit = () => submitContent(answer);

  // ─── Loading / preparing ──────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <GeneratingQuestion label="Preparing your first question…" />
      </div>
    );
  }

  // ─── Network / server error — clean retry, no console/toast storm ─────────
  if (isError) {
    return (
      <div className="hero-wash flex min-h-screen items-center justify-center bg-background p-6">
        <motion.div
          initial="hidden"
          animate="visible"
          variants={scalePop}
          className="glass max-w-md rounded-2xl border-border/50 p-6 text-center sm:p-10"
        >
          <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-destructive/10">
            <WifiOff className="h-7 w-7 text-destructive" />
          </div>
          <h2 className="mb-3 text-xl font-semibold">Connection hiccup</h2>
          <p className="mb-8 text-sm leading-relaxed text-muted-foreground">
            We couldn&apos;t load the next question. Your progress is saved — just try again.
          </p>
          <Button className="w-full" onClick={() => refetch()}>
            <RefreshCw className="h-4 w-4" /> Retry
          </Button>
        </motion.div>
      </div>
    );
  }

  // ─── Interview complete ───────────────────────────────────────────────────
  if (question === null && !preparing) {
    return (
      <div className="hero-wash flex min-h-screen items-center justify-center bg-background p-6">
        <motion.div
          initial="hidden"
          animate="visible"
          variants={scalePop}
          className="glass max-w-md rounded-2xl border-border/50 p-6 text-center sm:p-10"
        >
          <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10">
            <Sparkles className="h-7 w-7 text-primary" />
          </div>
          <h2 className="mb-3 text-xl font-semibold sm:text-2xl">Interview Complete</h2>
          <p className="mb-8 text-sm leading-relaxed text-muted-foreground">
            Nicely done{answered ? ` — you answered ${answered} question${answered === 1 ? '' : 's'}` : ''}.
            We&apos;ll now score every answer and build your full report.
          </p>
          <Button
            className="w-full"
            onClick={() => completeSession.mutate(sessionId)}
            loading={completeSession.isPending}
          >
            View Final Report
          </Button>
        </motion.div>
      </div>
    );
  }

  const wordCount = answer.trim() ? answer.trim().split(/\s+/).length : 0;

  return (
    <div className="flex min-h-screen flex-col bg-background">
      {/* Header */}
      <header className="flex h-16 items-center justify-between border-b border-border/50 bg-surface/60 px-6 backdrop-blur-md">
        <div className="flex items-center gap-3">
          <span className="relative flex h-2.5 w-2.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent-coral opacity-60" />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-accent-coral" />
          </span>
          <span className="text-sm font-semibold tracking-tight">Live Interview Session</span>
          {answered > 0 && (
            <span className="ml-1 rounded-full bg-surface-elevated px-2.5 py-0.5 text-xs font-medium text-muted-foreground">
              {answered} answered
            </span>
          )}
        </div>
        <button
          onClick={() => completeSession.mutate(sessionId)}
          className="flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs font-medium text-destructive transition-colors hover:bg-destructive/10"
        >
          <StopCircle className="h-4 w-4" /> End Interview
        </button>
      </header>

      {/* Main workspace */}
      <motion.main
        initial="hidden"
        animate="visible"
        variants={staggerContainer(0.1)}
        className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-4 p-4 sm:gap-6 sm:p-6 md:flex-row"
      >
        {/* Left: Question Area */}
        <motion.div variants={fadeUp} className="flex flex-1 flex-col gap-6">
          <div className="glass flex h-full flex-col rounded-2xl border-border/50 p-5 sm:p-8">
            <AnimatePresence mode="wait">
              {preparing ? (
                <GeneratingQuestion key="gen" label="Thinking about your next question…" />
              ) : (
                <motion.div
                  key={question?.id}
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -8 }}
                  transition={{ duration: 0.35 }}
                >
                  <div className="mb-5 flex items-center gap-2">
                    <Badge variant="primary">Question</Badge>
                    {question?.difficulty && (
                      <span className={`badge-${question.difficulty}`}>{question.difficulty}</span>
                    )}
                  </div>

                  {panelLines.length > 0 ? (
                    /* The panel talking. Each line is attributed, and the one being spoken
                       is ringed so the text and the voice are visibly the same person. */
                    <div className="space-y-3">
                      {panelLines.map((line, i) => {
                        const speaking =
                          panelVoices.speakingNow === line.speaker && i === panelLines.length - 1;
                        return (
                          <motion.div
                            key={`${line.speaker}-${i}`}
                            initial={{ opacity: 0, y: 6 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ duration: 0.25 }}
                            className={cn(
                              'rounded-xl border px-4 py-3 transition-shadow',
                              speaking
                                ? 'border-primary/40 bg-primary/5 ring-1 ring-primary/30'
                                : 'border-border/50 bg-surface/40',
                            )}
                          >
                            <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                              {line.speaker}
                              {interviewers?.find((iv) => iv.name === line.speaker)?.role && (
                                <span className="ml-2 font-normal normal-case tracking-normal opacity-70">
                                  {interviewers.find((iv) => iv.name === line.speaker)?.role}
                                </span>
                              )}
                            </p>
                            <p className="text-base leading-relaxed sm:text-lg">{line.text}</p>
                          </motion.div>
                        );
                      })}
                    </div>
                  ) : panelPending ? (
                    /*
                     * THE LAG YOU FELT. The bare question used to render the instant it
                     * arrived, while the panel's voice was still two to four seconds behind
                     * it — so you read the question, then heard it, and the room was always
                     * a beat behind the screen.
                     *
                     * While the panel is being written we show that somebody is about to
                     * speak instead of showing the words. Text and voice then land together,
                     * which is what makes it feel like a room rather than a page with audio
                     * bolted on. If the panel fails, the branch below still shows the
                     * question — nobody is ever left with nothing.
                     */
                    <div className="flex items-center gap-2.5 py-2 text-sm text-muted-foreground">
                      <span className="flex gap-1" aria-hidden>
                        {[0, 0.18, 0.36].map((d) => (
                          <motion.span
                            key={d}
                            className="h-1.5 w-1.5 rounded-full bg-muted-foreground/60"
                            animate={{ opacity: [0.25, 1, 0.25] }}
                            transition={{ duration: 1.1, repeat: Infinity, delay: d }}
                          />
                        ))}
                      </span>
                      The panel is talking…
                    </div>
                  ) : (
                    <h1 className="text-lg font-semibold leading-relaxed tracking-[-0.01em] sm:text-2xl">
                      {question?.content}
                    </h1>
                  )}
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          {/* Optional live presence check (camera + mic, on-device only) */}
          <PresenceMonitor />
        </motion.div>

        {/* Right: Answer Area */}
        <motion.div
          variants={fadeUp}
          className="glass flex flex-1 flex-col rounded-2xl border-border/50 p-6"
        >
          <div className="mb-4 flex items-center justify-between">
            <span className="text-sm font-semibold text-muted-foreground">
              {isCoding ? 'Your Solution' : 'Your Answer'}
            </span>
            <div className="flex items-center gap-2">
              {isCoding && <Badge variant="violet">Coding round</Badge>}
              {/* No "Hear question" button and no voice-name strip.
                  Both were from when a single synthetic voice read the question and the
                  candidate might reasonably want to replay it or check which voice they had
                  been given. The panel talks on its own, in two voices, and a button offering
                  to re-read "the question" has nothing to point at — the question is now
                  something Priya said, in her own words, in the middle of a conversation.
                  Naming the browser voice was worse: it announced the machinery. */}
            </div>
          </div>

          {isCoding ? (
            <CodingWorkspace
              disabled={preparing}
              submitting={submitAnswer.isPending}
              problemTitle="Coding question"
              problemDescription={question?.content ?? ''}
              difficulty={question?.difficulty ?? 'medium'}
              onSubmit={({ language, code }: { language: CodeLanguage; code: string }) =>
                submitContent(`\`\`\`${language}\n${code}\n\`\`\``)
              }
            />
          ) : useTyping ? (
            /* Typing fallback */
            <>
              <textarea
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                disabled={preparing}
                placeholder="Type your answer here as if you were speaking to an interviewer…"
                className="ease-out-expo w-full flex-1 resize-none rounded-xl border border-border/50 bg-surface-elevated p-4 text-sm leading-relaxed transition-shadow focus:border-primary/40 focus:shadow-glow focus:outline-none"
              />
              <div className="mt-3 flex items-center justify-between gap-3">
                <span className="text-xs text-muted-foreground/70">
                  {wordCount} {wordCount === 1 ? 'word' : 'words'}
                </span>
                <div className="flex items-center gap-3">
                  {stt.supported && (
                    <button
                      onClick={() => setTyping(false)}
                      className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                    >
                      Use voice instead
                    </button>
                  )}
                  <Button onClick={handleSubmit} disabled={preparing || !answer.trim()} loading={submitAnswer.isPending}>
                    <Send className="h-4 w-4" /> Submit &amp; Next
                  </Button>
                </div>
              </div>
            </>
          ) : (
            /* Voice-first answer UI */
            <div className="flex flex-1 flex-col items-center justify-center gap-5 py-4">
              {/* A real interviewer says "we can't hear you." The hook has always
                  classified permission and hardware failures into candidate-ready
                  English and nothing rendered it, so a blocked mic looked exactly
                  like a working one that heard nothing. */}
              {(stt.error || micSilent) && (
                <div
                  role="alert"
                  className={cn(
                    'flex w-full items-start gap-2.5 rounded-xl border px-3.5 py-2.5 text-left text-xs leading-relaxed',
                    stt.error
                      ? 'border-destructive/40 bg-destructive/10 text-destructive'
                      : 'border-accent-amber/40 bg-accent-amber/10 text-accent-amber-ink'
                  )}
                >
                  <MicOff className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
                  <span className="flex-1">
                    {stt.error ??
                      'We are not picking up any audio yet. If you have started speaking, your system input may be muted or the wrong microphone may be selected.'}{' '}
                    <button
                      onClick={() => {
                        stt.stop();
                        setTyping(true);
                      }}
                      className="font-semibold underline underline-offset-2"
                    >
                      Type this answer instead
                    </button>
                  </span>
                </div>
              )}

              <button
                onClick={toggleMic}
                disabled={preparing}
                aria-label={stt.listening ? 'Stop recording' : 'Start recording'}
                className={cn(
                  'relative flex h-20 w-20 items-center justify-center rounded-full transition-[color,background-color,border-color,box-shadow,transform,opacity] disabled:opacity-50 sm:h-24 sm:w-24',
                  // Deliberately NOT disabled on error. `error` is only cleared by
                  // start() or reset(), and start() is only reachable through this
                  // button — so disabling it removes the exact recovery Chrome
                  // expects: click the padlock, allow the mic, tap again.
                  stt.listening
                    ? 'bg-destructive text-destructive-foreground shadow-glow'
                    : stt.error
                      ? 'bg-surface-elevated text-muted-foreground ring-1 ring-destructive/40'
                      : 'bg-primary text-primary-foreground shadow-glow hover:shadow-glow-lg'
                )}
              >
                {stt.listening && (
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-destructive opacity-40" />
                )}
                {stt.listening ? <MicOff className="h-7 w-7 sm:h-9 sm:w-9" /> : <Mic className="h-7 w-7 sm:h-9 sm:w-9" />}
              </button>

              <p className="text-sm font-medium text-muted-foreground">
                {stt.error
                  ? 'Fix the permission, then tap to try again'
                  : stt.listening
                    ? handsFree
                      ? 'Listening — just talk. It stops when you do.'
                      : 'Listening… tap to stop'
                    : tts.speaking && handsFree
                      ? 'Let them finish…'
                      : answer
                        ? handsFree
                          ? 'Done. Review it and submit, or start talking again.'
                          : 'Tap the mic to add more, or submit'
                        : handsFree
                          ? 'The mic opens on its own — start speaking'
                          : 'Tap the mic and speak your answer'}
              </p>

              {/* Legible, not silent. A mic that opens by itself is unnerving if the
                  candidate cannot see that it is meant to. */}
              {stt.supported && (
                <button
                  onClick={() => {
                    setHandsFree((on) => !on);
                    if (handsFree && stt.listening) {
                      pinnedClosedRef.current = true;
                      closeMic();
                    }
                  }}
                  className={cn(
                    'inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[11px] font-semibold transition-colors',
                    handsFree
                      ? 'border-primary/40 bg-primary/10 text-primary'
                      : 'border-border text-muted-foreground hover:text-foreground'
                  )}
                >
                  <span
                    className={cn(
                      'h-1.5 w-1.5 rounded-full',
                      handsFree ? 'bg-primary' : 'bg-muted-foreground/50'
                    )}
                  />
                  Hands-free {handsFree ? 'on' : 'off'}
                </button>
              )}

              {/* Said is said. Stays up for the rest of the question even after the
                  candidate edits the word out, because a panel cannot un-hear it. */}
              {sworn.length > 0 && (
                <div
                  role="status"
                  className="flex w-full items-start gap-2.5 rounded-xl border border-destructive/40 bg-destructive/10 px-3.5 py-2.5 text-left text-xs leading-relaxed text-destructive"
                >
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
                  <span className="flex-1">
                    <span className="font-semibold">Flagged:</span> you said
                    {' '}
                    {sworn.map((w, i) => (
                      <span key={w}>
                        {i > 0 && ', '}
                        <span className="font-semibold">&ldquo;{w}&rdquo;</span>
                      </span>
                    ))}
                    . In a real panel that lands in the notes — it goes in your report.
                  </span>
                </div>
              )}

              {/* Live transcript — filler words in red, pauses marked */}
              <div className="min-h-[96px] w-full flex-1 overflow-y-auto rounded-xl border border-border/50 bg-surface-elevated p-4 text-sm leading-relaxed">
                <DeliveryTranscript
                  text={answer}
                  pauses={stt.pauses}
                  interim={stt.listening ? stt.interim : ''}
                />
              </div>

              <div className="flex w-full items-center justify-between gap-3">
                {/* Suppressed while the banner is up: two escape hatches four
                    inches apart read as panic, not help. */}
                {!stt.error && !micSilent ? (
                  <button
                    onClick={() => {
                      stt.stop();
                      setTyping(true);
                    }}
                    className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                  >
                    Trouble with the mic? Type instead
                  </button>
                ) : (
                  <span />
                )}
                <div className="flex items-center gap-2">
                  {answer && !submitAnswer.isPending && (
                    <button
                      onClick={() => {
                        setAnswer('');
                        stt.reset();
                      }}
                      className="rounded-lg border border-border px-3 py-2 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
                    >
                      Clear
                    </button>
                  )}
                  <Button onClick={handleSubmit} disabled={preparing || !answer.trim()} loading={submitAnswer.isPending}>
                    <Send className="h-4 w-4" /> Submit &amp; Next
                  </Button>
                </div>
              </div>
            </div>
          )}
        </motion.div>
      </motion.main>
    </div>
  );
}
