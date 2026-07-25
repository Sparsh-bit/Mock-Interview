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
  question_count: number;
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
      try {
        const res = await api.get(`/api/v1/reports/${sessionId}`);
        return res.data as ReportData;
      } catch (err: any) {
        if (err.status === 404 || err.response?.status === 404) {
          const genRes = await api.post(`/api/v1/reports/${sessionId}/generate`, {});
          return genRes.data as ReportData;
        }
        throw err;
      }
    },
    enabled: !!sessionId,
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
