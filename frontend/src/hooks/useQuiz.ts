import { useMutation, useQuery } from '@tanstack/react-query';
import { getBrowserApiClient } from '@/lib/api';

export interface BankTopic {
  topic: string;
  count: number;
}

export interface QuizQuestion {
  id: string;
  question: string;
  options: string[];
  topic: string;
  difficulty: string;
}

export interface StartQuizResponse {
  quiz_id: string;
  minutes: number;
  questions: QuizQuestion[];
}

export interface QuizResultItem {
  question_id: string;
  question: string;
  options: string[];
  correct_index: number;
  selected_index: number | null;
  is_correct: boolean;
  explanation: string;
  topic: string;
}

export interface SubmitQuizResponse {
  score: number;
  total: number;
  percentage: number;
  results: QuizResultItem[];
}

export function useQuiz() {
  const api = getBrowserApiClient();

  const startQuiz = useMutation({
    mutationFn: async (opts: {
      trackId?: string;
      count: number;
      minutes: number;
      topic?: string;
      company?: string;
    }) => {
      const res = await api.post('/api/v1/quiz/start', {
        track_id: opts.trackId ?? null,
        count: opts.count,
        minutes: opts.minutes,
        topic: opts.topic?.trim() || null,
        company: opts.company?.trim() || null,
      });
      return res.data as StartQuizResponse;
    },
  });

  const startBankQuiz = useMutation({
    mutationFn: async (opts: { topic?: string; count: number; minutes: number }) => {
      const res = await api.post('/api/v1/quiz/bank/start', {
        topic: opts.topic || null,
        count: opts.count,
        minutes: opts.minutes,
      });
      return res.data as StartQuizResponse;
    },
  });

  const submitQuiz = useMutation({
    mutationFn: async (opts: { quizId: string; answers: Record<string, number> }) => {
      const res = await api.post(`/api/v1/quiz/${opts.quizId}/submit`, { answers: opts.answers });
      return res.data as SubmitQuizResponse;
    },
  });

  return { startQuiz, startBankQuiz, submitQuiz };
}

export function useBankTopics() {
  return useQuery({
    queryKey: ['quiz', 'bank-topics'],
    queryFn: async () => {
      const res = await getBrowserApiClient().get('/api/v1/quiz/bank/topics');
      return res.data as BankTopic[];
    },
    staleTime: 30 * 60 * 1000,
  });
}
