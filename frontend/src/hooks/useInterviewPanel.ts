import { useMutation, useQuery } from '@tanstack/react-query';

import { getBrowserApiClient } from '@/lib/api';

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
}

/**
 * Where the interview is. Drives which behaviour the panel follows.
 *
 *   opening              greet, both introduce themselves, first question
 *   mid                  correction where earned, handover, next question
 *   wrapping             the senior one asks the other if they have anything left
 *   candidate_questions  "Do you have any questions for us?"
 *   answering_candidate  the candidate asked something — answer it properly
 */
export type PanelStage =
  | 'opening'
  | 'mid'
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
}

export interface PanelTurnResult {
  turns: PanelLine[];
  /** True when one of these turns actually put the supplied question to the candidate. */
  asked_question: boolean;
}

/**
 * Who is on the panel.
 *
 * Fetched rather than hardcoded, for the same reason the GD roster is: the names appear in the
 * prompt, the transcript and the voice allocation, and a frontend copy that drifts means Priya
 * speaks in Anil's voice or a line from an unknown speaker is silently dropped.
 */
export function useInterviewers() {
  return useQuery({
    queryKey: ['panel', 'interviewers'],
    queryFn: async () => {
      const res = await getBrowserApiClient().get('/api/v1/panel/interviewers');
      return res.data as Interviewer[];
    },
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
        return { turns: [], asked_question: false };
      }
    },
  });

  return { turn };
}
