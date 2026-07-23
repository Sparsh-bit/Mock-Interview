'use client';

import { useMemo, useState } from 'react';
import CodeMirror from '@uiw/react-codemirror';
import { java } from '@codemirror/lang-java';
import { python } from '@codemirror/lang-python';
import { cpp } from '@codemirror/lang-cpp';
import { sql } from '@codemirror/lang-sql';
import { githubLight } from '@uiw/codemirror-theme-github';
import { Play, Terminal } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useRunCode, type CodeLanguage } from '@/hooks/useCode';
import { cn } from '@/lib/utils';

const LANGUAGES: { id: CodeLanguage; label: string }[] = [
  { id: 'java', label: 'Java' },
  { id: 'python', label: 'Python' },
  { id: 'cpp', label: 'C++' },
  { id: 'sql', label: 'SQL' },
];

const STARTERS: Record<CodeLanguage, string> = {
  java: 'public class Main {\n    public static void main(String[] args) {\n        // your solution here\n    }\n}\n',
  python: '# your solution here\n',
  cpp: '#include <iostream>\nusing namespace std;\n\nint main() {\n    // your solution here\n    return 0;\n}\n',
  sql: '-- your query here\n',
};

interface CodingWorkspaceProps {
  /** Called with the final code when the candidate submits for evaluation. */
  onSubmit: (payload: { language: CodeLanguage; code: string }) => void;
  submitting?: boolean;
  disabled?: boolean;
}

export function CodingWorkspace({ onSubmit, submitting, disabled }: CodingWorkspaceProps) {
  const [language, setLanguage] = useState<CodeLanguage>('java');
  const [code, setCode] = useState<string>(STARTERS.java);
  const [stdin, setStdin] = useState('');
  const runCode = useRunCode();

  const extensions = useMemo(() => {
    switch (language) {
      case 'python': return [python()];
      case 'cpp': return [cpp()];
      case 'sql': return [sql()];
      default: return [java()];
    }
  }, [language]);

  const switchLanguage = (lang: CodeLanguage) => {
    // Only replace the buffer if the user hasn't diverged from the starter.
    setCode((current) =>
      Object.values(STARTERS).includes(current) ? STARTERS[lang] : current
    );
    setLanguage(lang);
  };

  const result = runCode.data;

  return (
    <div className="flex flex-col gap-4">
      {/* Language tabs */}
      <div className="flex items-center gap-1 rounded-full bg-secondary p-1 w-fit">
        {LANGUAGES.map((l) => (
          <button
            key={l.id}
            onClick={() => switchLanguage(l.id)}
            disabled={disabled}
            className={cn(
              'rounded-full px-4 py-1.5 text-[13px] font-medium transition-colors',
              language === l.id ? 'bg-surface-elevated text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'
            )}
          >
            {l.label}
          </button>
        ))}
      </div>

      {/* Editor */}
      <div className="overflow-hidden rounded-2xl border border-border">
        <CodeMirror
          value={code}
          height="320px"
          theme={githubLight}
          extensions={extensions}
          editable={!disabled}
          onChange={setCode}
          basicSetup={{ lineNumbers: true, foldGutter: true, highlightActiveLine: true }}
        />
      </div>

      {/* stdin */}
      <div>
        <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
          Standard input (optional)
        </label>
        <textarea
          value={stdin}
          onChange={(e) => setStdin(e.target.value)}
          disabled={disabled}
          rows={2}
          placeholder="Input passed to your program's stdin…"
          className="w-full resize-none rounded-xl border border-border bg-surface-elevated p-3 font-mono text-xs focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30"
        />
      </div>

      {/* Actions */}
      <div className="flex items-center gap-3">
        <Button
          variant="secondary"
          onClick={() => runCode.mutate({ language, source: code, stdin })}
          loading={runCode.isPending}
          disabled={disabled}
        >
          <Play className="h-4 w-4" /> Run Code
        </Button>
        <Button onClick={() => onSubmit({ language, code })} loading={submitting} disabled={disabled}>
          Submit for Evaluation
        </Button>
      </div>

      {/* Output */}
      {(runCode.isPending || result || runCode.isError) && (
        <div className="rounded-2xl border border-border bg-surface p-4">
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            <Terminal className="h-3.5 w-3.5" /> Output
          </div>
          {runCode.isPending && <p className="text-sm text-muted-foreground">Running…</p>}
          {runCode.isError && (
            <p className="text-sm text-red-600">Could not run code. Please try again.</p>
          )}
          {result && (
            <div className="space-y-2">
              {result.stdout && (
                <pre className="overflow-x-auto rounded-lg bg-surface-elevated p-3 font-mono text-xs text-foreground">{result.stdout}</pre>
              )}
              {result.stderr && (
                <pre className="overflow-x-auto rounded-lg bg-red-50 p-3 font-mono text-xs text-red-700">{result.stderr}</pre>
              )}
              {!result.stdout && !result.stderr && (
                <p className="text-sm text-muted-foreground">Program produced no output.</p>
              )}
              <p className="text-[11px] text-muted-foreground">
                Exit code: {result.exit_code ?? 'n/a'}{result.timed_out ? ' · timed out' : ''}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
