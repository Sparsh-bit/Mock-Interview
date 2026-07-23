import { useMutation, useQuery } from '@tanstack/react-query';
import { getBrowserApiClient } from '@/lib/api';

export interface GDTopic {
  id: number;
  text: string;
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

export function useGD() {
  const api = getBrowserApiClient();

  const panelTurn = useMutation({
    mutationFn: async (args: { topic: string; history: GDTurn[] }) => {
      const res = await api.post('/api/v1/gd/turn', args);
      return res.data as { contributions: GDTurn[] };
    },
  });

  const evaluate = useMutation({
    mutationFn: async (args: { topic: string; history: GDTurn[] }) => {
      const res = await api.post('/api/v1/gd/evaluate', args);
      return res.data as GDEvaluation;
    },
  });

  return { panelTurn, evaluate };
}
