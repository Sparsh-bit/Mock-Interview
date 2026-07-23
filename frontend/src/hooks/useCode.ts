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
