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
  /**
   * Null on a real report. On an unscored one, WHY generation did not finish.
   * The report page shows a different message per value — one generic
   * "temporarily unavailable" told a candidate who had used their day's practice
   * exactly the same thing as one hitting an outage, and only one of those has an
   * action they can take.
   */
  unscored_reason?: 'user_quota' | 'service_limit' | 'timeout' | 'provider_unavailable' | null;
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
    /** Career-ending language only — casual words never reach here. */
    unprofessional_count?: number;
    unprofessional_words?: string[];
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

/**
 * Read a report. NEVER generates one.
 *
 * A BILLED AI CALL MUST NOT LIVE IN A QUERY, and it did: this used to POST to `/generate` as
 * its `queryFn`, on the reasoning that generate is idempotent so one call is simpler than a
 * probe. Idempotent is not the same as free. React Query owns when a query runs — it refetches
 * on mount and whenever the data is stale — so with `staleTime` at a minute, a candidate who
 * opened their report, went to Detailed Analysis and came back triggered ANOTHER paid
 * generation. For a report that had not scored, `should_regenerate` says yes every time, so
 * each of those was a real model call.
 *
 * Reported as "the generate again button is triggering by itself as it is exhausting my api",
 * and it is also the likeliest reason the daily spend cap was hit — after which every provider
 * refuses and every candidate is told the model was unreachable. One bug, two symptoms, and
 * the expensive one was invisible.
 *
 * So: reads are queries and billed writes are mutations. A GET costs nothing and is safe to
 * repeat as often as React Query likes. The 404 this produces on a first view is the cost of
 * that separation and it is worth paying — a line in the console is cheaper than ₹11 of
 * generation per tab switch.
 */
export function useReport(sessionId: string) {
  return useQuery({
    queryKey: ['report', sessionId],
    queryFn: async () => {
      const api = getBrowserApiClient();
      try {
        const res = await api.get(`/api/v1/reports/${sessionId}`);
        return res.data as ReportData;
      } catch (err: unknown) {
        // NO REPORT YET IS NOT AN ERROR. It is the state a candidate is in the moment they
        // finish, and the caller turns it into "generate one" rather than an error card.
        if ((err as { status?: number })?.status === 404) return null;
        throw err;
      }
    },
    enabled: !!sessionId,
    retry: false,
  });
}

/**
 * Generate a report. A BILLED AI CALL, so it is a mutation and fires only when something asks.
 *
 * The server is idempotent — it returns an existing scored report untouched — so calling this
 * twice cannot produce two reports. What it can produce is two BILLS, which is why nothing
 * calls it on a timer, on a focus, or on a mount.
 */
export function useGenerateReport(sessionId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const api = getBrowserApiClient();
      // 120s outlasts the server's own ceiling: it caps AI generation at 85s and the host
      // gateway cuts anything past ~100s, so the client is never the first to give up and a
      // timeout here always means a real failure.
      try {
        const res = await api.post(`/api/v1/reports/${sessionId}/generate`, {}, { timeout: 120_000 });
        return res.data as ReportData;
      } catch (err: unknown) {
        const e = err as { isTimeout?: boolean; status?: number };
        // If we stopped waiting, the server may still have committed it. Looking once more is
        // a cheap read, never a second billed generation.
        if (e?.isTimeout === true) {
          const retry = await api.get(`/api/v1/reports/${sessionId}`).catch(() => null);
          if (retry) return retry.data as ReportData;
        }
        // 429 — this account has generated a lot of reports this hour. If one already exists,
        // SHOW IT: the limit is on making new reports, not on reading finished ones.
        if (e?.status === 429) {
          const existing = await api.get(`/api/v1/reports/${sessionId}`).catch(() => null);
          if (existing) return existing.data as ReportData;
        }
        throw err;
      }
    },
    // Never retried automatically: every attempt is money.
    retry: false,
    onSuccess: (data) => {
      queryClient.setQueryData(['report', sessionId], data);
    },
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
  /** "completed" | "partial" | "text_only" | "failed" | "pending".
   *  "partial" means one half of the analysis landed and the other did not — the
   *  server requests skills and projects as two independent calls, so skills
   *  without projects is a real outcome and is not reported as "completed". */
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

/**
 * Whether this account has consented to its resume being processed.
 *
 * READ RATHER THAN REMEMBERED IN THE BROWSER. localStorage would survive a withdrawal made on
 * another device and would be wrong in the direction that matters — showing no prompt to
 * somebody who has withdrawn. The server is the only thing that knows, and the upload
 * endpoint enforces it regardless of what this returns.
 */
export function useResumeConsent() {
  return useQuery({
    queryKey: ['legal', 'consent'],
    queryFn: async () => {
      const api = getBrowserApiClient();
      const res = await api.get<{
        consents: { purpose: string; granted: boolean | null }[];
      }>('/api/v1/legal/consent');
      const row = res.data.consents.find((c) => c.purpose === 'resume_processing');
      // `null` means never asked, which is not consent. Only an explicit grant is.
      return row?.granted === true;
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
      // before responding, so it is bounded by the server's analysis budget
      // (RESUME_ANALYSIS_BUDGET_SECONDS, 35s) plus the storage write and DB insert,
      // rather than by network latency. Kept well above that: a client that gives up
      // first turns a successful upload into an error the candidate cannot act on.
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

// ─── Campus recruiters & roadmaps ─────────────────────────────────────────────

export interface RecruiterProgram { name: string; detail: string }
export interface RecruiterTopic { name: string; weight: number }

export interface Recruiter {
  slug: string;
  name: string;
  short: string;
  /** "mass_recruiter" | "consulting" | "product" */
  tier: string;
  hires_per_year: string;
  drive_window: string;
  eligibility: string;
  /** What this firm actually builds and sells — used to frame the plan page. */
  business_context: string;
  accent: string;
  programs: RecruiterProgram[];
  rounds: string[];
  topics: RecruiterTopic[];
}

export interface StudyResource {
  title: string;
  /** Absent for exercises — those are instructions, not links. */
  url: string | null;
  author: string | null;
  /** practice | reference | docs | book | course | exercise */
  kind: string;
  /** free | freemium | paid */
  cost: string;
  note: string;
}

export interface RoadmapTopic {
  name: string;
  weight: number;
  hours: number;
  phase: number;
  resources: StudyResource[];
  subtopics: Subtopic[];
}
export interface RoadmapPhase {
  phase: number;
  title: string;
  starts_on: string;
  ends_on: string;
  topics: RoadmapTopic[];
  hours: number;
}
export interface Roadmap {
  company_slug: string;
  company_name: string;
  weeks: number;
  hours_per_week: number;
  total_hours: number;
  target_date: string;
  phases: RoadmapPhase[];
  /** Topics the budget could not fund. Non-empty means the plan is a triage. */
  omitted_topics: string[];
  /** Set when the time available cannot cover the syllabus. */
  feasibility_warning: string | null;
  disclaimer: string;
}

/** The recruiter catalogue. Reference data — cached hard, it changes on deploy. */
export function useRecruiters() {
  return useQuery({
    queryKey: ['recruiters'],
    queryFn: async () => {
      const res = await getBrowserApiClient().get('/api/v1/companies');
      return res.data as Recruiter[];
    },
    staleTime: 60 * 60 * 1000,
    gcTime: 2 * 60 * 60 * 1000,
  });
}

/**
 * A dated study plan for one recruiter.
 *
 * Not cached across parameter changes by accident: weeks and hours are in the key,
 * so dragging the sliders refetches rather than showing a stale plan.
 */
export function useRoadmap(slug: string | null, weeks: number, hoursPerWeek: number) {
  return useQuery({
    queryKey: ['roadmap', slug, weeks, hoursPerWeek],
    queryFn: async () => {
      const res = await getBrowserApiClient().get(
        `/api/v1/companies/${slug}/roadmap?weeks=${weeks}&hours_per_week=${hoursPerWeek}`,
      );
      return res.data as Roadmap;
    },
    enabled: !!slug,
    staleTime: 10 * 60 * 1000,
    placeholderData: (prev) => prev,
  });
}

export interface SubtopicLink { title: string; url: string; channel?: string | null }
export interface Subtopic {
  id: string;
  name: string;
  minutes: number;
  video: SubtopicLink | null;
  doc: SubtopicLink | null;
  practice: SubtopicLink | null;
}

export interface PrepProgress {
  completed: string[];
  minutes_done: number;
}

/** Everything the candidate has ticked off, across every company plan. */
export function usePrepProgress() {
  return useQuery({
    queryKey: ['prep-progress'],
    queryFn: async () => {
      const res = await getBrowserApiClient().get('/api/v1/companies/me/progress');
      return res.data as PrepProgress;
    },
    staleTime: 60 * 1000,
  });
}

/**
 * Tick a subtopic on or off.
 *
 * Optimistic: a checkbox that waits for a round trip feels broken, and this is the
 * single most-tapped control on the page. The server returns the whole state, so
 * the optimistic value is replaced by truth on success and rolled back on failure
 * — the UI can never end up disagreeing with the database.
 */
export function useToggleProgress() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { subtopicId: string; completed: boolean; companySlug?: string }) => {
      const res = await getBrowserApiClient().post('/api/v1/companies/me/progress', {
        subtopic_id: input.subtopicId,
        completed: input.completed,
        company_slug: input.companySlug ?? null,
      });
      return res.data as PrepProgress;
    },
    onMutate: async (input) => {
      await queryClient.cancelQueries({ queryKey: ['prep-progress'] });
      const previous = queryClient.getQueryData<PrepProgress>(['prep-progress']);
      queryClient.setQueryData<PrepProgress>(['prep-progress'], (old) => {
        const set = new Set(old?.completed ?? []);
        if (input.completed) set.add(input.subtopicId);
        else set.delete(input.subtopicId);
        return { completed: [...set], minutes_done: old?.minutes_done ?? 0 };
      });
      return { previous };
    },
    onError: (_e, _v, ctx) => {
      // Put it back. Leaving an optimistic tick in place after a failed write is
      // how a candidate ends up believing they studied something they didn't.
      if (ctx?.previous) queryClient.setQueryData(['prep-progress'], ctx.previous);
    },
    onSuccess: (data) => queryClient.setQueryData(['prep-progress'], data),
  });
}

/* ─── Standing: the rating and cleared-round credential ────────────────────── */

export interface RankInfo {
  name: string;
  meaning: string;
  floor: number;
}

export interface TierProgress {
  tier: string;
  label: string;
  clear_bar: number;
  cleared: number;
  attempted: number;
}

export interface RoundSummary {
  kind: string;
  tier: string;
  score: number;
  cleared: boolean;
  delta: number;
  rating_after: number;
  at: string;
  /** Why the delta was what it was, in one line. */
  note: string;
}

export interface Progress {
  rating: number;
  peak_rating: number;
  rank: RankInfo;
  next_rank: RankInfo | null;
  points_to_next: number;
  percentile: number | null;
  rated_rounds: number;
  total_cleared: number;
  tiers: TierProgress[];
  recent: RoundSummary[];
  ladder: RankInfo[];
}

/**
 * The candidate's standing.
 *
 * Short staleTime rather than the usual long one: this is the number a candidate
 * comes back to check straight after a round, and showing them yesterday's rating
 * on the screen whose whole job is to show movement is the one cache miss that
 * actually matters.
 */
export function useProgress() {
  return useQuery({
    queryKey: ['progress'],
    queryFn: async () => {
      const res = await getBrowserApiClient().get('/api/v1/progress');
      return res.data as Progress;
    },
    staleTime: 30 * 1000,
  });
}
