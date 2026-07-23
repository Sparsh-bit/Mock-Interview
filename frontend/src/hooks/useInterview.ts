import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { getBrowserApiClient } from '@/lib/api';
import { useRouter } from 'next/navigation';

export function useNextQuestion(sessionId: string) {
  return useQuery({
    queryKey: ['interview', 'next-question', sessionId],
    queryFn: async () => {
      const response = await getBrowserApiClient().get(`/api/v1/interview/${sessionId}/next`);
      return response.data as { question: any | null; message?: string };
    },
    staleTime: 0,
    gcTime: 0,
    enabled: !!sessionId,
  });
}

export function useInterview() {
  const api = getBrowserApiClient();
  const router = useRouter();
  const queryClient = useQueryClient();

  const startSession = useMutation({
    mutationFn: async (trackId: string) => {
      const response = await api.post('/api/v1/interview/start', { track_id: trackId });
      return response.data as { session_id: string; status: string };
    },
    onSuccess: (data) => {
      router.push(`/session/${data.session_id}`);
    }
  });

  const submitAnswer = useMutation({
    mutationFn: async ({ sessionId, questionId, content }: { sessionId: string; questionId: string; content: string }) => {
      const response = await api.post(`/api/v1/interview/${sessionId}/answer`, {
        question_id: questionId,
        content
      });
      return response.data as {
        technical_score: number;
        communication_score: number;
        completeness_score: number;
        confidence_score: number;
        overall_score: number;
        strengths: string[];
        weaknesses: string[];
        feedback: string;
        is_bluffing_detected: boolean;
      };
    }
  });

  const completeSession = useMutation({
    mutationFn: async (sessionId: string) => {
      await api.post(`/api/v1/interview/${sessionId}/complete`, {});
    },
    onSuccess: (_, sessionId) => {
      router.push(`/report/${sessionId}`);
    }
  });

  return {
    startSession,
    submitAnswer,
    completeSession,
    useNextQuestion,
  };
}
