import { useMutation } from '@tanstack/react-query';
import { getBrowserApiClient } from '@/lib/api';

export type CodeLanguage = 'java' | 'python' | 'cpp' | 'sql';

export interface CodeExecuteResult {
  language: string;
  stdout: string;
  stderr: string;
  exit_code: number | null;
  timed_out: boolean;
  supported_languages: string[];
}

export function useRunCode() {
  return useMutation({
    mutationFn: async (input: { language: CodeLanguage; source: string; stdin?: string }) => {
      const res = await getBrowserApiClient().post('/api/v1/code/execute', {
        language: input.language,
        source: input.source,
        stdin: input.stdin ?? '',
      });
      return res.data as CodeExecuteResult;
    },
  });
}

export interface CodeBug {
  description: string;
  severity: 'critical' | 'major' | 'minor' | 'style';
  line: number | null;
  fix: string;
}

export interface CodingEvaluation {
  correctness_level: 'correct' | 'nearly_correct' | 'partially_correct' | 'incorrect';
  summary: string;
  approach: 'brute_force' | 'optimised' | 'optimal' | 'wrong_approach';
  is_brute_force_sound: boolean;
  time_complexity: string;
  optimal_time_complexity: string;
  space_complexity: string;
  optimal_space_complexity: string;
  correctness_score: number;
  efficiency_score: number;
  code_quality_score: number;
  overall_score: number;
  bugs: CodeBug[];
  edge_cases_missed: string[];
  strengths: string[];
  improvements: string[];
  optimisation_hint: string;
  follow_up_questions: string[];
  ai_authorship_suspected: boolean;
  ai_authorship_confidence: 'low' | 'medium' | 'high';
  ai_authorship_signals: string[];
  ai_authorship_note: string;
}

/**
 * AI code review: graded correctness, what approach was taken, and a soft flag
 * when the submission looks AI-authored. Long-running, so give it room — the
 * server caps itself at 45s and answers `available: false` rather than hanging.
 */
export function useAnalyseCode() {
  return useMutation({
    mutationFn: async (input: {
      language: CodeLanguage;
      source: string;
      problem_title?: string;
      problem_description?: string;
      difficulty?: string;
      stdout?: string;
      stderr?: string;
    }) => {
      const res = await getBrowserApiClient().post(
        '/api/v1/code/analyse',
        {
          language: input.language,
          source: input.source,
          problem_title: input.problem_title ?? 'Coding question',
          problem_description: input.problem_description ?? '',
          difficulty: input.difficulty ?? 'medium',
          stdout: input.stdout ?? '',
          stderr: input.stderr ?? '',
        },
        { timeout: 60_000 },
      );
      return res.data as { available: boolean; evaluation: CodingEvaluation | null };
    },
  });
}
