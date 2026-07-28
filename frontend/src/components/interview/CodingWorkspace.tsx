'use client';

import { useMemo, useState } from 'react';
import CodeMirror from '@uiw/react-codemirror';
import { java } from '@codemirror/lang-java';
import { python } from '@codemirror/lang-python';
import { cpp } from '@codemirror/lang-cpp';
import { sql } from '@codemirror/lang-sql';
import { githubLight } from '@uiw/codemirror-theme-github';
import { AlertTriangle, Play, ScanSearch, Terminal } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  useAnalyseCode,
  useRunCode,
  type CodeLanguage,
  type CodingEvaluation,
} from '@/hooks/useCode';
import { cn } from '@/lib/utils';

const CORRECTNESS_META: Record<
  CodingEvaluation['correctness_level'],
  { label: string; tone: string }
> = {
  correct: { label: 'Correct', tone: 'bg-emerald-500/10 text-emerald-700 border-emerald-500/30' },
  nearly_correct: { label: 'Nearly correct', tone: 'bg-lime-500/10 text-lime-700 border-lime-500/30' },
  partially_correct: { label: 'Partially correct', tone: 'bg-amber-500/10 text-amber-700 border-amber-500/30' },
  incorrect: { label: 'Incorrect', tone: 'bg-red-500/10 text-red-700 border-red-500/30' },
};

const APPROACH_LABEL: Record<CodingEvaluation['approach'], string> = {
  brute_force: 'Brute force',
  optimised: 'Optimised',
  optimal: 'Optimal',
  wrong_approach: 'Wrong approach',
};

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
  /** The question being solved — gives the reviewer something to judge against. */
  problemTitle?: string;
  problemDescription?: string;
  difficulty?: string;
}

export function CodingWorkspace({
  onSubmit,
  submitting,
  disabled,
  problemTitle,
  problemDescription,
  difficulty,
}: CodingWorkspaceProps) {
  const [language, setLanguage] = useState<CodeLanguage>('java');
  const [code, setCode] = useState<string>(STARTERS.java);
  const [stdin, setStdin] = useState('');
  const runCode = useRunCode();
  const analyse = useAnalyseCode();

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
        <Button
          variant="secondary"
          onClick={() =>
            analyse.mutate({
              language,
              source: code,
              problem_title: problemTitle,
              problem_description: problemDescription,
              difficulty,
              // Give the reviewer the run output as evidence, when there is some.
              stdout: runCode.data?.stdout ?? '',
              stderr: runCode.data?.stderr ?? '',
            })
          }
          loading={analyse.isPending}
          disabled={disabled || !code.trim()}
        >
          <ScanSearch className="h-4 w-4" /> Review my code
        </Button>
        <Button onClick={() => onSubmit({ language, code })} loading={submitting} disabled={disabled}>
          Submit for Evaluation
        </Button>
      </div>

      {/* AI review */}
      {analyse.isPending && (
        <div className="rounded-2xl border border-border bg-surface p-4 text-sm text-muted-foreground">
          Reviewing your approach, complexity and edge cases…
        </div>
      )}
      {analyse.data && !analyse.data.available && (
        <div className="rounded-2xl border border-border bg-surface p-4 text-sm text-muted-foreground">
          Code review isn&apos;t available right now. Your code still runs and submits normally.
        </div>
      )}
      {analyse.data?.evaluation && <CodeReview evaluation={analyse.data.evaluation} />}

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

/** Renders the AI review: correctness, approach, complexity, bugs, AI flag. */
function CodeReview({ evaluation: e }: { evaluation: CodingEvaluation }) {
  const meta = CORRECTNESS_META[e.correctness_level];
  return (
    <div className="space-y-4 rounded-2xl border border-border bg-surface p-5">
      {/* Verdict */}
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn('rounded-full border px-3 py-1 text-xs font-bold', meta.tone)}>
          {meta.label}
        </span>
        <span className="rounded-full border border-border px-3 py-1 text-xs font-medium text-muted-foreground">
          {APPROACH_LABEL[e.approach]}
        </span>
        {/* A working brute force is a legitimate interview pass — say so. */}
        {e.approach === 'brute_force' && e.is_brute_force_sound && (
          <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1 text-xs font-medium text-emerald-700">
            Brute force is sound
          </span>
        )}
        <span className="ml-auto text-sm font-bold">
          {e.overall_score.toFixed(1)}
          <span className="text-xs font-normal text-muted-foreground">/10</span>
        </span>
      </div>

      <p className="text-sm leading-relaxed text-foreground/85">{e.summary}</p>

      {/* Possible AI authorship — a soft, fallible signal, not an accusation. */}
      {e.ai_authorship_suspected && (
        <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-4">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 shrink-0 text-amber-600" />
            <p className="text-xs font-bold uppercase tracking-wider text-amber-700">
              This may not be your own code ({e.ai_authorship_confidence} confidence)
            </p>
          </div>
          {e.ai_authorship_note && (
            <p className="mt-2 text-sm leading-relaxed text-foreground/85">{e.ai_authorship_note}</p>
          )}
          {e.ai_authorship_signals.length > 0 && (
            <ul className="mt-2 space-y-1">
              {e.ai_authorship_signals.map((s, i) => (
                <li key={i} className="flex gap-2 text-xs text-foreground/75">
                  <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-amber-500" />
                  {s}
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-[11px] italic text-amber-700/80">
            This is a heuristic and can be wrong — if the code is yours, ignore it.
          </p>
        </div>
      )}

      {/* Complexity */}
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="rounded-xl border border-border/60 p-3">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Time</p>
          <p className="mt-0.5 font-mono text-sm">{e.time_complexity || '—'}</p>
          {e.optimal_time_complexity && e.optimal_time_complexity !== e.time_complexity && (
            <p className="mt-0.5 text-[11px] text-muted-foreground">optimal: {e.optimal_time_complexity}</p>
          )}
        </div>
        <div className="rounded-xl border border-border/60 p-3">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Space</p>
          <p className="mt-0.5 font-mono text-sm">{e.space_complexity || '—'}</p>
          {e.optimal_space_complexity && e.optimal_space_complexity !== e.space_complexity && (
            <p className="mt-0.5 text-[11px] text-muted-foreground">optimal: {e.optimal_space_complexity}</p>
          )}
        </div>
      </div>

      {/* Bugs */}
      {e.bugs.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-red-600">Bugs found</p>
          <ul className="space-y-2">
            {e.bugs.map((b, i) => (
              <li key={i} className="rounded-lg border border-red-500/20 bg-red-500/5 p-3 text-sm">
                <div className="flex items-center gap-2">
                  <span className="text-[10px] font-bold uppercase text-red-700">{b.severity}</span>
                  {b.line != null && (
                    <span className="font-mono text-[11px] text-muted-foreground">line {b.line}</span>
                  )}
                </div>
                <p className="mt-1 text-foreground/85">{b.description}</p>
                {b.fix && <p className="mt-1 text-xs text-muted-foreground">Fix: {b.fix}</p>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {e.edge_cases_missed.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            Edge cases missed:
          </span>
          {e.edge_cases_missed.map((c) => (
            <span key={c} className="rounded-full border border-border px-2 py-0.5 text-[11px]">{c}</span>
          ))}
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        {e.strengths.length > 0 && (
          <div>
            <p className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-emerald-600">Strengths</p>
            <ul className="space-y-1 text-sm text-foreground/80">
              {e.strengths.map((s, i) => (
                <li key={i} className="flex gap-2">
                  <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-emerald-500" />{s}
                </li>
              ))}
            </ul>
          </div>
        )}
        {e.improvements.length > 0 && (
          <div>
            <p className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-amber-600">To improve</p>
            <ul className="space-y-1 text-sm text-foreground/80">
              {e.improvements.map((s, i) => (
                <li key={i} className="flex gap-2">
                  <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-amber-500" />{s}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {e.optimisation_hint && (
        <p className="rounded-xl border border-primary/20 bg-primary/5 p-3 text-sm leading-relaxed text-foreground/85">
          <span className="font-semibold">Next step: </span>{e.optimisation_hint}
        </p>
      )}

      {e.follow_up_questions.length > 0 && (
        <div>
          <p className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            An interviewer would ask
          </p>
          <ul className="space-y-1 text-sm text-foreground/80">
            {e.follow_up_questions.map((q, i) => (
              <li key={i} className="flex gap-2">
                <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-muted-foreground" />{q}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
