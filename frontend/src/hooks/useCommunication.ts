import { useMutation, useQuery } from '@tanstack/react-query';
import { getBrowserApiClient } from '@/lib/api';

export interface CommunicationPrompt {
  id: number;
  text: string;
}

export interface ReadingPassage {
  id: number;
  title: string;
  text: string;
  seconds: number;
}

export interface CommunicationResult {
  clarity_score: number;
  structure_score: number;
  confidence_score: number;
  conciseness_score: number;
  overall_score: number;
  pace_feedback: string;
  filler_feedback: string;
  feedback: string;
  strengths: string[];
  improvements: string[];
  words_per_minute: number;
  filler_count: number;
  eye_contact_pct: number | null;
  pause_count: number;
  total_pause_seconds: number;
}

export interface EvaluateArgs {
  prompt_text: string;
  transcript: string;
  duration_seconds: number;
  filler_count: number;
  words_per_minute: number;
  eye_contact_pct?: number | null;
  pause_count?: number;
  total_pause_seconds?: number;
  mode?: 'speaking' | 'reading';
}

export function useCommunicationPrompts() {
  return useQuery({
    queryKey: ['communication', 'prompts'],
    queryFn: async () => {
      const res = await getBrowserApiClient().get('/api/v1/communication/prompts');
      return res.data as CommunicationPrompt[];
    },
    staleTime: 30 * 60 * 1000,
  });
}

export function useReadingPassages() {
  return useQuery({
    queryKey: ['communication', 'passages'],
    queryFn: async () => {
      const res = await getBrowserApiClient().get('/api/v1/communication/passages');
      return res.data as ReadingPassage[];
    },
    staleTime: 30 * 60 * 1000,
  });
}

export function useEvaluateCommunication() {
  return useMutation({
    mutationFn: async (args: EvaluateArgs) => {
      const res = await getBrowserApiClient().post('/api/v1/communication/evaluate', args);
      return res.data as CommunicationResult;
    },
  });
}

/** Fetch ONE spoken cross-question that probes the candidate's answer. */
export function useCommunicationCrossQuestion() {
  return useMutation({
    mutationFn: async (args: { prompt_text: string; transcript: string }) => {
      const res = await getBrowserApiClient().post(
        '/api/v1/communication/cross-question',
        args,
        { timeout: 60_000 }
      );
      return (res.data as { question: string }).question;
    },
  });
}

/** Common English filler words/phrases, counted from a transcript. */
const FILLERS = ['um', 'uh', 'erm', 'like', 'you know', 'basically', 'actually', 'literally', 'sort of', 'kind of', 'i mean'];

export function countFillers(transcript: string): number {
  const text = ` ${transcript.toLowerCase()} `;
  let count = 0;
  for (const f of FILLERS) {
    // Count word-boundary occurrences of each filler.
    const re = new RegExp(`\\b${f.replace(/ /g, '\\s+')}\\b`, 'g');
    count += (text.match(re) || []).length;
  }
  return count;
}

export function wordsPerMinute(transcript: string, seconds: number): number {
  const words = transcript.trim() ? transcript.trim().split(/\s+/).length : 0;
  if (seconds <= 0) return 0;
  return Math.round((words / seconds) * 60);
}
