import { useMutation, useQuery } from '@tanstack/react-query';
import { getBrowserApiClient } from '@/lib/api';

export interface GDTopic {
  id: number;
  text: string;
  /** Technology | Work | Business | Society | Ethics — panels rotate between them. */
  category: string;
}

/**
 * A panelist as the SERVER defines them.
 *
 * Fetched rather than hardcoded here: the names appear in the prompt, the
 * transcript, the voice allocation and the evaluation, and a frontend copy that
 * drifts means "Riya" speaks in Arjun's voice or a contribution from an unknown
 * panelist is silently dropped.
 */
export interface GDPanelist {
  name: string;
  gender: string;
  stance: string;
}

/** A custom topic, turned into a discussable motion with both sides argued. */
export interface GDPreparedTopic {
  statement: string;
  framing: string;
  points_for: string[];
  points_against: string[];
  usable: boolean;
  reason: string;
}

export interface GDTurn {
  speaker: string;
  text: string;
}

export interface GDEvaluation {
  contribution_score: number;
  relevance_score: number;
  clarity_score: number;
  engagement_score: number;
  overall_score: number;
  feedback: string;
  strengths: string[];
  improvements: string[];
}

export function useGDTopics() {
  return useQuery({
    queryKey: ['gd', 'topics'],
    queryFn: async () => {
      const res = await getBrowserApiClient().get('/api/v1/gd/topics');
      return res.data as GDTopic[];
    },
    staleTime: 30 * 60 * 1000,
  });
}

/** Where the discussion is in its lifecycle — drives how the panel behaves. */
export type GDPhase = 'opening' | 'discussion' | 'closing';

export interface GDTurnArgs {
  topic: string;
  history: GDTurn[];
  /** The panel already asked the candidate something and is still waiting. */
  awaiting_candidate?: boolean;
  /** Direct questions the candidate has left unanswered (2+ → panel moves on). */
  ignored_questions?: number;
  /** Seconds since the candidate last spoke. */
  candidate_silent_seconds?: number;
  phase?: GDPhase;
  /** The candidate's first name, so the panel can address them by it. */
  candidate_name?: string;
}

export function useGDPanel() {
  return useQuery({
    queryKey: ['gd', 'panel'],
    queryFn: async () => {
      const res = await getBrowserApiClient().get('/api/v1/gd/panel');
      return res.data as GDPanelist[];
    },
    staleTime: Infinity,
  });
}

export function useGD() {
  const api = getBrowserApiClient();

  /** Turn a candidate's own topic into a motion with both sides prepared. */
  const prepareTopic = useMutation({
    mutationFn: async (topic: string) => {
      const res = await api.post('/api/v1/gd/prepare', { topic });
      return res.data as GDPreparedTopic;
    },
  });

  const panelTurn = useMutation({
    mutationFn: async (args: GDTurnArgs) => {
      const res = await api.post('/api/v1/gd/turn', args);
      return res.data as { contributions: GDTurn[]; addressed_candidate: boolean };
    },
  });

  const evaluate = useMutation({
    mutationFn: async (args: {
      topic: string;
      history: GDTurn[];
      ignored_questions?: number;
    }) => {
      const res = await api.post('/api/v1/gd/evaluate', args);
      return res.data as GDEvaluation;
    },
  });

  return { panelTurn, evaluate, prepareTopic };
}
