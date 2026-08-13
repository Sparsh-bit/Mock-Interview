'use client';

import { useInterview } from '@/hooks/useInterview';
import { useTracks, usePrimaryResume } from '@/hooks/useData';
import { Play, Code2, Loader2, CheckCircle2, Sparkles, ArrowRight, ListChecks, FileCheck2 } from 'lucide-react';
import { useState, useEffect, useMemo, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { toast } from 'sonner';
import { Paywall, paywallFromError, type PaywallInfo } from '@/components/billing/Paywall';
import { CreditMeter } from '@/components/billing/CreditMeter';

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
  //: Either source counts. Trimmed, so whitespace is not an answer.
  const hasResume = !!storedResume?.has_text || resumeText.trim().length >= 20;

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

  /*
   * THE PAYWALL IS DRIVEN BY THE SERVER'S 402, NOT BY THE CACHED BALANCE.
   *
   * The credit meter is right there on this page and it would be easy to check it before
   * enabling the button. That would be wrong in both directions: a stale cache blocks a user
   * the server would have allowed, and — the one that actually costs money — it fails to
   * block one the server refused, so they watch a spinner and get a toast instead of an
   * offer.
   *
   * So the request is always attempted, and this holds whatever the server said about why it
   * refused. `paywallFromError` returns null for every other kind of failure, which keeps a
   * network blip on the toast path where it belongs.
   */
  const [paywall, setPaywall] = useState<PaywallInfo | null>(null);

  const handleGenerate = () => {
    if (!selectedTrackId) return;
    setPaywall(null);
    createPlan.mutate(
      { trackId: selectedTrackId, company, program, prompt, resumeText },
      {
        onError: (err: Error) => {
          const blocked = paywallFromError(err);
          if (blocked) {
            // Not a toast. Running out of interviews is not a transient error to be
            // dismissed — it needs an explanation and a next step that stay on screen.
            setPaywall(blocked);
            return;
          }
          toast.error(err.message || 'Could not build your interview plan.');
        },
      }
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
              className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-primary px-6 py-4 text-sm font-bold text-primary-foreground shadow-glow transition-[color,background-color,border-color,box-shadow,transform,opacity] hover:bg-primary/90 disabled:opacity-50"
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

  // ─── Blocked: the allowance for interviews is spent ───────────────────────
  //
  // Rendered INSTEAD of the setup form, not above it. Leaving a form on screen that cannot
  // succeed invites somebody to fill it in again and press the button a second time.
  if (paywall) {
    return (
      <div className="mx-auto mt-10 max-w-2xl space-y-6">
        <Paywall info={paywall} />
        <div className="text-center">
          <button
            type="button"
            onClick={() => setPaywall(null)}
            className="text-sm text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
          >
            Back to setup
          </button>
        </div>
      </div>
    );
  }

  // ─── Step 1: Setup ────────────────────────────────────────────────────────
  return (
    <div className="mx-auto mt-10 max-w-3xl space-y-6">
      {/* The count, before anything is filled in. A candidate who spends five minutes on the
          setup form and only then learns they have no interviews left has lost the one thing
          they came with. */}
      <CreditMeter />
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
                    className={`rounded-xl border px-4 py-2.5 text-sm font-semibold transition-[color,background-color,border-color,box-shadow,transform,opacity] ${
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
                        className={`inline-flex items-center gap-2 rounded-lg border px-3.5 py-2 text-sm transition-[color,background-color,border-color,box-shadow,transform,opacity] ${
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
          {/* REQUIRED, not optional — and the requirement is satisfied by EITHER a stored
              resume or pasted text, which is why the label changes rather than always
              demanding a paste.

              It was optional and that quietly produced the worst interviews the product
              gives. The planner's whole advantage is asking "you listed <project> — how did
              you handle X there?" instead of a generic question set; with nothing to read it
              falls back to the generic set, and a candidate whose first interview was the
              generic one has seen a worse product than the one that exists. Making it
              compulsory costs thirty seconds once (the upload is remembered) and changes
              every interview after it. */}
          <label className="mb-1.5 block text-sm font-medium">
            Your resume{' '}
            <span className={storedResume?.has_text ? 'text-muted-foreground' : 'text-destructive'}>
              {storedResume?.has_text
                ? '(on file — paste here only to override it for this interview)'
                : '(required — paste your skills & projects, or upload once in your profile)'}
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

        {/* A disabled button with no reason beside it is a dead end — the candidate cannot
            tell whether they missed a field or the app is broken. Named specifically rather
            than "complete the form", because the two possible causes have different fixes. */}
        {!hasResume && (
          <p className="mb-3 text-center text-xs text-muted-foreground">
            Add your resume above (or{' '}
            <Link href="/profile" className="font-semibold text-primary hover:underline">
              upload it once
            </Link>
            ) — the interview is built around your own projects.
          </p>
        )}

        <button
          onClick={handleGenerate}
          // The resume gate. Satisfied by a stored file OR pasted text — somebody who
          // uploaded once should never be asked again, which is what the tip below promises.
          // The server independently falls back to the stored resume, so this is the
          // courtesy half; it stops somebody submitting a form that would produce the
          // generic interview rather than the personalised one they came for.
          disabled={createPlan.isPending || !selectedTrackId || !hasResume}
          className="flex w-full items-center justify-center gap-2 rounded-xl bg-primary px-6 py-4 text-sm font-bold text-primary-foreground shadow-glow transition-[color,background-color,border-color,box-shadow,transform,opacity] hover:bg-primary/90 disabled:opacity-50"
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
