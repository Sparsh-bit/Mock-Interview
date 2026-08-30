import { useMutation, useQuery } from '@tanstack/react-query';

import { getBrowserApiClient } from '@/lib/api';
import type { SpeechTone } from '@/lib/speech/neural-tts';

/**
 * The two-person interview panel — hooks/useInterviewPanel.ts
 *
 * A real campus interview is two or three people who know each other, who talk to each other
 * as much as to you, who correct you on the spot when you are wrong, and who at the end ask
 * whether you have anything to ask them. This is the client half of that.
 *
 * IT WRAPS THE QUESTION, IT DOES NOT REPLACE IT. The orchestrator still chooses which
 * question to ask — all the adaptive selection, per-session question ownership and
 * cross-question scoping is untouched. This asks "what do the two of them say around it".
 *
 * SO IT MUST BE ALLOWED TO FAIL. Every call here returns empty rather than throwing, and the
 * caller falls back to showing the question on its own. The panel is presentation; a
 * presentation failure must never cost somebody their interview.
 */

export interface Interviewer {
  name: string;
  gender: string;
  role: string;
  /** Prose persona, for reference — too long to render. */
  disposition: string;
}

export interface PanelLine {
  speaker: string;
  text: string;
  /**
   * How the line is delivered — see SpeechTone.
   *
   * Tagged by the model, not inferred here. The model is the only thing that knows which
   * of its own lines is the correction and which is an aside to the other interviewer;
   * recovering that from the text with keywords would be guessing at something it already
   * decided. Optional so an older backend simply yields flat delivery rather than an error.
   */
  tone?: SpeechTone;
}

/**
 * Where the interview is. Drives which behaviour the panel follows.
 *
 *   opening              greet, both introduce themselves, first question
 *   mid                  correction where earned, handover, next question
 *   follow_up            the question comes out of their last answer — stay on the thread
 *   wrapping             the senior one asks the other if they have anything left
 *   candidate_questions  "Do you have any questions for us?"
 *   answering_candidate  the candidate asked something — answer it properly
 */
export type PanelStage =
  | 'opening'
  | 'skill_check'
  | 'mid'
  // The next question came out of their last answer. Kept distinct from `mid` because a
  // follow-up introduced as a fresh question is indistinguishable from one — which wastes
  // the single moment the interview visibly listened to them.
  | 'follow_up'
  | 'pivot'
  // The candidate asked the panel something instead of answering. The panel answers it in a
  // line and re-puts the SAME question — see backend/app/prompts/interview_panel.md.
  | 'off_script'
  | 'code_review'
  | 'wrapping'
  | 'candidate_questions'
  | 'answering_candidate';

export interface PanelTurnArgs {
  session_id: string;
  stage: PanelStage;
  /** The question the orchestrator chose. Empty for stages that do not ask one. */
  question?: string;
  /** What the candidate last said, so a wrong answer can be corrected in the room. */
  last_answer?: string;
  /**
   * The expected concepts for the LAST question.
   *
   * This is what keeps a correction honest: the server grounds it in the bank's own answer
   * rather than whatever the model recalls, and the prompt refuses to invent one when this is
   * missing. A correction that is itself wrong is worse than none in a product that teaches.
   */
  last_expected?: string;
  /** What the candidate asked, for the answering_candidate stage. */
  candidate_question?: string;
  candidate_name?: string;
  /** For code_review: which language the editor was set to. The code itself is read
   *  server-side from the submitted answer, never sent from here. */
  language?: string;
}

export interface PanelTurnResult {
  turns: PanelLine[];
  /** True when one of these turns actually put the supplied question to the candidate. */
  asked_question: boolean;
  /**
   * For the pivot stage: the topic the panel offered instead.
   *
   * Chosen by the SERVER. It is the only side that knows what this session has already
   * covered, and a client-chosen pivot could hand a candidate back the very topic they just
   * declined — which would be worse than not offering one.
   */
  pivot_topic?: string;
  /**
   * For the skill_check stage: what the panel asked them to rate themselves on.
   *
   * Chosen by the SERVER from the role — a sales candidate is asked about sales, not Java.
   * Recorded alongside the number so the report can say which subject a 7 refers to.
   */
  rating_subject?: string;
  /**
   * The panel's read of what the candidate last said: "answered" (almost always),
   * "off_topic", "unintelligible", "other_language", "asked_us" or "adversarial".
   *
   * The model's judgement, not a keyword match — only it can see that an answer was about the
   * wrong thing. Defaults to "answered" whenever the panel could not speak, because recording
   * that somebody failed to answer on the strength of a provider outage would be a lie.
   */
  candidate_turn?: string;
}

/**
 * Who is on the panel.
 *
 * Fetched rather than hardcoded, for the same reason the GD roster is: the names appear in the
 * prompt, the transcript and the voice allocation, and a frontend copy that drifts means Priya
 * speaks in Anil's voice or a line from an unknown speaker is silently dropped.
 */
/**
 * Who is on the panel, and whether this is a technical interview.
 *
 * `technical` is what decides whether a code editor exists at all. A sales candidate has no
 * use for one, and showing it says the simulation has not understood the role — the same
 * class of mistake as asking them to rate themselves in Java.
 */
export interface PanelInfo {
  interviewers: Interviewer[];
  technical: boolean;
}

export function useInterviewers(sessionId?: string) {
  return useQuery({
    // Keyed by session, because the DESIGNATIONS depend on the role: a sales interview is run
    // by a Regional Sales Manager, not a Technical Lead. Sharing one cache entry across
    // sessions would show whichever role loaded first.
    queryKey: ['panel', 'interviewers', sessionId ?? 'default'],
    queryFn: async () => {
      const res = await getBrowserApiClient().get(
        sessionId
          ? `/api/v1/panel/interviewers?session_id=${encodeURIComponent(sessionId)}`
          : '/api/v1/panel/interviewers',
      );
      return res.data as PanelInfo;
    },
    // Still Infinity: names, genders and designations are fixed for the life of a session, and
    // the voice allocation downstream keys off the names.
    staleTime: Infinity,
  });
}

export function useInterviewPanel() {
  const api = getBrowserApiClient();

  const turn = useMutation({
    mutationFn: async (args: PanelTurnArgs): Promise<PanelTurnResult> => {
      try {
        const res = await api.post('/api/v1/panel/turn', args, { timeout: 20_000 });
        return res.data as PanelTurnResult;
      } catch {
        // Empty, not an error. The caller shows the question on its own and the interview
        // continues — see the note at the top of this file.
        return { turns: [], asked_question: false, pivot_topic: '', rating_subject: '' };
      }
    },
  });

  return { turn };
}

/**
 * Record the candidate's own estimate of their Java level.
 *
 * The rating moves the questions they get AND the expectation the report judges them
 * against — see set_self_rating in backend/app/api/v1/interview.py for why it has to move
 * both, or claiming 2/10 every time would be the optimal play.
 */
export function useSelfRating(sessionId: string) {
  return useMutation({
    mutationFn: async (args: { rating: number; subject: string; strengths: string[] }) => {
      const res = await getBrowserApiClient().post(
        `/api/v1/interview/${sessionId}/self-rating`,
        args,
      );
      return res.data as { status: string };
    },
  });
}

/**
 * Record that the candidate declined a topic and was offered another.
 *
 * The anti-farming half of the pivot. Without this, "I don't know" is a free instruction to
 * serve easier questions; with it, every pivot is on the session and the report counts them.
 * Fire-and-forget by design — a failure to record must not stall the interview, and one
 * unrecorded pivot is a far smaller problem than a candidate stuck on a spinner.
 */
export function useRecordPivot(sessionId: string) {
  return useMutation({
    mutationFn: async (args: {
      declined_question: string;
      offered_topic: string;
      accepted: boolean;
    }) => {
      try {
        await getBrowserApiClient().post(`/api/v1/interview/${sessionId}/pivot`, args);
      } catch {
        // Deliberately swallowed — see above.
      }
    },
  });
}
