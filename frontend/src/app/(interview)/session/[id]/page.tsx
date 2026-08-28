'use client';

import { useInterview } from '@/hooks/useInterview';
import { useBalance } from '@/hooks/useBilling';
import { useLeaveGuard } from '@/hooks/useLeaveGuard';
import { useParams } from 'next/navigation';
import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { AlertTriangle, Code2, MessageSquare, Mic, MicOff, RefreshCw, Send, Sparkles, StopCircle, Video, WifiOff } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { StarRating } from '@/components/ui/star-rating';
import { CodingWorkspace } from '@/components/interview/CodingWorkspace';
import { PresenceMonitor } from '@/components/interview/PresenceMonitor';
import { DeliveryTranscript } from '@/components/interview/DeliveryTranscript';
import type { CodeLanguage } from '@/hooks/useCode';
import { useSpeechRecognition, useSpeechSynthesis, usePanelVoices } from '@/hooks/useSpeech';
import { useCandidateName } from '@/hooks/useCandidateName';
import { useConnection, isNetworkError } from '@/hooks/useConnection';
import {
  useInterviewPanel,
  useInterviewers,
  useRecordPivot,
  useSelfRating,
  type PanelLine,
  type PanelStage,
} from '@/hooks/useInterviewPanel';
import { PanelThread } from '@/components/interview/PanelThread';
import { parseSelfRating } from '@/lib/interview/self-rating';
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

      {/* DO NOT CLOSE THIS, SAID WHILE IT MATTERS.
          The question is being generated server-side against this session, and a candidate who
          reads a spinner as "stuck" and reloads or closes the tab loses their place in an
          interview they get one attempt at. The sentence is only shown here — during the wait
          — because a standing warning on a page that is working is noise people learn to
          ignore, and then do not read on the one screen where it counts.

          Deliberately calm and specific about the duration. "Do not close" on its own reads as
          a threat and makes people anxious at exactly the wrong moment; naming a few seconds
          tells them the wait is normal and finite, which is what actually stops the reload. */}
      <p className="max-w-sm text-xs leading-relaxed text-muted-foreground/80">
        Please keep this screen open — your next question is being prepared and usually takes a
        few seconds. Closing or reloading now would interrupt the interview.
      </p>
    </motion.div>
  );
}

export default function LiveSessionPage() {
  const params = useParams();
  const sessionId = params.id as string;
  const { useNextQuestion, submitAnswer, completeSession, rateInterview } = useInterview();
  //: The star rating on the completion card. Zero means not yet chosen, which is what
  //: disables the button — see the card itself for why the SAVE is not on that path.
  const [stars, setStars] = useState(0);

  const { data, isLoading, isFetching, isError, refetch } = useNextQuestion(sessionId);

  /*
   * THE CONNECTION. Reported: "if the device goes offline then the interview must give the
   * warning of the internet connection and also the session must go on or it must resume from
   * theri as it was earlier... the interview must not start from the starting."
   *
   * RESUMING IS ALREADY CORRECT AND THAT IS THE POINT. The interview's position lives
   * server-side: the plan is in the session row and `/next` returns the question the candidate
   * has not answered yet. So a drop cannot lose the candidate's place, and reconnecting is a
   * re-fetch, not a restart. What was missing was everything around it — no warning, a
   * microphone that stayed armed against a recogniser it could not reach, and a query layer
   * that surfaced the outage as an interview error.
   *
   * So this hook is only asked whether the connection works. What to do about it is decided
   * here, where it is known which actions are safe.
   */
  const connection = useConnection();

  /*
   * COME BACK TO THE SAME QUESTION.
   *
   * On reconnect, re-fetch rather than assume. The client's copy of "the current question" was
   * correct when the connection dropped, but an answer submitted from another tab — or one
   * that reached the server and whose RESPONSE was lost, which is the ordinary case for a drop
   * mid-submit — means the server has moved on. Re-fetching is how the two agree again, and it
   * is also what makes a lost-response submit resolve correctly instead of asking the candidate
   * the same question twice.
   */
  const wasOfflineRef = useRef(false);
  useEffect(() => {
    if (!connection.online) {
      wasOfflineRef.current = true;
      return;
    }
    if (!wasOfflineRef.current) return;
    wasOfflineRef.current = false;
    void refetch();
  }, [connection.online, refetch]);

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
  // Session-scoped: the designations follow the role, so a sales candidate sees a Regional
  // Sales Manager rather than a Senior Engineering Manager.
  const { data: panelInfo, isLoading: panelInfoLoading } = useInterviewers(sessionId);
  const interviewers = panelInfo?.interviewers;
  /*
   * IS THERE A CODE EDITOR AT ALL?
   *
   * Resolved from the role, not from the question type. A sales or HR interview never needs
   * one, and a permanent editor in a sales round is not neutral clutter — it says the
   * simulation has not understood what job the candidate applied for, which is the same
   * class of mistake as asking them to rate themselves in Java.
   *
   * Defaults to true while the roster is still loading, and true for any role the domain
   * classifier does not recognise: a missing editor costs a technical candidate the
   * question, a spurious one costs everybody else a glance.
   */
  const hasEditor = panelInfo?.technical ?? true;
  const { turn: panelTurn } = useInterviewPanel();
  const panelVoices = usePanelVoices(
    useMemo(
      () => (interviewers ?? []).map((i) => ({ name: i.name, gender: i.gender, stance: i.disposition })),
      [interviewers],
    ),
  );
  /*
   * THE LIVE PANEL VOICES, read through a ref rather than captured.
   *
   * `speakTurn` is a useCallback on [sessionId, candidateName], and it called
   * `panelVoices.speakAs` directly — capturing the `panelVoices` object from the render that
   * created it. But `speakAs` is itself `useCallback(…, [voiceMap, stanceOf])`, and BOTH
   * settle asynchronously after mount: `stanceOf` when the interviewers query resolves, and
   * `voiceMap` when the browser's voice list arrives (`voiceschanged` is famously late, and
   * on Safari it fires more than once).
   *
   * So speakTurn held the FIRST speakAs — the one built when the voice map was still empty —
   * and every line of every turn went out through it. On the browser-speech path that means
   * Anil and Priya both speak in the single default voice at identical pitch and rate, which
   * is exactly the "the voices are so bad" and "Meera has a male voice" reports: the voice
   * allocation was working and nothing was reading it.
   *
   * A ref is read at CALL time, so the current speakAs is always the one used.
   */
  const voicesRef = useRef(panelVoices);
  voicesRef.current = panelVoices;

  const [panelLines, setPanelLines] = useState<PanelLine[]>([]);
  //: True from the moment a question arrives until the panel either speaks or gives up. It
  //: is what stops the question text appearing seconds before the voice that says it.
  const [panelPending, setPanelPending] = useState(false);
  /*
   * IS THE PANEL TALKING? One signal, for the WHOLE turn.
   *
   * THIS IS THE BUG THAT PUT THE INTERVIEWER'S VOICE IN THE CANDIDATE'S ANSWER. The mic used
   * to wait on `speakingNow || takingFloor`, and both of those are PER-UTTERANCE: speakAs
   * sets speakingNow back to null the moment one line finishes, and the next line's
   * takingFloor is not set until the chained promise resumes and React re-renders. In that
   * window — with a two- or three-line turn, there are two of them — nobody appeared to be
   * talking, the mic armed, and Priya's next sentence went straight into the answer box. It
   * is visible in the transcript as her own words, mangled by the recogniser: "you keep the
   * feels private and only allow access through public catchers".
   *
   * A turn-level flag cannot have that gap, because it is set once before the first line and
   * cleared once after the last. The per-utterance signals are still exactly right for the
   * UI — the ring around whoever is speaking — and are still used there. They were only ever
   * wrong as a microphone interlock.
   */
  const [panelBusy, setPanelBusy] = useState(false);
  //: The same flag, readable from inside a timeout that was scheduled before it changed.
  //: State is captured by the closure; this is not.
  const panelBusyRef = useRef(false);
  panelBusyRef.current = panelBusy;
  //: Clears the answer box and the recogniser's own buffer. Held in a ref for the same
  //: reason the mic actions are: `answer` is in its closure and listing it as a dependency
  //: would rebuild speakTurn on every transcribed word.
  const resetAnswerRef = useRef<(() => void) | null>(null);
  //: The question we have already run the panel for, so a re-render does not buy a second
  //: turn for the same question.
  const panelForRef = useRef<string | null>(null);

  /*
   * WHERE THE INTERVIEW IS. The conversational spine of the redesign.
   *
   * It used to be implicit: there was a question, you answered it, there was another
   * question. That is a questionnaire. A real panel opens by asking what you are good at,
   * moves you off a topic you cannot do, reads your code back to you, and at the end asks
   * whether YOU have anything to ask THEM — and none of those fit "current question".
   *
   *   skill_check  the opening exchange: rate yourself, name your strong areas
   *   asking       normal flow — question, answer, correction
   *   pivot        they declined; the panel has offered another topic and is waiting
   *   reviewing    they submitted code and the panel is reading it
   *   closing      wrap-up, then "any questions for us?", then the answer to it
   *
   * EVERY ONE OF THESE HAS AN ESCAPE. A candidate must never be unable to reach their
   * report because a closing turn failed or the provider went down mid-sentence — the End
   * Interview control in the header is always live, and every phase below falls through to
   * the next on any error rather than waiting.
   */
  type Phase = 'skill_check' | 'asking' | 'pivot' | 'reviewing' | 'closing' | 'done';
  const [phase, setPhase] = useState<Phase>('skill_check');
  /*
   * LEAVING NOW COSTS THEM THE ATTEMPT, so say so.
   *
   * The interview is already spent the moment it starts — the charge is taken up front and the
   * session cannot be resumed — so a candidate who closes the tab, reloads, or switches to
   * another app to look something up loses the whole thing. Most of them have no idea; the
   * common one is reloading because a question is taking a few seconds and the page looks
   * stuck, which is precisely the moment the warning has to exist.
   *
   * Armed only while there is something to lose: not on the loading screen, not on the
   * completed screen, and never on the report. A guard that fires on a finished interview
   * teaches people to click through it.
   */
  const balance = useBalance();
  const leave = useLeaveGuard(phase !== 'done');

  /*
   * IS THIS ATTEMPT FREE? Asked so the warning can be TRUE rather than merely alarming.
   *
   * "Your free interview will be wasted" is exactly right for a candidate on the trial and
   * simply wrong for one who bought a five-pack — telling a paying customer they are losing
   * something free reads as the product not knowing what they paid. `trial_allowance` comes
   * from the server precisely so this is not a guess: if everything consumed so far still
   * falls inside the trial, this attempt came out of it.
   */
  const interviewBalance = balance.data?.features?.find((f) => f.feature === 'interview');
  const isFreeAttempt =
    !!interviewBalance && interviewBalance.used <= interviewBalance.trial_allowance;

  //: Which pane is showing on a phone. Three columns do not fit on 375px and this product's
  //: users are overwhelmingly phone-first, so below lg they become tabs rather than a stack —
  //: stacked, the compiler would sit two screens below the question it belongs to.
  const [mobilePane, setMobilePane] = useState<'talk' | 'code' | 'you'>('talk');
  //: If the roster arrives after the candidate has already tapped Compiler — it defaults to
  //: available while loading — they would be left looking at a pane that no longer exists.
  useEffect(() => {
    if (!hasEditor && mobilePane === 'code') setMobilePane('talk');
  }, [hasEditor, mobilePane]);

  //: The topic the panel offered after a decline, so a "yes" can be acted on.
  const [pivotOffer, setPivotOffer] = useState<{ topic: string; declined: string } | null>(null);
  //: What the panel asked them to rate themselves on — "Java" for a Java role, "Sales &
  //: Business Development" for a sales one. Recorded with the number so the report knows
  //: which subject a bare 7 refers to.
  const [ratingSubject, setRatingSubject] = useState('');
  //: Which language the compiler is set to. Lifted out of CodingWorkspace so a code review
  //: can say which language it is reading — "this is Java" changes what counts as a mistake.
  const [codeLanguage, setCodeLanguage] = useState<CodeLanguage>('java');
  /*
   * The camera's verdict, mirrored up out of PresenceMonitor.
   *
   * Below lg the video is behind a tab, so a warning rendered inside it is a warning nobody
   * sees — which is worse than not detecting at all, because it looks like it is working.
   * This badges the tab and drives the banner below, so the alert reaches the candidate
   * wherever they happen to be looking.
   */
  const [presence, setPresence] = useState({
    multiplePeople: false,
    multiplePeopleEver: false,
    candidateAbsent: false,
  });
  //: Set once the closing sequence has run, so it cannot run twice.
  const closedRef = useRef(false);
  const [closingQuestion, setClosingQuestion] = useState('');
  const [answeringClosing, setAnsweringClosing] = useState(false);
  const selfRating = useSelfRating(sessionId);
  const recordPivot = useRecordPivot(sessionId);

  // Track how long the candidate actually spoke this answer, for pace/delivery.
  const speakStartRef = useRef<number | null>(null);
  const speakSecondsRef = useRef(0);

  const question = data?.question ?? null;
  const isCoding = question?.type === 'coding';
  const questionText = question?.content;
  const useTyping = typing || !stt.supported;

  /*
   * WHAT THE INTERVIEWER ACTUALLY ASKED, in their words.
   *
   * Reported as "i cannot see the real question asked by the interviewer", alongside a
   * complaint that the question appears on screen every time. Both describe the same thing.
   *
   * `questionText` is the PLANNED question — the row the orchestrator chose, phrased for a
   * bank. The panel does not read it out; it asks the question in its own words, in the middle
   * of a conversation ("Okay — so you've got a dealer threatening to walk over margin. What do
   * you actually do on Monday?"). The pinned block showed the bank row, so the candidate was
   * looking at a second, differently-worded copy of a question they had just been asked, which
   * reads as the same question arriving twice.
   *
   * So: pin the line the panel actually spoke. Found by walking BACK for the most recent
   * `asking` line, because a turn can end on an aside or a correction and the question is not
   * necessarily last. Falls back to the planned text, which is the right fallback and not
   * merely a safe one — when the panel could not speak, the planned text IS what the candidate
   * was shown.
   */
  const askedAloud = useMemo(() => {
    for (let i = panelLines.length - 1; i >= 0; i--) {
      if (panelLines[i].tone === 'asking' && panelLines[i].text.trim()) return panelLines[i];
    }
    return null;
  }, [panelLines]);
  const pinnedQuestion = askedAloud?.text ?? questionText;

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
    // PHASE AS WELL AS QUESTION, and this was the other half of the same bug. The guard is
    // keyed on "have we already armed for this?", and it used to mean "for this question" —
    // so the skill check consumed the one arming that belonged to question one, and the mic
    // never opened for the question itself. Every phase that takes speech gets its own.
  }, [question?.id, phase]);

  useEffect(() => {
    if (!handsFree || useTyping || preparing) return;
    /*
     * ONLY WHILE A QUESTION IS ACTUALLY OPEN.
     *
     * The redesign put four more panel turns between questions — the skill check, the
     * pivot, the code review and the close — and every one of them is the panel talking
     * for several seconds. Without this gate the mic arms during a code review and
     * transcribes Anil reading the candidate's own code back to them straight into the
     * next answer.
     *
     * `pivot` and `closing` also have their own on-screen controls (two buttons, a text
     * box), which is deliberate: a spoken "yes" is indistinguishable from the start of an
     * answer to a recogniser, so those moments are not voice moments at all.
     *
     * `skill_check` IS a voice moment and is allowed through — the panel asks the rating out
     * loud and the candidate is supposed to say it back. parseSelfRating reads the number
     * out of the transcript; the buttons on screen are the fallback for when it cannot.
     */
    if (phase !== 'asking' && phase !== 'skill_check') return;
    /*
     * NOT ON A CODING QUESTION. The editor is the answer channel, not the microphone.
     *
     * The mic used to arm anyway, so a candidate sat with an open microphone that was
     * recording them muttering while they wrote code — and whatever it caught became their
     * "answer" alongside the code. There is nothing for it to hear on a coding question:
     * the panel asked them to write something, and the thing they write is in the editor.
     *
     * DURING `asking` ONLY, and that qualifier is the whole fix for "it cannot detect the
     * answer to how would you rate yourself".
     *
     * `isCoding` describes the QUESTION, but this effect also runs for the skill check —
     * which happens BEFORE that question is put, and is a spoken moment no matter what the
     * question after it turns out to be. So whenever question one happened to be a coding
     * question, this returned early during `skill_check`, the microphone never opened, the
     * candidate said their rating into a closed mic, and parseSelfRating was handed an empty
     * transcript. The parser was blamed for that; it was never called.
     *
     * The failure was intermittent in exactly the way that makes it hard to report — it
     * depended entirely on the type of the first question the orchestrator happened to pick.
     */
    if (isCoding && phase === 'asking') return;
    if (!question?.id || !stt.supported) return;
    /*
     * THE INTERLOCK. Nothing opens this microphone while anyone else has the floor.
     *
     * `panelBusy` is the turn-level flag and is the one that matters — the per-utterance
     * signals have gaps between lines, and that is precisely how the interviewer's own
     * sentence ended up transcribed into an answer. The other two are kept as well: they
     * cost nothing, and `tts.speaking` covers the single-voice fallback path when the panel
     * is unavailable, which panelBusy knows nothing about.
     */
    if (panelBusy || tts.speaking || panelVoices.speakingNow || panelVoices.takingFloor) return;
    /*
     * AND NOT WHILE THE CONNECTION IS DOWN.
     *
     * Recognition is a network service in every browser that has it, so an open mic during an
     * outage is not a recording — it is a mic that produces nothing, or worse, produces a
     * partial transcript when the connection returns and files it as the candidate's answer.
     * Holding it shut is the "less disturbance" half of the report: the question stays on
     * screen, the answer they already typed stays in the box, and nothing is captured badly in
     * between.
     */
    if (!connection.online) return;
    if (stt.listening || stt.error) return;
    if (pinnedClosedRef.current || armedForRef.current === question.id) return;
    /*
     * A beat after they stop — the way you do not start talking the instant someone's last
     * word lands.
     *
     * 900ms rather than 550. Most candidates are on a laptop with the speakers on, so the
     * panel's last syllable is still physically in the room after the audio element reports
     * that it ended, and a recogniser that opens too eagerly captures the tail of it. The
     * cost of waiting is that a very fast candidate says three or four words before the mic
     * catches up; the cost of not waiting is the interviewer's words inside their answer,
     * which is what this is fixing.
     *
     * Re-checked inside the timeout, not just before it: nine hundred milliseconds is long
     * enough for the next turn to have begun.
     */
    const t = setTimeout(() => {
      if (pinnedClosedRef.current || panelBusyRef.current) return;
      /*
       * THE GUARD IS CLAIMED HERE, NOT WHEN THE TIMER WAS SCHEDULED, and the difference is a
       * microphone that silently never opens.
       *
       * It used to be set immediately before the setTimeout. But this effect has eleven
       * dependencies, and its cleanup clears the pending timer — so ANY of them changing
       * inside the 900ms window cancelled the arming, and the re-run then hit
       * `armedForRef.current === question.id` and returned early. The guard had been claimed
       * by an arming that never happened, and nothing would ever claim it again for this
       * question. The mic stayed shut for the whole answer with the interface still inviting
       * the candidate to speak.
       *
       * That is a race, so it presented as the intermittent half of "the mic does not turn
       * on by itself" — dependent on whether a re-render happened to land in a specific
       * nine-hundred-millisecond window.
       *
       * Claiming it at the moment the mic actually opens keeps the property the guard is
       * for — one auto-open per question, never re-opening one the candidate closed — while
       * making a cancelled arming simply reschedule, which is what a cancelled arming should
       * do. Re-runs before it fires are then free: they clear a timer that had claimed
       * nothing and start a fresh one.
       */
      armedForRef.current = question.id;
      openMicRef.current?.();
    }, 900);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
    // `connection.online` is in the list so the mic re-arms once the connection returns —
    // without it a candidate who dropped out mid-question would have to reach for the button.
  }, [handsFree, useTyping, preparing, phase, panelBusy, isCoding, question?.id, tts.speaking, panelVoices.speakingNow, panelVoices.takingFloor, stt.supported, stt.listening, stt.error, connection.online]);

  /**
   * END OF ANSWER — A LABEL, NOT A CLOSE. The mic stays open until they submit.
   *
   * IT USED TO CLOSE, and that was a trap. Four and a half seconds of silence shut the
   * microphone, and because the arming guard had already fired for this question it could
   * NEVER RE-OPEN — so a candidate who paused five seconds to think lost the mic for the
   * rest of the question and had to reach for the button. The interface said "start talking
   * again" while being physically unable to hear them. That is the "it automatically shuts
   * off the mic" report, and the copy was the giveaway: it promised something the code did
   * not do.
   *
   * Closing bought nothing anyway. It was never a submit — the candidate always reviewed and
   * sent — so all it did was end the one thing they might still want. Silence now only
   * changes the prompt underneath, which is what it was really for.
   */
  const [looksDone, setLooksDone] = useState(false);
  useEffect(() => {
    if (!handsFree || !stt.listening || !answer.trim()) {
      setLooksDone(false);
      return;
    }
    const t = setTimeout(() => setLooksDone(true), 3000);
    return () => clearTimeout(t);
    // `answer` in the deps is the point — every new word restarts the timer.
  }, [handsFree, stt.listening, answer]);

  /*
   * ONE PLACE THAT SPEAKS. Fetch a turn, warm every line's audio at once, reveal each line
   * as its own voice starts.
   *
   * Five callers now — the opening, the skill check, the pivot, the code review and the
   * close. Five copies of the prefetch-then-speak dance would be five places for the
   * ordering to drift back to text-before-voice, which is the bug this app has had twice.
   */
  const speakTurn = useCallback(
    async (args: {
      stage: PanelStage;
      question?: string;
      candidate_question?: string;
      language?: string;
      /**
       * DEAD, AND KEPT ONLY TO SAY SO. The thread never resets any more.
       *
       * It used to clear on every new question, which is why "I cannot see what the
       * interviewers are saying" was a fair report: the moment the next turn began, the
       * correction they had just given, the code review, the whole exchange — gone, before
       * anybody had finished reading it. Combined with a remount on every phase change it
       * meant the pane was empty far more often than it had anything in it.
       *
       * An interview is a conversation and a conversation accumulates. Scrolling back to see
       * what somebody said two questions ago is the entire reason this is a thread rather
       * than a question box.
       */
      reset?: boolean;
    }): Promise<{ spoke: boolean; pivotTopic: string; ratingSubject: string }> => {
      /*
       * THIS FUNCTION CANNOT REJECT, AND THAT IS A DESIGN DECISION RATHER THAN CAUTION.
       *
       * Six places await it, several from inside `void (async () => …)()` where a rejection
       * is an unhandled promise and nothing recovers. Each of those then fails differently:
       * the code review leaves the candidate on "They are reading your code…" with no
       * controls at all, the question path leaves an empty thread that will never retry
       * because `panelForRef` is already claimed, the closing box leaves its Ask button
       * spinning forever.
       *
       * Six defensive wrappers would be six chances to forget the seventh. One guarantee
       * here makes every caller safe by construction: on any failure this resolves as
       * "nobody spoke", which is a case every caller already handles because it is what a
       * provider outage has always produced.
       */
      try {
      // Deliberately does not clear. See the note on `reset`.
      setPanelPending(true);
      // Held from BEFORE the request until after the last word — the request itself counts,
      // because a mic opened while the turn is being written is a mic that is open when it
      // arrives.
      setPanelBusy(true);
      /*
       * AND IF IT IS SOMEHOW ALREADY OPEN, CLOSE IT.
       *
       * The interlock above stops the mic OPENING during a turn. This covers the other
       * direction — a mic that was already listening when a turn begins, which happens on
       * every path where the panel speaks in response to something the candidate did rather
       * than at the start of a question: the pivot after a decline, the review after a code
       * submission. Cheap, and the failure it prevents is the one that has already shipped
       * twice.
       */
      closeMicRef.current?.();
      /*
       * AND THROW AWAY WHATEVER IT HEARD.
       *
       * Closing the mic is not enough on its own: the recogniser keeps its own transcript,
       * so anything captured in the instant before the close still flows into the answer box
       * the moment the effect below next runs. That is how a fragment of the interviewer's
       * sentence survives even a correct interlock.
       *
       * Safe to discard because a panel turn only ever begins AFTER an answer has been
       * submitted — the skill check is before any answer exists, and the question, pivot,
       * review and closing turns all follow a submit that already cleared this. There is no
       * path on which this can take a candidate's own words away from them.
       */
      resetAnswerRef.current?.();
      /*
       * AND SILENCE THE SINGLE-VOICE FALLBACK.
       *
       * Reported as "sometimes the old google voice arises in the question's background", and
       * that is exactly what it is — a second voice under the panel, not beside it.
       *
       * There are two independent owners of `window.speechSynthesis`, which is a GLOBAL
       * queue: this page's interviewer fallback (`tts`, used when the panel cannot speak) and
       * usePanelVoices' own browser fallback. Neither knows about the other. usePanelVoices
       * cancels the queue with speechSynthesis.cancel() when it takes the floor — but cancel()
       * only resolves `tts`'s pending utterance, it does not bump `tts`'s generation counter,
       * so `tts`'s loop wakes up at its next await, decides it is still current, and speaks
       * the REST of the previous question over the panel's neural audio. The browser voice is
       * whatever the OS defaults to, which on Chrome is a Google voice.
       *
       * `tts.cancel()` bumps that counter, which is the only thing that actually stops the
       * loop. Called here rather than at each of the six speakTurn call sites, because the
       * invariant is "the panel is about to talk", and that is what this function means.
       */
      tts.cancel();
      try {
      const result = await panelTurn.mutateAsync({
        session_id: sessionId,
        stage: args.stage,
        question: args.question ?? '',
        candidate_question: args.candidate_question ?? '',
        language: args.language ?? '',
        candidate_name: candidateName,
      });
      setPanelPending(false);
      if (!result.turns.length) {
        return {
          spoke: false,
          pivotTopic: result.pivot_topic ?? '',
          ratingSubject: result.rating_subject ?? '',
        };
      }

      // Every line starts synthesising NOW rather than when its turn comes to speak.
      // Serially, a three-line turn was three vendor round-trips of ~3.5s laid end to end
      // with the playback between them.
      voicesRef.current.prefetchTurn(result.turns);
      /*
       * EACH LINE FAILS ON ITS OWN. The `await` used to sit bare in this loop, so a single
       * rejected utterance broke out of it — and every LATER line of that turn was then never
       * spoken and, because the reveal is driven by `onStart`, never even shown. Anil leads
       * almost every turn, so a fault on his line deleted Priya's from the interview
       * entirely: "only the anil is speaking, the priya is not their in the interview".
       *
       * The catch also guarantees the line is REVEALED. A candidate must be able to read what
       * the panel said even when the audio for it failed — losing the voice is a degraded
       * interview, losing the words is a broken one, and the second used to follow from the
       * first for every line after the failure.
       */
      for (const line of result.turns) {
        let shown = false;
        const reveal = () => {
          if (shown) return;
          shown = true;
          setPanelPending(false);
          setPanelLines((prev) => [...prev, line]);
        };
        try {
          await voicesRef.current.speakAs(line.speaker, line.text, {
            // Fires when the audio is in hand, not when the request goes out — so the line
            // appears with the voice rather than seconds ahead of it.
            onStart: reveal,
            tone: line.tone,
          });
        } catch (err) {
          console.warn(`panel line failed for ${line.speaker}; continuing the turn`, err);
          reveal();
        }
      }
      return {
        spoke: true,
        pivotTopic: result.pivot_topic ?? '',
        ratingSubject: result.rating_subject ?? '',
      };
      } finally {
        // `finally`, so a provider failure or a thrown mutation cannot leave the microphone
        // interlocked for the rest of the interview — that would be a worse bug than the one
        // it is fixing, and a silent one.
        setPanelPending(false);
        setPanelBusy(false);
      }
      } catch (err) {
        // Logged rather than swallowed silently — this is invisible from the outside (the
        // interview simply continues in a plainer form), so without a console line there is
        // no way to tell a provider problem from a bug in here.
        console.warn('panel turn failed; continuing without it', err);
        return { spoke: false, pivotTopic: '', ratingSubject: '' };
      }
    },
    // panelTurn and panelVoices are stable enough for this to be safe, and listing them
    // would re-create the callback on every transcribed word.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [sessionId, candidateName],
  );

  /*
   * THE OPENING EXCHANGE: "out of ten, how would you rate yourself in Java?"
   *
   * Asked out loud rather than collected on the setup form, because that is where a real
   * panel asks it and because the answer is meant to shape the room the candidate is
   * already in. It runs once, before the first question, and it is entirely skippable —
   * if the panel cannot speak, or the candidate says something with no number in it, the
   * interview proceeds exactly as it did before this feature existed.
   */
  const skillAskedRef = useRef(false);
  useEffect(() => {
    if (phase !== 'skill_check' || skillAskedRef.current) return;
    if (isLoading || !question) return;
    skillAskedRef.current = true;
    void (async () => {
      const { spoke, ratingSubject: subject } = await speakTurn({ stage: 'skill_check' });
      setRatingSubject(subject);
      // No panel, no skill check. Falling through to the questions is right: the rating is
      // an enhancement, and a candidate staring at a silent screen waiting to be asked
      // something is the worst possible failure mode for it.
      if (!spoke) setPhase('asking');
    })();
  }, [phase, isLoading, question, speakTurn]);

  /*
   * THE QUESTION ITSELF. Unchanged in what it does — the orchestrator still chooses which
   * question, the panel still only decides who says it and how — but it now waits for the
   * skill check and stands down during a pivot or a code review, because those are the
   * panel talking about the question the candidate has already been given.
   */
  useEffect(() => {
    if (phase !== 'asking') return;
    if (!questionText || !question?.id || useTyping) return;
    if (panelForRef.current === question.id) return;
    panelForRef.current = question.id;

    void (async () => {
      const { spoke } = await speakTurn({
        // The first question is a greeting and introductions; everything after is normal
        // flow, where a wrong previous answer gets corrected before the next question.
        // A follow-up is not a new topic and must not be introduced like one. `follow_up`
        // tells the panel to stay on the thread, name the thing from their answer it is
        // pressing on, and keep the same interviewer rather than handing over — which is
        // what a follow-up IS. Delivered through `mid` it read as a fresh question, which is
        // why "I cannot see the cross questions" was a fair description of a feature that
        // had been running all along.
        stage: answered === 0 ? 'opening' : question?.is_follow_up ? 'follow_up' : 'mid',
        question: questionText,
      });
      /*
       * No panel — provider down, over budget, or nothing usable came back.
       *
       * The question is APPENDED TO THE THREAD as a line from the lead interviewer rather
       * than rendered separately, so a failed turn does not blank the conversation or change
       * what the screen looks like. The candidate loses the panel's phrasing, which is a real
       * loss; they do not also lose everything said before it.
       */
      if (!spoke) {
        const lead = interviewers?.[0]?.name ?? 'Interviewer';
        setPanelLines((prev) => [...prev, { speaker: lead, text: questionText, tone: 'asking' }]);
        /*
         * SPOKEN THROUGH THE PANEL VOICE, NOT THE BROWSER — and this line is the whole reason
         * "i can only listen the google default audios" survived four rounds of TTS fixes.
         *
         * It was `tts.speak(questionText)`. `tts` is useSpeechSynthesis: the BROWSER
         * synthesiser, with no path to the vendor at all. So whenever a panel turn came back
         * empty, the question was read out by Chrome in a Google voice — and because the
         * neural layer was never asked, the vendor's dashboard showed zero requests. Every
         * investigation of the TTS layer was looking at code this path does not reach.
         *
         * It also explains the voices changing question to question: a turn that succeeded was
         * spoken by `speakAs` in a real voice, a turn that failed by Chrome. Two speech systems
         * in one interview, alternating on whether an AI call happened to return.
         *
         * `speakAs` is the same call the successful path uses, so the fallback now sounds like
         * the interview it belongs to. It has its own browser fallback inside it, so nothing is
         * lost when the vendor genuinely is unavailable — the difference is that the vendor is
         * now ASKED.
         */
        void voicesRef.current.speakAs(lead, questionText, { tone: 'asking' });
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, questionText, question?.id, useTyping]);

  /*
   * THE CLOSE. Wrap-up, then "do you have any questions for us?", then an actual answer to
   * whatever they ask.
   *
   * The stages have existed server-side since the panel was built and nothing ever
   * triggered them, so the interview simply stopped. It runs when the orchestrator has no
   * more questions, and EVERY step falls through on failure — the report is reachable from
   * the header at all times, and a closing turn that cannot be generated must not be able
   * to strand somebody one click from their result.
   */
  useEffect(() => {
    /*
     * A FAILED FETCH IS NOT THE END OF THE INTERVIEW.
     *
     * `question` is `data?.question ?? null`, so it is null when the interview is over AND
     * when the /next request simply failed — a dropped campus connection, both retries lost.
     * Without this check the closing sequence fires on that failure: `closedRef` latches,
     * the phase moves to `closing`, and the candidate who taps Retry gets their question
     * back into a page that has already decided the interview finished. There is no way out
     * of that except End Interview, on an interview that never started.
     *
     * `isError` distinguishes them, and it is the only thing that can.
     */
    if (isError) return;
    if (question !== null || preparing || closedRef.current) return;
    // Wait for the skill check ONLY if one is actually going to happen. With no question
    // there is nothing to wait for, and blocking unconditionally would strand a session
    // that had no questions at all on a screen with no way forward but End Interview.
    if (phase === 'skill_check' && question) return;
    closedRef.current = true;
    setPhase('closing');
    void (async () => {
      // Two turns, in order: Anil says he is done and asks Priya whether she has anything
      // else, then the panel asks the candidate whether they have questions. Appended
      // rather than replacing, so the candidate can still see what was just said to them.
      await speakTurn({ stage: 'wrapping' });
      await speakTurn({ stage: 'candidate_questions', reset: false });
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [question, preparing, phase, isError]);

  useEffect(() => {
    // Never while the panel has the floor. The interlock upstream should mean the mic is
    // shut, but this is the last gate before their words become the candidate's answer, and
    // it costs one comparison.
    if (panelBusy) return;
    if (stt.transcript) setAnswer(stt.transcript);
  }, [stt.transcript, panelBusy]);

  //: The thread scrolls inside its own pane now, so the newest line would otherwise arrive
  //: below the fold — the candidate would be reading one sentence behind the voice, which is
  //: the same complaint as text-before-voice wearing a different hat.
  const threadEndRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [panelLines.length, panelPending]);

  /*
   * THE SPOKEN RATING. "Out of ten, how would you rate yourself in Java?" — and they say it.
   *
   * Read from the transcript rather than collected on a form, because the panel asked it out
   * loud and a slider appearing mid-conversation to catch an answer somebody just gave is
   * exactly the seam this redesign exists to remove.
   *
   * parseSelfRating returns null rather than guessing, and that is the important half: a
   * wrong rating silently changes which questions the candidate is asked and what their
   * report judges them against, with nothing on screen to say so. When it cannot find a
   * number the buttons in the panel stay up and the candidate taps one, which costs one tap
   * and is honest.
   */
  useEffect(() => {
    if (phase !== 'skill_check' || !stt.transcript.trim()) return;
    const parsed = parseSelfRating(stt.transcript);
    if (!parsed) return;

    /*
     * DEBOUNCED ON THE TRANSCRIPT, not on the microphone closing.
     *
     * It used to wait for `!stt.listening`, on the reasoning that the mic closing itself
     * after silence was the signal they had finished. Two things were wrong with that. The
     * mic no longer auto-closes at all — closing it was a trap, see the note above — so the
     * signal never arrives. And even before that, it meant saying "2" and then sitting for
     * four and a half seconds before anything happened, which reads as the app not having
     * heard you. Reported exactly that way: "when i spoke 2 it did not catch it".
     *
     * Every new word restarts this timer, so "six... no, seven" still lands on seven — the
     * self-correction case the last-number-wins rule in parseSelfRating exists for. 1.4s is
     * long enough to cover the gap between "six" and "no, seven" and short enough that a
     * one-word answer feels answered.
     */
    const t = setTimeout(
      () => {
        selfRating.mutate({
          rating: parsed.rating,
          subject: ratingSubject,
          strengths: parsed.strengths,
        });
        setAnswer('');
        stt.reset();
        setPhase('asking');
      },
      stt.listening ? 1400 : 250,
    );
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, stt.transcript, stt.listening]);

  const closeMic = () => {
    stt.stop();
    if (speakStartRef.current) {
      speakSecondsRef.current += (Date.now() - speakStartRef.current) / 1000;
      speakStartRef.current = null;
    }
  };

  resetAnswerRef.current = () => {
    setAnswer('');
    stt.reset();
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
    // Guarded here as well as in the UI. This is the one function that files an answer
    // against a question id, and the UI gate above is a rendering decision that a future
    // layout change could quietly drop — filing the candidate's self-rating as their answer
    // to question one is not a mistake worth being one refactor away from.
    if (phase !== 'asking') return;
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

    const declinedQuestion = questionText ?? '';
    const wasCoding = isCoding;

    submitAnswer.mutate(
      { sessionId, questionId: question.id, content, delivery },
      {
        onSuccess: (res) => {
          setAnswered(res.questions_answered);
          setAnswer('');
          stt.reset();
          speakSecondsRef.current = 0;

          /*
           * THEY SAID THEY DID NOT KNOW. Offer them somewhere else to stand.
           *
           * `declined` is decided SERVER-side (dont_know.py, forty tests) because the rule
           * is subtle: "I don't know the exact syntax, but you'd use a ConcurrentHashMap
           * and compute() is atomic" is a good answer that opens with the phrase, and
           * interrupting it to offer an easier topic would land on exactly the careful
           * students who hedge before explaining.
           *
           * The answer is still recorded and still scored — declining IS an answer to the
           * question and is graded as one. The pivot is recorded too, which is what stops
           * "I don't know" being a free instruction to serve easier questions.
           */
          if (res.declined) {
            void (async () => {
              /*
               * WRAPPED, BECAUSE A THROW HERE STRANDS THEM.
               *
               * If speakTurn rejects — a callback that raises, an unexpected state — neither
               * branch below runs: the phase stays `asking`, `panelForRef` still holds the
               * question just answered so no new turn fires, and `refetch` never happens.
               * The candidate sits on an answered question with an empty box and no way
               * forward but End Interview.
               *
               * The catch does the only thing that is always right: move the interview on.
               * Losing the pivot costs them a courtesy; losing the interview costs them the
               * session.
               */
              try {
                // Appended: the candidate should still see the question they just declined
                // above the offer to move on. Replacing it would make "do you know about X?"
                // arrive with no visible reason.
                const { pivotTopic } = await speakTurn({ stage: 'pivot', reset: false });
                if (pivotTopic) {
                  setPivotOffer({ topic: pivotTopic, declined: declinedQuestion });
                  setPhase('pivot');
                  recordPivot.mutate({
                    declined_question: declinedQuestion,
                    offered_topic: pivotTopic,
                    // Recorded as offered, not accepted. Whether they take it is a second
                    // event, and pretending they did would overstate what happened.
                    accepted: false,
                  });
                  return;
                }
              } catch {
                // Fall through to the same place "nothing left to offer" goes.
              }
              // Nothing left to offer, or the turn failed. Moving on is the honest outcome —
              // inventing a topic the bank cannot source would be a dead end mid-interview.
              refetch();
            })();
            return;
          }

          /*
           * THEY WROTE CODE. The panel reads it back and says what is wrong with it.
           *
           * The code is not sent from here — it is the answer that was just submitted, and
           * the server reads it back out of the database like every other thing the panel
           * grounds itself in. That keeps the answer key server-side and means a review
           * cannot be produced against code the candidate did not actually submit.
           */
          if (wasCoding) {
            void (async () => {
              setPhase('reviewing');
              try {
                // Appended for the same reason: a review reads as a review only when the
                // problem it is reviewing against is still on screen.
                await speakTurn({
                  stage: 'code_review',
                  language: codeLanguage,
                  reset: false,
                });
              } finally {
                /*
                 * `finally`, AND THIS ONE IS THE WORST OF THE TWO TO GET WRONG.
                 *
                 * `reviewing` is a phase with no controls at all — no microphone, no submit,
                 * nothing but "They are reading your code…". If speakTurn throws before these
                 * two lines, the candidate watches that message for the rest of the session.
                 * Every other phase has at least one button; this one has none, so it is the
                 * only phase where a missing reset is unrecoverable.
                 */
                setPhase('asking');
                refetch();
              }
            })();
            return;
          }

          refetch();
        },
        onError: (err: Error) => {
          /*
           * A FAILED SUBMIT IS THE STRONGEST CONNECTIVITY SIGNAL WE GET, and the only one that
           * catches a device whose `navigator.onLine` is lying — a hotspot with no data left
           * keeps the radio associated and reports itself online forever.
           *
           * Filtered by `isNetworkError`, because a 402 out of credits or a 500 from the
           * scorer is not a connection problem, and telling a candidate to check their wifi
           * when the server rejected their request sends them to fix the wrong thing.
           */
          if (isNetworkError(err)) {
            connection.reportFailure();
            // No toast on this path. The strip already says it, more calmly and without
            // stacking one per retry.
            return;
          }
          toast.error(err.message || 'Failed to submit answer. Please try again.');
        },
      }
    );
  };

  const handleSubmit = () => submitContent(answer);

  // ─── Loading / preparing ──────────────────────────────────────────────────
  /*
   * WAIT FOR THE ROLE BEFORE DRAWING THE ROOM.
   *
   * `hasEditor` is `panelInfo?.technical ?? true`, and that default is right — a missing
   * editor costs a developer the question they were about to answer, a spurious one costs a
   * sales candidate a glance. But while the query is in flight it means a SALES interview
   * opens as three columns with a code editor in the middle, mounts CodeMirror and its
   * language modes, and then reflows to two columns underneath the candidate a moment later.
   *
   * The page already shows this spinner while the first question loads, and the two queries
   * run in parallel, so waiting for both usually costs nothing and removes the flash
   * entirely. Somebody who told us their interview is not technical should never see a code
   * editor, not even for a frame.
   */
  if (isLoading || panelInfoLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <GeneratingQuestion label="Preparing your first question…" />
      </div>
    );
  }

  /*
   * ─── Network / server error — clean retry, no console/toast storm ─────────
   *
   * ONLY WHEN THERE IS NOTHING TO SHOW. This used to fire on `isError` alone, and that is the
   * biggest part of "there must be a less disturbance": a thirty-second wifi drop mid-interview
   * replaced the entire session — the pinned question, the answer half-typed in the box, the
   * whole panel thread — with a full-screen error card. The progress was never actually lost,
   * but every visible trace of it was, and coming back to an empty thread is indistinguishable
   * from starting over. It is why the report says "the interview must not start from the
   * starting" about a system that already resumed correctly.
   *
   * With a question in hand the interview stays exactly where it was and the offline strip
   * above does the talking. TanStack Query keeps the last successful data through an error, so
   * `question` survives the outage — which is what makes this safe rather than optimistic.
   */
  if (isError && !question) {
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

  /*
   * ─── Interview complete ───────────────────────────────────────────────────
   *
   * `phase === 'done'`, NOT `question === null`. That distinction is the whole closing
   * sequence: the orchestrator running out of questions used to be the end of the
   * interview, and now it is the beginning of the end — the panel wraps up, asks whether
   * the candidate has anything to ask THEM, and answers it. Gating on the absence of a
   * question would replace that entire conversation with this card the instant it started.
   */
  if (phase === 'done') {
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
          <p className="mb-6 text-sm leading-relaxed text-muted-foreground">
            Nicely done{answered ? ` — you answered ${answered} question${answered === 1 ? '' : 's'}` : ''}.
            We&apos;ll now score every answer and build your full report.
          </p>

          {/* ── THE RATING, AND WHY IT CANNOT COST THEM THE REPORT ───────────────────────
              Required to press the button, by decision — but the SAVE is fired without being
              awaited, so the report is never waiting on it. A rating that fails costs the
              rating and nothing else.

              That distinction is the whole design. The candidate has paid ₹49 and is one tap
              from the thing they paid for; putting a network call on the critical path to it
              would mean a dropped connection strands somebody on this card with no way
              forward. Requiring the GESTURE and not the RESPONSE gives the response rate a
              required field buys without the failure mode it usually brings. */}
          <div className="mb-6">
            <p className="mb-2 text-sm font-medium text-foreground">How was your interview?</p>
            <StarRating
              value={stars}
              onChange={setStars}
              label="Rate your interview out of five"
            />
          </div>

          <Button
            className="w-full"
            disabled={stars === 0}
            onClick={() => {
              // NOT AWAITED, AND THE CATCH IS THE POINT. An unhandled rejection from a
              // fire-and-forget promise is an error in the console at best and a crashed
              // render at worst; swallowing it here is what makes "the rating cannot cost
              // them the report" true rather than merely intended.
              rateInterview.mutate({ sessionId, stars });
              completeSession.mutate(sessionId);
            }}
            loading={completeSession.isPending}
          >
            View Final Report
          </Button>
          {stars === 0 && (
            <p className="mt-2 text-xs text-muted-foreground">
              Tap a star to continue.
            </p>
          )}
        </motion.div>
      </div>
    );
  }

  const wordCount = answer.trim() ? answer.trim().split(/\s+/).length : 0;

  return (
    /*
     * EXACTLY ONE VIEWPORT TALL, and each pane scrolls inside it.
     *
     * THE JUMPING MIC BUTTON. The page used to grow with its content, so every line the
     * panel added pushed the answer controls further down — the microphone moved under your
     * thumb between one sentence and the next, which during an interview is genuinely
     * disorienting. Bounding the page is what pins them: the thread scrolls, the mic does
     * not move.
     *
     * 100dvh rather than 100vh: on mobile Safari and Chrome, vh is the height with the
     * browser chrome HIDDEN, so a 100vh page is permanently taller than the visible area and
     * the bottom of it — the mic — sits under the address bar. dvh tracks the real viewport.
     *
     * ── AND AN ESCAPE HATCH BELOW 700px OF HEIGHT ───────────────────────────────────────
     *
     * REPORTED: "in the zoomed screens the submit answer button in the interview is also
     * been hidden". Pinning the app to the viewport is right until the viewport is smaller
     * than the layout's own floor, and then it is the bug. `h-[100dvh]` is a HARD height and
     * `overflow-hidden` means anything past it is not scrolled to — it does not exist. The
     * floor is about 692px (the arithmetic is in tailwind.config.ts next to the `short`
     * screen), and the last thing past it is the button row.
     *
     * Browser zoom is what produces those viewports. Zoom does not make CSS pixels smaller,
     * it makes the window hold fewer of them, so a 900px window is a 450px viewport at 200%
     * — and a candidate who has zoomed in to read the question is precisely the candidate
     * who then cannot submit their answer. A phone in landscape (844x390) is under the floor
     * with no zoom at all.
     *
     * So below 700px tall the page stops being an app pinned to the viewport and becomes a
     * page: `h-auto min-h-[100dvh] overflow-visible`, and each pane hands back its own
     * scrolling (`short:overflow-visible`) so what you get is ONE ordinary page scroll with
     * nothing clipped, rather than a scrollable page full of panes that are still clipping.
     * Everything is reachable, in exchange for the mic no longer being pinned — which is the
     * right trade, because a mic that does not move and a Submit button that does not exist
     * is not a trade at all.
     *
     * Above 700px NOTHING CHANGES. `short` is a raw max-height media query, so every desktop
     * and every ordinary laptop window keeps exactly the pinned layout it has today.
     */
    <div className="flex h-[100dvh] flex-col overflow-hidden bg-background short:h-auto short:min-h-[100dvh] short:overflow-visible">
      {/* THEY CAME BACK. Shown after a tab or app switch, because nothing can be prevented at
          that point — the interview kept running while they were away — and the honest thing
          is to tell them what it cost and what happens if they do it again. Dismissible, but it
          returns on the next departure: somebody who dismissed it and left again has shown they
          did not take it in. */}
      {leave.hasLeft && (
        <div
          role="alert"
          className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-accent-amber/40 bg-accent-amber/15 px-4 py-2 text-xs text-accent-amber-ink sm:px-6"
        >
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden />
          <span className="min-w-0 flex-1">
            <strong className="font-semibold">Stay on this screen.</strong>{' '}
            {isFreeAttempt ? 'Your free interview' : 'This interview'} is already counted — the
            interview kept going while you were away, and closing or reloading this tab ends it
            for good.
          </span>
          <button
            onClick={leave.acknowledge}
            className="shrink-0 font-semibold underline underline-offset-2"
          >
            Got it
          </button>
        </div>
      )}
      {/* Header.
          THE TITLE TRUNCATES AND THE BUTTON DOES NOT SHRINK, and that ordering is the whole
          point of the classes here. This row was `justify-between` with `px-6` and nothing
          allowed to give: at 320px — the narrowest phone, and also what 400% zoom makes of a
          1280px window — "Live Interview Session" plus the "N answered" chip plus "End
          Interview" needs about 296px of the 272px available, and the root above is
          `overflow-hidden`, so the overflow was not a horizontal scrollbar. It was the End
          Interview button being cut off the right edge — the one control mic-interlock.test.ts
          calls the universal escape, gone at the one size where a candidate is most likely to
          be stuck.
          `min-w-0` on the group is what lets `truncate` engage on the title (a flex item's
          automatic minimum size is its content, so without it the text refuses to shrink and
          pushes its siblings out instead), and the title is the right thing to sacrifice: it
          is decoration, and the button is a way out. */}
      <header className="flex h-16 flex-shrink-0 items-center justify-between gap-2 border-b border-border/50 bg-surface/60 px-4 backdrop-blur-md sm:px-6">
        <div className="flex min-w-0 items-center gap-3">
          <span className="relative flex h-2.5 w-2.5 flex-shrink-0">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent-coral opacity-60" />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-accent-coral" />
          </span>
          <span className="truncate text-sm font-semibold tracking-tight">Live Interview Session</span>
          {answered > 0 && (
            <span className="ml-1 flex-shrink-0 whitespace-nowrap rounded-full bg-surface-elevated px-2.5 py-0.5 text-xs font-medium text-muted-foreground">
              {answered} answered
            </span>
          )}
        </div>
        {/* ALWAYS LIVE, at every phase.
            The closing sequence adds three panel turns between the last answer and the
            report, and any of them can fail or hang on a bad connection. A candidate must
            never be unable to reach their own result because a piece of dialogue would not
            generate — so this bypasses every phase and goes straight to the report. */}
        <button
          onClick={() => {
            panelVoices.cancelAll();
            completeSession.mutate(sessionId);
          }}
          className="flex flex-shrink-0 items-center gap-2 whitespace-nowrap rounded-lg px-3 py-1.5 text-xs font-medium text-destructive transition-colors hover:bg-destructive/10"
        >
          <StopCircle className="h-4 w-4 flex-shrink-0" /> End Interview
        </button>
      </header>

      {/* ── The connection warning ──────────────────────────────────────────────
          A STRIP, NOT A MODAL, and that is the whole design. "there must be a less
          disturbance": a dialog over the interview would take the question off screen,
          steal focus from the answer box and make a thirty-second wifi blip feel like a
          failed session. This states the problem, says what is safe, and leaves everything
          else exactly where it was — the question stays pinned, the typed answer stays in
          the box, the timer holds, and the microphone stays shut until it can be heard.

          flex-shrink-0 so it cannot be compressed out of existence by the panes below, and
          outside the scroll container so it stays visible while the thread scrolls. */}
      {!connection.online && (
        <div
          role="status"
          aria-live="polite"
          className="flex flex-shrink-0 items-center gap-3 border-b border-accent-amber/30 bg-accent-amber/10 px-4 py-2.5 sm:px-6"
        >
          <WifiOff className="h-4 w-4 flex-shrink-0 text-accent-amber" aria-hidden />
          <p className="text-xs leading-relaxed text-foreground">
            <span className="font-semibold">No internet connection.</span>{' '}
            {/* Says the thing the candidate is actually worried about. A generic "connection
                lost" leaves them wondering whether to refresh — and refreshing is the one
                action that would feel like losing the interview, even though it would not. */}
            Your interview is paused, not lost — you&rsquo;ll carry on from this same question
            once you&rsquo;re back. Nothing you&rsquo;ve typed will be discarded.
          </p>
        </div>
      )}
      {/* The proctoring alert, wherever the candidate is looking.
          Duplicated from inside the video pane on purpose: below lg that pane is behind a
          tab, and an invigilation warning the candidate never sees is not invigilation. */}
      {presence.multiplePeople && mobilePane !== 'you' && (
        <div
          role="alert"
          className="flex items-center gap-2 border-b border-destructive/40 bg-destructive px-4 py-2 text-xs font-medium text-destructive-foreground lg:hidden"
        >
          <AlertTriangle className="h-3.5 w-3.5 flex-shrink-0" />
          Another person is in frame. In a real interview this ends the round.
        </div>
      )}

      {/* Mobile pane switcher.
          Three columns do not fit on 375px and this product's users are overwhelmingly
          phone-first. Stacking them would be worse than tabs: the compiler would sit two
          screens below the question it belongs to, and the video below that, so a candidate
          would be scrolling during an interview. Tabs keep each pane full-height and one
          thumb away. Above lg they disappear and all three are simply on screen.

          STICKY UNDER `short:`, and only there. Below 700px tall the page scrolls as a page
          (see the root above), and a pane switcher that scrolls away is a navigation the
          candidate has to scroll back up to find — on a coding question, where the answer
          lives in the Compiler pane, that is the difference between a tab and a dead end. It
          takes an opaque background at the same time, because a translucent bar over
          scrolling text is unreadable. Pinned above `short`, where nothing scrolls past it
          anyway, so this is invisible on desktop. */}
      <div className="flex flex-shrink-0 items-center gap-1 border-b border-border/50 bg-surface/40 p-2 lg:hidden short:sticky short:top-0 short:z-30 short:bg-surface">
        {([
          { id: 'talk', label: 'Interview', icon: MessageSquare },
          // Filtered, not disabled. A tab that leads to a pane the interview does not have
          // is a dead end, and on a phone it is a third of the bar.
          ...(hasEditor ? [{ id: 'code' as const, label: 'Compiler', icon: Code2 }] : []),
          { id: 'you', label: 'You', icon: Video },
        ] as const).map((t) => {
          const Icon = t.icon;
          return (
            <button
              key={t.id}
              onClick={() => setMobilePane(t.id)}
              className={cn(
                'flex min-h-10 flex-1 items-center justify-center gap-1.5 rounded-lg text-xs font-medium transition-colors',
                mobilePane === t.id
                  ? 'bg-primary/10 text-primary'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              <Icon className="h-3.5 w-3.5" />
              {t.label}
              {/* The camera is the one pane you might genuinely need to look at while
                  reading another, so it carries its warning across to the tab. */}
              {t.id === 'you' && presence.multiplePeopleEver && (
                <span className="h-1.5 w-1.5 rounded-full bg-destructive" />
              )}
            </button>
          );
        })}
      </div>

      {/* THE THREE PANES.
          Conversation left, compiler middle, video right — the shape of a real technical
          screen, where the person you are talking to is beside your editor rather than
          replaced by it. The middle column is the widest because it is the one being typed
          in; the right is the narrowest because a webcam tile does not need more. */}
      <motion.main
        initial="hidden"
        animate="visible"
        variants={staggerContainer(0.08)}
        // min-h-0 is what actually makes the panes scroll rather than the page: a grid item
        // defaults to min-height:auto, which means "as tall as my content" and silently
        // defeats every overflow rule inside it.
        className={cn(
          'mx-auto grid w-full min-h-0 max-w-[1800px] flex-1 gap-4 p-3 sm:p-4 lg:gap-5 lg:p-5',
          // Two columns without an editor, not three with an empty one. A non-technical
          // interview is a conversation and a camera, and giving the conversation the room
          // the editor was taking is the point of removing it.
          hasEditor
            ? 'lg:grid-cols-[minmax(320px,1fr)_minmax(0,1.55fr)_minmax(280px,0.85fr)]'
            : 'lg:max-w-[1200px] lg:grid-cols-[minmax(0,1.7fr)_minmax(280px,0.8fr)]',
        )}
      >
        {/* ── LEFT: the conversation ──────────────────────────────────────── */}
        <motion.div
          variants={fadeUp}
          className={cn(
            // `overflow-y-auto` is the belt to the `short:` braces, and it earns its place in
            // the band the breakpoint does not cover. The 692px floor in tailwind.config.ts is
            // the floor with NO banners up; the offline strip, the "we cannot hear you" alert
            // and the sworn-words notice are 60-90px each, so at 750px tall with two of them
            // showing this pane's content exceeds it again while still being above `short`.
            // Without this the surplus was clipped by the root and the button row went with
            // it; with it the pane scrolls and everything in it stays reachable.
            //
            // Released under `short:`, where the page itself is the scroller — a pane that
            // keeps its own scrollbar inside a scrolling page is two nested scroll areas over
            // the same content, and on a touch screen the wrong one always takes the gesture.
            'glass flex min-h-0 flex-col overflow-y-auto rounded-2xl border-border/50 p-4 sm:p-5 short:overflow-visible',
            mobilePane === 'talk' ? 'flex' : 'hidden lg:flex',
          )}
        >
          <div className="mb-4 flex flex-shrink-0 items-center gap-2">
            <Badge variant="primary">
              {phase === 'skill_check'
                ? 'Getting started'
                : phase === 'closing'
                  ? 'Wrapping up'
                  : phase === 'reviewing'
                    ? 'Code review'
                    : 'Interview'}
            </Badge>
            {question?.difficulty && phase === 'asking' && (
              <span className={`badge-${question.difficulty}`}>{question.difficulty}</span>
            )}
            {answered > 0 && (
              <span className="ml-auto text-[11px] text-muted-foreground">
                {answered} answered
              </span>
            )}
          </div>

          {/* The thread scrolls; the answer controls below it do not. During an interview the
              thing you must always be able to reach is the microphone, and a mic button that
              scrolls off after a long code review is a mic button that is not there. */}
          {/* `short:overflow-visible` releases the thread's own scrollbar when the page has
              become the scroller. It keeps `flex-1 min-h-0`, which in a content-sized column
              simply resolves to the thread's own height — so under `short:` the whole
              conversation is in the page scroll rather than in a 100px window inside it. */}
          <div className="mb-4 min-h-0 flex-1 overflow-y-auto pr-1 short:overflow-visible">
            {/* NO AnimatePresence AND NO CHANGING KEY.
                Both were destroying the conversation. `mode="wait"` unmounts the current
                child before mounting the next, and the key included `phase` — so every move
                between skill_check, asking, pivot, reviewing and closing tore down the whole
                thread and rebuilt it empty. Together with the reset that used to run on each
                turn, the interviewers' words were being deleted twice over, which is exactly
                what "I cannot see what the interviewers are saying" describes.

                The lines animate themselves in individually inside PanelThread, which is
                where the animation belonged all along. */}
            <div>
              {preparing && !panelLines.length ? (
                <GeneratingQuestion label="Thinking about your next question…" />
              ) : (
                <div>
                  <PanelThread
                    lines={panelLines}
                    speakingNow={panelVoices.speakingNow}
                    takingFloor={panelVoices.takingFloor}
                    interviewers={interviewers}
                    // No fallback prop any more: a question the panel could not dress up is
                    // appended to the thread as a line from the lead interviewer, so it
                    // reads as the same interview rather than as the page changing.
                    // THE WHOLE GAP, not just the panel call. `panelPending` covers writing
                    // the turn; `preparing` covers submitting the answer and fetching the next
                    // question, which happen first. Passing only the former left the earliest
                    // and least explicable part of the wait — right after the candidate presses
                    // submit — with nothing on screen at all.
                    pending={panelPending || preparing}
                  />

                  {/* The pivot, made explicit.
                      The panel has just asked "do you know about X?" out loud, and the
                      candidate answers out loud. But a spoken "yes" is indistinguishable
                      from the start of an answer to a recogniser, so the two buttons are
                      the unambiguous path — and they are the ONLY thing on screen at that
                      moment, so there is nothing to misread. */}
                  {phase === 'pivot' && pivotOffer && (
                    <div className="mt-4 rounded-xl border border-primary/30 bg-primary/5 p-4">
                      <p className="mb-3 text-sm">
                        Do you know about{' '}
                        <span className="font-semibold">{pivotOffer.topic}</span>?
                      </p>
                      <div className="flex flex-wrap gap-2">
                        <Button
                          size="sm"
                          onClick={() => {
                            recordPivot.mutate({
                              declined_question: pivotOffer.declined,
                              offered_topic: pivotOffer.topic,
                              accepted: true,
                            });
                            setPivotOffer(null);
                            setPhase('asking');
                            refetch();
                          }}
                        >
                          Yes, ask me
                        </Button>
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => {
                            setPivotOffer(null);
                            setPhase('asking');
                            refetch();
                          }}
                        >
                          Not that either
                        </Button>
                      </div>
                    </div>
                  )}

                  {/* THE LAST EXCHANGE. "Do you have any questions for us?"
                      The one part of an interview candidates actually remember, and the
                      one this app used to skip entirely — the stages existed server-side
                      and nothing ever called them, so the interview just stopped.

                      Typed rather than spoken, and deliberately: this is the moment the
                      microphone is least reliable, because the candidate has stopped
                      performing and is thinking about what to ask. A mistranscribed
                      question here gets a confident answer to something they did not ask. */}
                  {phase === 'closing' && !panelPending && !panelVoices.speakingNow && (
                    <div className="mt-4 rounded-xl border border-border/60 bg-surface/40 p-4">
                      <textarea
                        value={closingQuestion}
                        onChange={(e) => setClosingQuestion(e.target.value)}
                        placeholder="Ask them anything — about the role, the process, or how you did."
                        rows={2}
                        className="mb-3 w-full resize-none rounded-lg border border-border/50 bg-surface-elevated p-3 text-sm leading-relaxed focus:border-primary/40 focus:outline-none"
                      />
                      <div className="flex flex-wrap items-center gap-2">
                        <Button
                          size="sm"
                          disabled={!closingQuestion.trim() || answeringClosing}
                          loading={answeringClosing}
                          onClick={() => {
                            const asked = closingQuestion.trim();
                            setClosingQuestion('');
                            setAnsweringClosing(true);
                            void (async () => {
                              await speakTurn({
                                stage: 'answering_candidate',
                                candidate_question: asked,
                                reset: false,
                              });
                              setAnsweringClosing(false);
                            })();
                          }}
                        >
                          Ask
                        </Button>
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => setPhase('done')}
                        >
                          Nothing from me — finish
                        </Button>
                      </div>
                    </div>
                  )}

                  {/* The self-rating, when the number could not be heard.
                      parseSelfRating returns null rather than guessing — a wrong rating
                      silently changes which questions you get and what your report judges
                      you against, which is far worse than one extra tap. */}
                  {phase === 'skill_check' && !panelPending && !panelVoices.speakingNow && (
                    <div className="mt-4 rounded-xl border border-border/60 bg-surface/40 p-4">
                      <p className="mb-3 text-xs text-muted-foreground">
                        Say it out loud, or pick a number — it decides how hard the questions
                        start.
                      </p>
                      <div className="flex flex-wrap gap-1.5">
                        {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((n) => (
                          <button
                            key={n}
                            onClick={() => {
                              selfRating.mutate({ rating: n, subject: ratingSubject, strengths: [] });
                              setPhase('asking');
                            }}
                            className="h-9 w-9 rounded-lg border border-border text-xs font-semibold transition-colors hover:border-primary hover:bg-primary/10 hover:text-primary"
                          >
                            {n}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
            <div ref={threadEndRef} />
          </div>

          {/* ── The question on the table, pinned above the answer channel ─────
              THE QUESTION USED TO EXIST ONLY AS A CHAT LINE, and that was the organisational
              problem behind "the section where the question arises and where the answer is
              said need to be organised again".

              The panel thread is a conversation, so a question scrolls away behind the
              correction, the aside and the handover that follow it — and a candidate two
              minutes into composing an answer had nothing on screen telling them what they
              were answering. In a real room the question stays in the air; in a chat log it
              does not, and re-reading upward mid-answer is the moment the illusion breaks.

              So the current question is restated here, immediately above the box it is
              answered into: the two halves of the exchange are adjacent and separately
              labelled, rather than one being a scrolled-past message.

              `flex-shrink-0` and outside the scrolling region deliberately — the layout
              invariants pinned in mic-interlock.test.ts require the answer controls to stay
              out of the scroll container, and this is part of that block. It is NOT a second
              copy of the thread: only the question itself, only while one is actually open. */}
          {phase === 'asking' && questionText && (
            <div className="flex-shrink-0 rounded-xl border border-primary/25 bg-primary/[0.04] px-4 py-3">
              {/* THE LABEL ROW IS GONE — "ANIL ASKED · EASY" — and only the coding marker
                  survives, because that one changes what the candidate is meant to DO.

                  Removed on request, and the request was right on both halves. "Anil asked"
                  restates what the thread directly above already shows, attributed, with the
                  panelist's name on it; a second attribution three lines later is the machinery
                  announcing itself. And the DIFFICULTY badge should never have been shown to
                  the person being assessed: telling somebody a question is "EASY" before they
                  answer it can only do harm. Get it right and you were told it was easy; get it
                  wrong and you were told you failed an easy one. It is a planning label for the
                  interview's own bookkeeping, and it leaked onto the candidate's screen.

                  The question TEXT stays. It is pinned outside the scroll container so a long
                  question does not disappear while somebody is answering it, which is the one
                  job this block does that the thread cannot. */}
              {isCoding && (
                <div className="mb-1.5 flex items-center gap-2">
                  <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
                    <Code2 className="h-3 w-3" aria-hidden />
                    coding
                  </span>
                </div>
              )}
              {/* Clamped rather than scrollable. A long question that grows this block pushes
                  the microphone off screen on a laptop, and the full text is always still in
                  the thread above. */}
              <p className="line-clamp-3 text-sm leading-relaxed text-foreground">
                {pinnedQuestion}
              </p>
            </div>
          )}

          {/* ── The answer channel, pinned to the bottom of the conversation ── */}
          <div className="flex-shrink-0 border-t border-border/50 pt-4">
          {/* Labelled, so the two halves of the exchange read as two sections rather than as
              one undifferentiated column. Hidden on the non-answering phases, where the
              controls below are an explanation rather than an input. */}
          {phase === 'asking' && !isCoding && (
            <p className="mb-2 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
              Your answer
            </p>
          )}
          {/*
            ONLY WHEN A QUESTION IS ACTUALLY OPEN.
            Without this gate, "seven out of ten" said during the skill check is filed as
            the answer to question one — submitContent only checks that a `question` exists,
            and during the opening exchange one already does. The pivot and the close have
            their own controls in the thread above for the same reason: neither is a moment
            when "Submit & Next" means anything.
          */}
          {/* On a coding question the answer is in the middle pane, so this side says where
              to go rather than offering a second, wrong way to answer. Showing a microphone
              here would be offering the candidate a channel that files a spoken answer
              against a question that asked for code. */}
          {phase === 'asking' && isCoding ? (
            <p className="flex items-center justify-center gap-2 py-2 text-center text-xs text-muted-foreground">
              <Code2 className="h-3.5 w-3.5 flex-shrink-0" />
              Write your solution in the editor, run it, then submit.
            </p>
          ) : phase !== 'asking' ? (
            <p className="py-2 text-center text-xs text-muted-foreground">
              {phase === 'skill_check'
                ? 'Say your rating out loud, or tap a number above.'
                : phase === 'pivot'
                  ? 'Answer them above.'
                  : phase === 'reviewing'
                    ? 'They are reading your code…'
                    : 'Ask them anything above, or finish up.'}
            </p>
          ) : useTyping ? (
            /* Typing fallback */
            <>
              <textarea
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                disabled={preparing}
                placeholder="Type your answer here as if you were speaking to an interviewer…"
                /* Capped for the same reason as the voice transcript below — `flex-1` in a
                   content-sized parent grows instead of scrolling, and a long typed answer
                   pushed Submit off the bottom. A textarea scrolls natively once bounded.

                   dvh, NOT vh, for the same reason the root is: this is a CEILING, and a
                   ceiling measured against the viewport-with-the-chrome-hidden is about 10%
                   taller than intended on a phone — 10% of the height the button row needs.

                   AND THE FLOOR COMES DOWN ON A SHORT VIEWPORT, because a floor and a ceiling
                   that cross is a box that has stopped responding at all. 22dvh falls below
                   96px at roughly 437px of viewport height, and from there the min-height
                   wins: everything around this box keeps compressing and this one does not,
                   which is precisely what pushes the button row out. 64px still shows three
                   lines at this leading, and the box scrolls, so nothing is lost but slack. */
                className="ease-out-expo max-h-[22dvh] min-h-[96px] w-full resize-none overflow-y-auto rounded-xl border border-border/50 bg-surface-elevated p-4 text-sm leading-relaxed transition-shadow focus:border-primary/40 focus:shadow-glow focus:outline-none short:min-h-[64px]"
              />
              {/* WRAPS. `justify-between` with three inflexible children and no wrap is a
                  row that grows past its box rather than reflowing, and the box it grows past
                  is inside an `overflow-hidden` root — so at 320px, or at 200% zoom on a
                  laptop, "Submit & Next" left the right-hand edge and there was no scrollbar
                  to bring it back. Wrapping costs one extra line at those sizes and keeps the
                  only control that ends the question on screen. */}
              <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
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
                {/* The copy now matches what the microphone actually does. It used to say
                    "start talking again" after auto-closing in a state where it could not
                    re-open, which is the worst kind of interface lie: the one that makes a
                    candidate think they are the problem. */}
                {stt.error
                  ? 'Fix the permission, then tap to try again'
                  : stt.listening
                    ? handsFree
                      ? looksDone
                        ? 'Still listening — keep going, or submit when you are ready.'
                        : 'Listening — just talk.'
                      : 'Listening… tap to stop'
                    : tts.speaking && handsFree
                      ? 'Let them finish…'
                      : answer
                        ? 'Tap the mic to add more, or submit'
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

              {/*
                Live transcript — filler words in red, pauses marked.

                CAPPED, NOT `flex-1`. This is the fix for "when the answer gets long the
                submit button hides below".

                It read `min-h-[96px] flex-1 overflow-y-auto`, and the overflow rule never
                fired. `flex-1` only bounds a child when the flex PARENT has a bounded
                height, and this one is inside the answer channel, which is `flex-shrink-0`
                and therefore sized to its content. So `flex-1` resolved to "grow to fit",
                the box grew with every sentence the candidate spoke, the channel grew with
                it, and Submit & Next was pushed off the bottom of the viewport — at exactly
                the moment a candidate who had just given a long answer wanted to press it.

                An explicit max-height makes the scroll real: the transcript scrolls inside
                itself and the controls below it never move. In dvh — a ceiling in plain vh is
                measured against the viewport with the browser chrome hidden, so on a phone it
                is about 10% taller than it reads here, and that 10% comes out of the space the
                button row needs — and paired with min-h so a one-word answer does not collapse
                the box to nothing. The floor drops to 64px on a short viewport, because a
                floor that cannot come down while the ceiling keeps falling is a box that has
                stopped responding: 22dvh passes under 96px at about 437px of viewport height.
              */}
              <div className="min-h-[96px] max-h-[22dvh] w-full overflow-y-auto rounded-xl border border-border/50 bg-surface-elevated p-4 text-sm leading-relaxed short:min-h-[64px]">
                <DeliveryTranscript
                  text={answer}
                  pauses={stt.pauses}
                  interim={stt.listening ? stt.interim : ''}
                />
              </div>

              {/* WRAPS, for the reason given on the typing row above — and more urgently
                  here, because this row is the widest in the app: a sentence-long "Trouble
                  with the mic?" link, Clear, and Submit & Next need about 400px and a 320px
                  phone gives this pane about 250px. */}
              <div className="flex w-full flex-wrap items-center justify-between gap-3">
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
          </div>
        </motion.div>

        {/* ── MIDDLE: the compiler, permanently ───────────────────────────────
            On screen for EVERY question, not only the coding ones. That is the point of
            the redesign: in a real technical screen the editor is simply there, and you
            reach for it when you want to show something rather than being handed one when
            the interviewer decides this is now a coding question. On a theory question it
            is a scratchpad and says so; on a coding question it is the answer and says
            that instead. */}
        {/* NOT RENDERED AT ALL for a non-technical role, rather than rendered and hidden.
            The comment here used to claim that while the code applied a `hidden` class,
            which is not the same thing: a hidden pane still mounts CodeMirror, still pulls
            in every language mode, and still runs its effects — on a sales interview, for
            an editor nobody will ever open. */}
        {hasEditor && (
        <motion.div
          variants={fadeUp}
          className={cn(
            // `short:overflow-visible` hands the scrolling back to the page below 700px tall.
            // This pane holds a 320px editor, a stdin box and three buttons — comfortably more
            // than a zoomed viewport — and a pane that keeps its own scrollbar inside a page
            // that is already scrolling is two scroll areas over the same content, where a
            // touch gesture goes to whichever one the browser guesses.
            'glass min-h-0 overflow-y-auto rounded-2xl border-border/50 p-4 sm:p-5 short:overflow-visible',
            mobilePane === 'code' ? 'block' : 'hidden lg:block',
          )}
        >
          <div className="mb-4 flex items-center justify-between gap-2">
            <span className="text-sm font-semibold text-muted-foreground">
              {isCoding ? 'Your solution' : 'Compiler'}
            </span>
            {isCoding ? (
              <Badge variant="violet">This is your answer</Badge>
            ) : (
              <span className="text-[11px] text-muted-foreground/70">Scratchpad</span>
            )}
          </div>
          <CodingWorkspace
            disabled={preparing}
            submitting={submitAnswer.isPending}
            problemTitle={isCoding ? 'Coding question' : 'Scratchpad'}
            problemDescription={question?.content ?? ''}
            difficulty={question?.difficulty ?? 'medium'}
            onLanguageChange={setCodeLanguage}
            roleLabel={
              isCoding
                ? 'Write your solution here and submit it. Anil and Priya will read it and tell you what they find.'
                : 'Not the answer to this one — answer out loud. This is here to sketch on, the way you would use a whiteboard.'
            }
            // Submitting a scratchpad as an answer to a theory question would file code
            // against a question that asked for an explanation, and it would be scored as
            // one. Run and Review still work, which is what a scratchpad is for.
            hideSubmit={!isCoding}
            onSubmit={({ language, code }: { language: CodeLanguage; code: string }) =>
              submitContent(`\`\`\`${language}\n${code}\n\`\`\``)
            }
          />
        </motion.div>
        )}

        {/* ── RIGHT: you ──────────────────────────────────────────────────── */}
        <motion.div
          variants={fadeUp}
          className={cn(
            'min-h-0 overflow-y-auto short:overflow-visible',
            mobilePane === 'you' ? 'block' : 'hidden lg:block',
          )}
        >
          <PresenceMonitor onAlert={setPresence} />
        </motion.div>
      </motion.main>
    </div>
  );
}
