import { useMutation, useQuery } from '@tanstack/react-query';
import { getBrowserApiClient } from '@/lib/api';
import { useRouter } from 'next/navigation';

export interface InterviewPlan {
  session_id: string;
  topics: string[];
  question_count: number;
}

export function useNextQuestion(sessionId: string) {
  return useQuery({
    queryKey: ['interview', 'next-question', sessionId],
    queryFn: async () => {
      const response = await getBrowserApiClient().get(`/api/v1/interview/${sessionId}/next`);
      return response.data as {
        question: {
          id: string;
          content: string;
          type: string;
          difficulty: string;
          /**
           * This question came out of the candidate's last answer rather than from the plan.
           *
           * Decided server-side from the session's own `cross_question_ids` — the same record
           * the orchestrator keys its logic on, so there is no second derivation that could
           * disagree. The client uses it to pick the panel stage and to mark the thread; it
           * was not sent at all before, which is why follow-ups were indistinguishable from
           * new questions and the feature looked like it was not running.
           */
          is_follow_up?: boolean;
        } | null;
        message?: string;
      };
    },
    staleTime: 0,
    gcTime: 0,
    enabled: !!sessionId,
    // The interview flow must not retry-storm the user with "network error"
    // toasts — a single retry smooths over a transient blip, then we surface
    // a clean retry button in the UI.
    retry: 1,
  });
}

export interface PlanInput {
  trackId: string;
  company: string;
  program: string;
  prompt: string;
  resumeText: string;
  /** True when the candidate typed their own company instead of picking one. */
  customSetup?: boolean;
  /** Explicit technical/non-technical choice. null lets the backend infer from the role. */
  isTechnical?: boolean | null;
}

export function useInterview() {
  const api = getBrowserApiClient();
  const router = useRouter();

  // Legacy single-track quick start (kept for any direct entry points).
  const startSession = useMutation({
    mutationFn: async (trackId: string) => {
      const response = await api.post('/api/v1/interview/start', { track_id: trackId });
      return response.data as { session_id: string; status: string };
    },
    onSuccess: (data) => {
      router.push(`/session/${data.session_id}`);
    },
  });

  // Generate a company/program/resume-tailored plan for the candidate to review.
  // The AI call can take a while on the free-tier model, so this request gets a
  // generous timeout (the default 30s would abort it mid-generation).
  const createPlan = useMutation({
    mutationFn: async (input: PlanInput) => {
      const response = await api.post(
        '/api/v1/interview/plan',
        {
          track_id: input.trackId,
          company: input.company,
          program: input.program,
          prompt: input.prompt,
          resume_text: input.resumeText,
          // Tells the backend that the track_id above is a foreign-key carrier and nothing
          // more — the candidate typed their own employer, so the catalogue track must not
          // be read for the role, the company, the domain, or whether this is technical.
          custom_setup: input.customSetup ?? false,
          // null means "work it out from the role", which is right for a catalogue track.
          // true/false is the candidate saying so outright, and it overrides the inference.
          is_technical: input.isTechnical ?? null,
        },
        { timeout: 150_000 }
      );
      return response.data as InterviewPlan;
    },
  });

  // Approve the plan and begin the interview.
  const approvePlan = useMutation({
    mutationFn: async (sessionId: string) => {
      await api.post(`/api/v1/interview/${sessionId}/approve`, {});
      return sessionId;
    },
    onSuccess: (sessionId) => {
      router.push(`/session/${sessionId}`);
    },
  });

  // Record the answer. Scoring is deferred to the final report, so this just
  // confirms the answer was stored and the flow moves on immediately. Delivery
  // metrics (fillers, pauses, pace) are sent so the final report can analyse
  // how the candidate spoke across the whole interview.
  const submitAnswer = useMutation({
    mutationFn: async ({
      sessionId,
      questionId,
      content,
      delivery,
    }: {
      sessionId: string;
      questionId: string;
      content: string;
      delivery?: {
        filler_count: number;
        pause_count: number;
        total_pause_seconds: number;
        words: number;
        speaking_seconds: number;
        /** Where each pause fell, as a word offset — needed to render the
         *  answer back with hesitations marked, which a count cannot do. */
        pauses?: Array<{ wordIndex: number; seconds: number }>;
      };
    }) => {
      const response = await api.post(`/api/v1/interview/${sessionId}/answer`, {
        question_id: questionId,
        content,
        ...(delivery ? { delivery } : {}),
      });
      return response.data as {
        status: string;
        questions_answered: number;
        /**
         * The candidate declined rather than answered badly.
         *
         * Decided SERVER-side — the rule is subtle enough to need its own module and forty
         * tests (backend/app/services/interview/dont_know.py), and a client-side copy would
         * drift and start offering an easier topic in the middle of a correct answer.
         */
        declined?: boolean;
      };
    },
  });

  const completeSession = useMutation({
    mutationFn: async (sessionId: string) => {
      await api.post(`/api/v1/interview/${sessionId}/complete`, {});
    },
    onSuccess: (_, sessionId) => {
      router.push(`/report/${sessionId}`);
    },
  });

  return {
    startSession,
    createPlan,
    approvePlan,
    submitAnswer,
    completeSession,
    useNextQuestion,
  };
}
