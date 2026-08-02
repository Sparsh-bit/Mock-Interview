'use client';

import { useInterview } from '@/hooks/useInterview';
import { useTracks, usePrimaryResume } from '@/hooks/useData';
import { Play, Code2, Loader2, CheckCircle2, Sparkles, ArrowRight, ListChecks, FileCheck2 } from 'lucide-react';
import { useState, useEffect, useMemo, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { toast } from 'sonner';

export const runtime = 'edge';
export default function InterviewSetupPage() {
  return (
    <Suspense fallback={<div className="mt-10 text-center text-sm text-muted-foreground">Loading…</div>}>
      <InterviewSetup />
    </Suspense>
  );
}

function InterviewSetup() {
  const { createPlan, approvePlan } = useInterview();
  const { data: tracks, isLoading: tracksLoading } = useTracks();
  const searchParams = useSearchParams();
  const requestedTrackId = searchParams.get('trackId');
  // Carried over from /prepare so picking a target company there lands here with
  // the field already filled — otherwise the candidate chooses twice.
  const requestedCompany = searchParams.get('company');

  const [selectedTrackId, setSelectedTrackId] = useState('');
  const [company, setCompany] = useState('');
  const [program, setProgram] = useState('');
  const [prompt, setPrompt] = useState('');
  const [resumeText, setResumeText] = useState('');
  // Shown so a blank box does not look like opting out of personalisation.
  const { data: storedResume } = usePrimaryResume();

  useEffect(() => {
    if (requestedCompany) setCompany((c) => c || requestedCompany);
  }, [requestedCompany]);

  useEffect(() => {
    if (!tracks || tracks.length === 0 || selectedTrackId) return;
    if (requestedTrackId && tracks.some((t) => t.id === requestedTrackId)) {
      setSelectedTrackId(requestedTrackId);
    } else {
      setSelectedTrackId(tracks[0].id);
    }
  }, [tracks, selectedTrackId, requestedTrackId]);

  // Tracks grouped by company: the picker is company-first, and the flat list is
  // 24 items long now that every catalogue company is interviewable.
  const companies = useMemo(() => {
    const map = new Map<string, { name: string; tracks: NonNullable<typeof tracks> }>();
    (tracks ?? []).forEach((t) => {
      const entry = map.get(t.company.name) ?? { name: t.company.name, tracks: [] };
      entry.tracks.push(t);
      map.set(t.company.name, entry);
    });
    return [...map.values()].sort((a, b) => a.name.localeCompare(b.name));
  }, [tracks]);

  const activeCompanyName = useMemo(
    () => (tracks ?? []).find((t) => t.id === selectedTrackId)?.company.name ?? '',
    [tracks, selectedTrackId],
  );
  const activeCompany = companies.find((c) => c.name === activeCompanyName);

  const plan = createPlan.data;

  const handleGenerate = () => {
    if (!selectedTrackId) return;
    createPlan.mutate(
      { trackId: selectedTrackId, company, program, prompt, resumeText },
      { onError: (err: Error) => toast.error(err.message || 'Could not build your interview plan.') }
    );
  };

  const handleStart = () => {
    if (!plan) return;
    approvePlan.mutate(plan.session_id, {
      onError: (err: Error) => toast.error(err.message || 'Could not start the interview.'),
    });
  };

  // ─── Step 2: Review & approve the generated plan ──────────────────────────
  if (plan) {
    return (
      <div className="mx-auto mt-10 max-w-3xl space-y-6">
        <div className="rounded-xl border border-border bg-surface-elevated p-6 shadow-elev-1">
          <div className="mb-6 flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-primary/10">
              <ListChecks className="h-5 w-5 text-primary" />
            </div>
            <div>
              <h1 className="text-[clamp(1.5rem,2.6vw,2rem)] font-medium leading-[1.12] tracking-[-0.03em]">Your interview plan is ready</h1>
              <p className="text-sm text-muted-foreground">
                {plan.question_count} questions{company ? ` · tailored for ${company}` : ''}
                {program ? ` · ${program}` : ''}. Review the topics, then begin.
              </p>
            </div>
          </div>

          <p className="mb-3 text-xs font-semibold uppercase tracking-widest text-muted-foreground">
            Topics we&apos;ll cover
          </p>
          <div className="mb-8 flex flex-wrap gap-2">
            {plan.topics.length > 0 ? (
              plan.topics.map((t) => (
                <span
                  key={t}
                  className="rounded-full border border-primary/20 bg-primary/5 px-3.5 py-1.5 text-sm font-medium text-foreground/90"
                >
                  {t}
                </span>
              ))
            ) : (
              <span className="text-sm text-muted-foreground">A balanced spread for this role.</span>
            )}
          </div>

          <div className="flex flex-col gap-3 sm:flex-row">
            <button
              onClick={handleStart}
              disabled={approvePlan.isPending}
              className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-primary px-6 py-4 text-sm font-bold text-primary-foreground shadow-glow transition-all hover:bg-primary/90 disabled:opacity-50"
            >
              {approvePlan.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" /> Starting…
                </>
              ) : (
                <>
                  <Play className="h-4 w-4" /> Start Interview
                </>
              )}
            </button>
            <button
              onClick={() => createPlan.reset()}
              disabled={approvePlan.isPending}
              className="rounded-xl border border-border px-6 py-4 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
            >
              Adjust setup
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ─── Step 1: Setup ────────────────────────────────────────────────────────
  return (
    <div className="mx-auto mt-10 max-w-3xl space-y-6">
      <div className="rounded-xl border border-border bg-surface-elevated p-6 shadow-elev-1">
        <div className="mb-8">
          <h1 className="text-[clamp(1.5rem,2.6vw,2rem)] font-medium leading-[1.12] tracking-[-0.03em]">Start a New Mock Interview</h1>
          <p className="mt-2 text-muted-foreground">
            Tell us who you&apos;re preparing for. The AI builds a realistic, ordered interview —
            warm-up first, then technical, then scenario and HR — and can pull from your resume.
          </p>
        </div>

        {/* ── Company, then program ────────────────────────────────────────
            Two compact levels instead of one grid of every track. With twelve
            companies the flat grid ran to 24 large cards, which pushed the
            customisation — the resume, the focus box, the whole reason this is
            not a generic interview — so far below the fold that nobody found it.
            Twelve chips and a row of programs fit on one screen. */}
        <p className="mb-3 text-xs font-semibold uppercase tracking-widest text-muted-foreground">
          Who are you interviewing with?
        </p>
        {tracksLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-primary" />
          </div>
        ) : (
          <>
            <div className="mb-4 flex flex-wrap gap-2">
              {companies.map((c) => {
                const active = c.name === activeCompanyName;
                return (
                  <button
                    type="button"
                    key={c.name}
                    onClick={() => {
                      // Selecting a company selects its first program, so the form
                      // is never in a half-chosen state with no track.
                      setSelectedTrackId(c.tracks[0].id);
                      setCompany(c.name);
                    }}
                    className={`rounded-xl border px-4 py-2.5 text-sm font-semibold transition-all ${
                      active
                        ? 'border-primary bg-primary/10 text-primary shadow-glow'
                        : 'border-border/60 bg-surface text-foreground/80 hover:border-primary/50'
                    }`}
                  >
                    {c.name}
                    <span className="ml-1.5 text-[11px] font-medium text-muted-foreground">
                      {c.tracks.length}
                    </span>
                  </button>
                );
              })}
            </div>

            {activeCompany && (
              <div className="mb-7">
                <p className="mb-2 text-xs font-semibold uppercase tracking-widest text-muted-foreground">
                  Program / track
                </p>
                <div className="flex flex-wrap gap-2">
                  {activeCompany.tracks.map((track) => {
                    const isSelected = selectedTrackId === track.id;
                    return (
                      <button
                        type="button"
                        key={track.id}
                        onClick={() => setSelectedTrackId(track.id)}
                        className={`inline-flex items-center gap-2 rounded-lg border px-3.5 py-2 text-sm transition-all ${
                          isSelected
                            ? 'border-primary bg-primary/10 font-semibold text-primary'
                            : 'border-border/60 bg-surface text-muted-foreground hover:border-primary/50 hover:text-foreground'
                        }`}
                      >
                        {isSelected ? (
                          <CheckCircle2 className="h-4 w-4" />
                        ) : (
                          <Code2 className="h-4 w-4 opacity-50" />
                        )}
                        {track.name}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </>
        )}

        {/* Company + program */}
        <div className="mb-5 grid gap-4 sm:grid-cols-2">
          <div>
            <label className="mb-1.5 block text-sm font-medium">Company you&apos;re preparing for</label>
            <input
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              placeholder="e.g. Cognizant, Infosys, TCS…"
              className="w-full rounded-xl border border-border/50 bg-surface-elevated px-4 py-3 text-sm focus:border-primary/40 focus:outline-none focus:ring-2 focus:ring-primary/20"
            />
          </div>
          <div>
            <label className="mb-1.5 block text-sm font-medium">Program / role</label>
            <input
              value={program}
              onChange={(e) => setProgram(e.target.value)}
              placeholder="e.g. GenC, GenC Next, Java FSE…"
              className="w-full rounded-xl border border-border/50 bg-surface-elevated px-4 py-3 text-sm focus:border-primary/40 focus:outline-none focus:ring-2 focus:ring-primary/20"
            />
          </div>
        </div>

        {/* Free prompt */}
        <div className="mb-5">
          <label className="mb-1.5 block text-sm font-medium">
            Anything specific? <span className="text-muted-foreground">(optional)</span>
          </label>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={2}
            placeholder="e.g. Focus on Spring Boot and SQL; I struggle with multithreading."
            className="w-full resize-none rounded-xl border border-border/50 bg-surface-elevated px-4 py-3 text-sm focus:border-primary/40 focus:outline-none focus:ring-2 focus:ring-primary/20"
          />
        </div>

        {/* Resume.

            When an uploaded resume exists the server uses it automatically, so
            this box has to say so — otherwise leaving it blank looks like opting
            out of personalisation when it is in fact the normal path. Pasted text
            still takes precedence, which is why it remains editable rather than
            being hidden once a file is on record. */}
        <div className="mb-8">
          <label className="mb-1.5 block text-sm font-medium">
            Your resume{' '}
            <span className="text-muted-foreground">
              {storedResume?.has_text ? '(optional — overrides your uploaded resume)' : '(optional — paste skills & projects)'}
            </span>
          </label>

          {storedResume?.has_text && (
            <div className="mb-2 flex flex-wrap items-center gap-2 rounded-lg border border-accent-emerald/20 bg-accent-emerald/5 px-3 py-2 text-xs">
              <FileCheck2 className="h-3.5 w-3.5 shrink-0 text-accent-emerald-ink" />
              <span className="text-muted-foreground">
                Using <span className="font-semibold text-foreground">{storedResume.filename}</span> — leave this
                blank to keep using it.
              </span>
              <Link href="/profile" className="font-semibold text-primary hover:underline">
                Change
              </Link>
            </div>
          )}

          <textarea
            value={resumeText}
            onChange={(e) => setResumeText(e.target.value)}
            rows={4}
            placeholder={
              storedResume?.has_text
                ? 'Leave blank to use your uploaded resume, or paste different details to use just for this interview.'
                : 'Paste your resume or key points here. The interviewer will ask about your actual projects, skills and experience.'
            }
            className="w-full resize-none rounded-xl border border-border/50 bg-surface-elevated px-4 py-3 text-sm focus:border-primary/40 focus:outline-none focus:ring-2 focus:ring-primary/20"
          />

          {!storedResume?.has_text && (
            <p className="mt-2 text-[11px] text-muted-foreground">
              Tip:{' '}
              <Link href="/profile" className="font-semibold text-primary hover:underline">
                upload your resume once
              </Link>{' '}
              and every interview will use it automatically.
            </p>
          )}
        </div>

        <button
          onClick={handleGenerate}
          disabled={createPlan.isPending || !selectedTrackId}
          className="flex w-full items-center justify-center gap-2 rounded-xl bg-primary px-6 py-4 text-sm font-bold text-primary-foreground shadow-glow transition-all hover:bg-primary/90 disabled:opacity-50"
        >
          {createPlan.isPending ? (
            <>
              <Sparkles className="h-4 w-4 animate-pulse" /> Building your tailored interview…
            </>
          ) : (
            <>
              Build my interview plan <ArrowRight className="h-4 w-4" />
            </>
          )}
        </button>
        {createPlan.isPending && (
          <p className="mt-3 text-center text-xs text-muted-foreground">
            Crafting questions for your company, program and resume — this usually takes a few
            seconds. Hang tight.
          </p>
        )}
      </div>
    </div>
  );
}
