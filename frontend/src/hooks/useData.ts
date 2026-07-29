'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getBrowserApiClient } from '@/lib/api';

export interface Track {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  difficulty_level: string;
  duration_minutes: number;
  /** Size of the track's question bank. */
  question_count: number;
  /** How many questions an interview actually asks — show this to users. */
  interview_question_count: number;
  company: {
    id: string;
    name: string;
    slug: string;
    logo_url: string | null;
  };
}

export interface UserStats {
  total_sessions: number;
  completed_sessions: number;
  average_score: number | null;
  total_questions_answered: number;
  hours_practiced: number;
  best_score: number | null;
  streak_days: number;
}

export interface SessionSummary {
  id: string;
  track_name: string;
  company_name: string;
  program: string | null;
  topics: string[];
  status: string;
  mode: string;
  questions_asked: number;
  overall_score: number | null;
  started_at: string | null;
  completed_at: string | null;
  duration_seconds: number | null;
}

export interface UserProfile {
  user_id: string;
  full_name: string | null;
  avatar_url: string | null;
  bio: string | null;
  target_company: string | null;
  experience_years: number | null;
  linkedin_url: string | null;
  github_url: string | null;
  timezone: string;
  updated_at: string;
}

export interface QuestionAnalysis {
  question_id: string;
  question: string;
  answer_quality: string;
  score: number;
  missing_concepts: string[];
  ideal_answer_summary: string;
}

export interface ReportData {
  id: string;
  session_id: string;
  overall_score: number;
  overall_score_label: string;
  executive_summary: string;
  readiness_level: string;
  readiness_reasoning: string;
  strengths: string[];
  weaknesses: string[];
  topic_scores: Record<string, number>;
  dimension_scores: Record<string, number>;
  performance_percentile: number;
  question_analysis: QuestionAnalysis[];
  improvement_roadmap: Array<{
    priority: number;
    topic: string;
    current_score: number;
    target_score: number;
    study_hours_estimate: number;
    resources: Array<{
      type: string;
      title: string;
      url: string | null;
      author: string | null;
    }>;
  }>;
  is_shared: boolean;
  created_at: string;
  pdf_url: string | null;
  delivery: {
    filler_count?: number;
    pause_count?: number;
    total_pause_seconds?: number;
    words?: number;
    speaking_seconds?: number;
    wpm?: number;
    answers?: number;
  } | null;
  previous: {
    overall_score: number;
    readiness_level: string;
    created_at: string | null;
  } | null;
}

export function useTracks() {
  return useQuery({
    queryKey: ['tracks'],
    queryFn: async () => {
      const api = getBrowserApiClient();
      const res = await api.get('/api/v1/questions/tracks');
      return res.data as Track[];
    },
    // Reference data: changes on deploy, not per session. Serving it from cache
    // for the session avoids a backend round trip on nearly every navigation.
    staleTime: 30 * 60 * 1000,
    gcTime: 60 * 60 * 1000,
  });
}

export function useUserStats() {
  return useQuery({
    queryKey: ['user-stats'],
    queryFn: async () => {
      const api = getBrowserApiClient();
      const res = await api.get('/api/v1/users/me/stats');
      return res.data as UserStats;
    },
    // Keep the previous numbers on screen while refetching instead of falling
    // back to spinners — on a slow backend that flicker is most of the
    // "everything is loading again" feeling.
    placeholderData: (prev) => prev,
    staleTime: 5 * 60 * 1000,
  });
}

export function useUserSessions(limit: number = 10) {
  return useQuery({
    queryKey: ['user-sessions', limit],
    queryFn: async () => {
      const api = getBrowserApiClient();
      const res = await api.get(`/api/v1/users/me/sessions?limit=${limit}`);
      return res.data as SessionSummary[];
    },
    placeholderData: (prev) => prev,
    staleTime: 2 * 60 * 1000,
  });
}

export function useUserProfile() {
  return useQuery({
    queryKey: ['user-profile'],
    queryFn: async () => {
      const api = getBrowserApiClient();
      const res = await api.get('/api/v1/users/me/profile');
      return res.data as UserProfile;
    },
    placeholderData: (prev) => prev,
    staleTime: 10 * 60 * 1000,
  });
}

export function useUpdateProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (data: Partial<{
      full_name: string;
      bio: string;
      target_company: string;
      experience_years: number;
      linkedin_url: string;
      github_url: string;
      timezone: string;
    }>) => {
      const api = getBrowserApiClient();
      const res = await api.patch('/api/v1/users/me/profile', data);
      return res.data as UserProfile;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['user-profile'] });
    },
  });
}

export function useReport(sessionId: string) {
  return useQuery({
    queryKey: ['report', sessionId],
    queryFn: async () => {
      const api = getBrowserApiClient();

      // One call. `generate` is idempotent — it returns the existing report if
      // there is one and creates it otherwise — so there is nothing to probe
      // for first. Probing with a GET meant the normal path (no report yet)
      // logged a 404 in the console on every first view, and a 404 cannot be
      // suppressed from JavaScript: the browser records it at the network layer.
      //
      // 120s outlasts the server's own ceiling. The server caps AI generation at
      // 50s and the host gateway cuts anything past ~100s, so the client is never
      // the first to give up and a timeout here always means a real failure.
      try {
        const res = await api.post(
          `/api/v1/reports/${sessionId}/generate`,
          {},
          { timeout: 120_000 },
        );
        return res.data as ReportData;
      } catch (err: unknown) {
        // If we stopped waiting, the server may still have committed the report.
        // Looking once more is a cheap read, never a second billed generation.
        if ((err as { isTimeout?: boolean })?.isTimeout === true) {
          const retry = await api.get(`/api/v1/reports/${sessionId}`).catch(() => null);
          if (retry) return retry.data as ReportData;
        }
        throw err;
      }
    },
    enabled: !!sessionId,
    // Generation is a billed AI call; never retry it automatically.
    retry: false,
  });
}

export function useToggleShareReport() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (reportId: string) => {
      const api = getBrowserApiClient();
      const res = await api.patch(`/api/v1/reports/${reportId}/share`, {});
      return res.data as { is_shared: boolean; report_id: string };
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['report'] });
    },
  });
}

export interface StoredResume {
  id: string;
  filename: string;
  file_size_bytes: number;
  mime_type: string;
  is_primary: boolean;
  /** "completed" | "text_only" | "failed" | "pending" */
  parsing_status: string;
  parsed_skills: string[] | null;
  created_at: string;
  parsing_error: string | null;
  /** Whether readable text was extracted — this, not parsing_status, decides
   *  whether an interview can be personalised at all. */
  has_text: boolean;
  project_count: number;
  priority_topics: string[];
}

/** The candidate's active resume, or null if they have not uploaded one. */
export function usePrimaryResume() {
  return useQuery({
    queryKey: ['resume', 'primary'],
    queryFn: async () => {
      const api = getBrowserApiClient();
      const res = await api.get('/api/v1/resume/primary');
      return (res.data ?? null) as StoredResume | null;
    },
    staleTime: 5 * 60 * 1000,
  });
}

export function useUploadResume() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (file: File) => {
      const api = getBrowserApiClient();
      const form = new FormData();
      form.append('file', file);
      // Generous timeout: the request extracts the text AND runs the AI analysis
      // before responding, so it is bounded by the server's 45s analysis budget
      // rather than by network latency.
      const res = await api.post('/api/v1/resume/upload', form, { timeout: 120_000 });
      return res.data as StoredResume;
    },
    onSuccess: () => {
      // Both the active resume and the full list change: the new upload becomes
      // primary and demotes the previous one.
      queryClient.invalidateQueries({ queryKey: ['resume'] });
    },
  });
}

export function useDeleteResume() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (resumeId: string) => {
      const api = getBrowserApiClient();
      await api.delete(`/api/v1/resume/${resumeId}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['resume'] });
    },
  });
}

export interface AnalysedAnswer {
  answer_id: string;
  question_id: string;
  question: string;
  question_type: string;
  topic: string;
  /** Exactly what the candidate said — never tidied up. */
  answer: string;
  answered_at: string;
  delivery: {
    filler_count: number;
    pause_count: number;
    total_pause_seconds: number;
    words: number;
    speaking_seconds: number;
    pauses: Array<{ wordIndex: number; seconds: number }>;
  } | null;
  model_answer: {
    model_answer: string;
    what_was_missing: string[];
    key_points: string[];
    verdict_line: string;
  } | null;
  is_coding: boolean;
}

export interface DetailedAnalysis {
  session_id: string;
  track_name: string;
  company_name: string;
  completed_at: string | null;
  answers: AnalysedAnswer[];
}

/** Every question with the candidate's verbatim answer. Free — no AI call. */
export function useDetailedAnalysis(sessionId: string) {
  return useQuery({
    queryKey: ['analysis', sessionId],
    queryFn: async () => {
      const api = getBrowserApiClient();
      const res = await api.get(`/api/v1/analysis/${sessionId}`);
      return res.data as DetailedAnalysis;
    },
    enabled: !!sessionId,
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * Generate the model answer for one answer.
 *
 * `retry: false` deliberately — this is a billed AI call, so a transient failure
 * must not silently become three charges.
 */
export function useGenerateModelAnswer(sessionId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (answerId: string) => {
      const api = getBrowserApiClient();
      const res = await api.post(
        `/api/v1/analysis/${sessionId}/answers/${answerId}/model-answer`,
        {},
        { timeout: 90_000 },
      );
      return res.data as AnalysedAnswer['model_answer'] & { answer_id: string; cached: boolean };
    },
    retry: false,
    onSuccess: (result) => {
      // Write it into the cached analysis so it stays visible without a refetch.
      queryClient.setQueryData<DetailedAnalysis>(['analysis', sessionId], (prev) =>
        prev
          ? {
              ...prev,
              answers: prev.answers.map((a) =>
                a.answer_id === result.answer_id
                  ? {
                      ...a,
                      model_answer: {
                        model_answer: result.model_answer,
                        what_was_missing: result.what_was_missing,
                        key_points: result.key_points,
                        verdict_line: result.verdict_line,
                      },
                    }
                  : a,
              ),
            }
          : prev,
      );
    },
  });
}
