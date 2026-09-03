'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import {
  ArrowLeft,
  ArrowRight,
  FileCheck2,
  Loader2,
  MessageSquare,
  Mic,
  Upload,
} from 'lucide-react';

import { Brandmark } from '@/components/brand/Brandmark';
import { ResumeConsentGate } from '@/components/legal/ResumeConsentGate';
import { Choice, STEP_TITLE_ID, StepHead, StepRail } from '@/components/onboarding/shared';
import { usePrimaryResume, useRecruiters, useUpdateProfile, useUserProfile } from '@/hooks/useData';
import { useResumeUploadFlow, RESUME_MAX_MB } from '@/hooks/useResumeUploadFlow';
import { cn } from '@/lib/utils';

export const runtime = 'edge';

/**
 * THE FIRST FIVE MINUTES — app/welcome/page.tsx
 *
 * ── THE PROBLEM THIS EXISTS TO FIX ───────────────────────────────────────────────────────
 * Until now the flow after signing up was: confirm your email, log in, and land on a
 * dashboard of zeros. Nothing on that dashboard could be used. Its primary action, "Start
 * interview", led to a form whose submit button is disabled until a resume exists; the study
 * plan was unpersonalised because no target company had been chosen; and a new account holds
 * zero interview credits, so even a candidate who found the resume upload hit a 402 at the
 * end of it. Three dead ends, none of them signposted, on the first screen anybody sees.
 *
 * `plans.py` names the last one plainly — "the front door is now a paywall rather than a
 * trial". That is a pricing decision and this does not argue with it. What it does is stop the
 * paywall being the FIRST thing a new account meets, by walking through the two pieces of
 * setup the product actually needs and then handing over to the two things that are free.
 *
 * ── FOUR STEPS, AND WHY EACH ONE EARNS ITS SCREEN ────────────────────────────────────────
 *   1 TARGET     Company and programme. Without it `/prepare` has no plan to build and the
 *                interviewer has no paper to weight its questions against.
 *   2 RESUME     Hard-gated: the interview form's submit is disabled without one. Skippable
 *                here, because forcing an upload before somebody has seen anything work is
 *                how you lose the ones who do not have a PDF to hand on a phone.
 *   3 BACKGROUND Years, and one line about themselves. Optional, and the only step that is
 *                purely about answer quality rather than about unblocking a feature.
 *   4 READY      Three routes out, and the two free ones come first.
 *
 * ── HOW "ALREADY DONE" IS DECIDED ────────────────────────────────────────────────────────
 * There is no `onboarding_completed` column and this deliberately does not add one. A flag
 * like that is a second source of truth that drifts from the first: delete your resume and
 * the flag still says you are set up. Instead the wizard asks the data — a profile with a
 * target company and an uploaded resume IS a completed setup — and redirects to the dashboard
 * when both are true. The only thing kept locally is that somebody chose to skip, which is a
 * fact about a person's intent rather than about their account, and is exactly what local
 * storage is for.
 *
 * The key is `interviewos:` prefixed. That prefix is deliberate and documented in CLAUDE.md:
 * the brand has been renamed twice and the keys were left alone both times, because renaming
 * a key that is already written in somebody's browser silently resets them.
 */

const SKIP_KEY = 'interviewos:onboarding.skipped';
/** Prefills the interview form from the target chosen here, so nobody picks a company twice. */
const TARGET_KEY = 'interviewos:onboarding.target';

/**
 * READING AND WRITING THE ONE THING THIS FLOW KEEPS LOCALLY.
 *
 * `localStorage` is not a property bag, it is an API that THROWS — in a browser set to block
 * site data, in Safari's private mode when the quota is exhausted, and inside some embedded
 * webviews. An unguarded `getItem` in the redirect effect below would therefore take the whole
 * onboarding screen down for a brand-new account, for the sake of remembering whether somebody
 * pressed "skip". That is the trade this wrapper refuses to make.
 *
 * Both failures are silent and both degrade correctly: a failed read is "not skipped", so the
 * wizard shows once more than it needed to; a failed write is "we could not remember", with the
 * same consequence. Neither is worth a message, and `browser-storage.test.ts` enforces the
 * guard across the codebase because the last time this rule was broken it was in
 * settings/page.tsx and nobody noticed until a user could not open the page at all.
 */
function readLocal(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeLocal(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* See above: forgetting is the correct failure mode here. */
  }
}

const STEPS = [
  { id: 'target', label: 'Your target', hint: 'Who you are sitting for' },
  { id: 'resume', label: 'Your resume', hint: 'What the panel reads' },
  { id: 'background', label: 'Your background', hint: 'How it tailors questions' },
  { id: 'ready', label: 'Ready', hint: 'Where to start' },
] as const;

export default function WelcomePage() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  /*
   * WHICH WAY THE STEP IS MOVING, so the transition can carry the direction. Forward slides in
   * from the right and out to the left; Back does the reverse. A wizard whose steps always
   * enter from the same side reads as four unrelated screens rather than as one flow, and it
   * gives a visitor no spatial sense of having gone backwards when they press Back.
   */
  const [dir, setDir] = useState<1 | -1>(1);
  const reduced = useReducedMotion();

  /* Every step change goes through here. Two things have to happen on each one and both were
     missing: the direction has to be recorded, and focus has to move. */
  const go = useCallback(
    (next: number) => {
      setDir((prev) => (next === step ? prev : next > step ? 1 : -1));
      setStep(next);
    },
    [step],
  );

  /*
   * FOCUS FOLLOWS THE STEP — AND IT HAS TO WAIT FOR THE TRANSITION.
   *
   * Pressing Continue unmounts the button that had focus, so focus fell back to <body>: a
   * keyboard user was returned to the top of the document and had to tab past the brandmark,
   * the whole step rail and the Skip link to reach the next step's first field, and a screen
   * reader announced nothing at all.
   *
   * The obvious fix — a `useEffect` on `step` calling `getElementById(...).focus()` — DOES NOT
   * WORK HERE, and silently: with `AnimatePresence mode="wait"` the outgoing step is still
   * mounted when `step` changes, so the effect finds the OLD heading, focuses it, and then
   * that element unmounts a quarter-second later and focus falls back to <body> exactly as
   * before. Tested: it reported `BODY`.
   *
   * So the move is tied to the entering step finishing its animation instead. `initial={false}`
   * on the AnimatePresence means the first step never animates in, so this never fires on page
   * load — stealing focus on arrival would be its own bug.
   */
  const focusStepTitle = useCallback((definition: unknown) => {
    if (definition !== 'center') return;
    document.getElementById(STEP_TITLE_ID)?.focus();
  }, []);

  const { data: profile, isLoading: profileLoading } = useUserProfile();
  const { data: resume, isLoading: resumeLoading } = usePrimaryResume();
  const { data: recruiters, isLoading: recruitersLoading } = useRecruiters();
  const updateProfile = useUpdateProfile();

  const [company, setCompany] = useState<string | null>(null);
  const [program, setProgram] = useState<string | null>(null);
  const [years, setYears] = useState<number | null>(null);
  const [bio, setBio] = useState('');
  const [saving, setSaving] = useState(false);

  /*
   * ALREADY SET UP → STRAIGHT THROUGH. Somebody who signs in on a second device should not be
   * re-onboarded, and somebody who followed a link here by hand should not be trapped.
   *
   * ── THE DECISION IS TAKEN ONCE, AND THAT IS THE WHOLE POINT ─────────────────────────────
   * This used to depend on `complete`, recomputed from live React Query data on every render.
   * Which meant the wizard redirected out of ITSELF: step 1 PATCHes the profile so
   * `target_company` becomes set, step 2's upload invalidates `['resume']` so `resume` becomes
   * non-null — and at that moment `complete` flipped true, the effect fired, and the candidate
   * was thrown to the dashboard having never seen step 3 or step 4. Worse for anyone who
   * already had a resume: pressing Continue on step 1 ended the flow.
   *
   * Steps 3 and 4 are the reason this route exists — step 4 is what puts the two FREE rounds
   * in front of a new account instead of a 402 — so losing them silently is the most expensive
   * failure this file could have.
   *
   * `decided` latches on the first render where both reads have landed. After that the wizard
   * owns the page and no amount of data changing underneath it can navigate away.
   */
  const settled = !profileLoading && !resumeLoading;
  const decided = useRef(false);
  const [leaving, setLeaving] = useState(false);
  useEffect(() => {
    if (!settled || decided.current) return;
    decided.current = true;
    const setUp = Boolean(profile?.target_company) && Boolean(resume);
    const skipped = typeof window !== 'undefined' && readLocal(SKIP_KEY) === '1';
    if (setUp || skipped) {
      setLeaving(true);
      router.replace('/dashboard');
    }
  }, [settled, profile, resume, router]);

  /* Seed from whatever the account already has, so a half-finished setup resumes rather than
     restarts. `target_company` is stored as "Company — Programme"; splitting on the em dash is
     safe because neither half ever contains one. */
  const seeded = useRef(false);
  useEffect(() => {
    if (seeded.current || !profile) return;
    seeded.current = true;
    if (profile.target_company) {
      const [c, p] = profile.target_company.split(' — ');
      setCompany(c ?? null);
      setProgram(p ?? null);
    }
    if (typeof profile.experience_years === 'number') setYears(profile.experience_years);
    if (profile.bio) setBio(profile.bio);
  }, [profile]);

  const selected = useMemo(
    () => recruiters?.find((r) => r.name === company) ?? null,
    [recruiters, company],
  );

  const skip = () => {
    writeLocal(SKIP_KEY, '1');
    router.replace('/dashboard');
  };

  const saveTarget = async () => {
    if (!company) return;
    setSaving(true);
    try {
      await updateProfile.mutateAsync({
        target_company: program ? `${company} — ${program}` : company,
      });
      /* Prefill only — the target itself is saved server-side on the line above, so losing
         this costs a pre-selected chip on the interview form and nothing else. */
      writeLocal(TARGET_KEY, JSON.stringify({ company, program }));
      go(1);
    } catch {
      toast.error('Could not save your target. Try again.');
    } finally {
      setSaving(false);
    }
  };

  const saveBackground = async () => {
    setSaving(true);
    try {
      await updateProfile.mutateAsync({
        ...(years !== null ? { experience_years: years } : {}),
        ...(bio.trim() ? { bio: bio.trim() } : {}),
      });
      go(3);
    } catch {
      /* NOT A BLOCKER. This step is optional by design, and refusing to advance because an
         optional save failed would strand somebody on the least important screen in the flow. */
      toast.error('Could not save that — you can add it later in your profile.');
      go(3);
    } finally {
      setSaving(false);
    }
  };

  if (!settled || leaving) {
    return (
      <div className="mk grid min-h-screen place-items-center">
        <Loader2 className="h-5 w-5 animate-spin text-[var(--mk-muted)]" />
      </div>
    );
  }

  return (
    <div className="mk mk-grain relative min-h-screen">
      <div className="mx-auto grid max-w-[1060px] gap-10 px-[var(--mk-gutter)] py-10 lg:grid-cols-[248px_1fr] lg:gap-16 lg:py-16">
        <aside className="lg:sticky lg:top-16 lg:self-start">
          <span className="flex items-center gap-2.5">
            <Brandmark className="h-7 w-7" />
            <span className="whitespace-nowrap font-[family-name:var(--mk-font-display)] text-[1.0625rem] font-medium text-[var(--mk-ink)]">
              Interview<span className="text-[var(--mk-gold)]"> OS</span>
            </span>
          </span>

          <p className="mt-6 text-[var(--mk-micro)] leading-[1.6] text-[var(--mk-muted)]">
            Two minutes. Then the panel knows who it is interviewing.
          </p>

          <div className="mt-6 hidden lg:block">
            <StepRail steps={STEPS} current={step} onJump={go} />
          </div>

          {/* THE EXIT IS ALWAYS VISIBLE. A setup flow with no way out is a wall, and the one
              thing worse than an unconfigured account is somebody who never gets past the
              configuration. */}
          <button
            type="button"
            onClick={skip}
            className="mt-8 text-[var(--mk-micro)] text-[var(--mk-muted)] underline decoration-[var(--mk-border)] underline-offset-4 transition-colors hover:text-[var(--mk-ink)]"
          >
            Skip — take me to the dashboard
          </button>
        </aside>

        {/* Mobile progress. The rail is too tall for a phone, so the same information becomes
            one line and one bar. */}
        <div className="lg:hidden">
          <p className="mk-num text-[var(--mk-micro)] text-[var(--mk-muted)]">
            Step {step + 1} of {STEPS.length} — {STEPS[step].label}
          </p>
          <div className="mt-2 h-[3px] w-full overflow-hidden rounded-full bg-[rgb(59_43_28/0.1)]">
            <span
              className="block h-full rounded-full bg-[var(--mk-gold)] transition-[width] duration-500 [transition-timing-function:var(--mk-ease)]"
              style={{ width: `${((step + 1) / STEPS.length) * 100}%` }}
            />
          </div>
        </div>

        <main className="min-w-0">
          {/*
            * THE STEP TRANSITION.
            *
            * `mode="wait"` — the outgoing step finishes leaving before the incoming one
            * starts. The alternative, crossfading them in place, means two steps are in the
            * DOM together and the taller one dictates the height, so the panel jumps by
            * whatever the difference is; and with focus moving to the new heading on the same
            * tick, a screen reader would be landed on a heading inside an element that is
            * still animating out.
            *
            * 0.26s, out-expo, and a 20px slide rather than the usual 24 — this is a form, and
            * a form that slides far enough to notice reads as slow the third time you see it.
            * The distance carries the DIRECTION and nothing else.
            *
            * Under `prefers-reduced-motion` there is no transition at all: `AnimatePresence`
            * still keys the steps so focus and mounting behave identically, but the variants
            * collapse to a plain opacity swap over 0.01s. A wizard is exactly the case that
            * setting exists for — motion the user did not ask for, on every click, on a
            * screen they are trying to fill in.
            */}
          <AnimatePresence mode="wait" initial={false} custom={dir}>
            <motion.div
              key={step}
              custom={dir}
              variants={{
                enter: (d: number) => ({ opacity: 0, x: reduced ? 0 : d * 20 }),
                center: { opacity: 1, x: 0 },
                exit: (d: number) => ({ opacity: 0, x: reduced ? 0 : d * -20 }),
              }}
              initial="enter"
              animate="center"
              exit="exit"
              transition={{ duration: reduced ? 0.01 : 0.26, ease: [0.22, 1, 0.36, 1] }}
              onAnimationComplete={focusStepTitle}
            >
          {step === 0 && (
            <TargetStep
              loading={recruitersLoading}
              recruiters={recruiters ?? []}
              company={company}
              program={program}
              onCompany={(name) => {
                setCompany(name);
                setProgram(null);
              }}
              onProgram={setProgram}
              selected={selected}
              saving={saving}
              onNext={saveTarget}
            />
          )}

          {step === 1 && (
            <ResumeStep resume={resume} onBack={() => go(0)} onNext={() => go(2)} />
          )}

          {step === 2 && (
            <BackgroundStep
              years={years}
              bio={bio}
              onYears={setYears}
              onBio={setBio}
              saving={saving}
              onBack={() => go(1)}
              onNext={saveBackground}
            />
          )}

          {step === 3 && (
            <ReadyStep company={company} program={program} hasResume={Boolean(resume)} />
          )}
            </motion.div>
          </AnimatePresence>

          {/*
            * WHAT A SCREEN READER HEARS WHEN THE STEP CHANGES.
            *
            * Focus moving to the heading announces the new step's title; this announces the
            * POSITION, which the heading does not carry. Visually hidden rather than absent,
            * because the same fact is already on screen for sighted users in the mobile
            * progress line and the desktop rail — this is the third rendering of one fact, for
            * the one audience the other two do not reach.
            */}
          <p aria-live="polite" className="sr-only">
            Step {step + 1} of {STEPS.length}: {STEPS[step].label}
          </p>
        </main>
      </div>
    </div>
  );
}

/* ── 1 · TARGET ───────────────────────────────────────────────────────────
   Company first, then that company's programmes. Two dependent lists rather
   than one flat list of 24, because "Cognizant GenC Next" means nothing to
   somebody who has not sat a Cognizant drive, and "Cognizant" followed by its
   four programmes reads as a question they can answer. */
function TargetStep({
  loading,
  recruiters,
  company,
  program,
  onCompany,
  onProgram,
  selected,
  saving,
  onNext,
}: {
  loading: boolean;
  recruiters: { slug: string; name: string; short: string; programs: { name: string; detail: string }[] }[];
  company: string | null;
  program: string | null;
  onCompany: (name: string) => void;
  onProgram: (name: string) => void;
  selected: { programs: { name: string; detail: string }[] } | null;
  saving: boolean;
  onNext: () => void;
}) {
  return (
    <>
      <StepHead eyebrow="Step one" title="Who are you" turn="sitting for?">
        Every recruiter weights its paper differently — Amazon gives algorithms 45% of it, TCS
        gives aptitude 25%. Pick your target and the questions, the plan and the report are all
        weighted to it.
      </StepHead>

      {loading ? (
        <Skeleton rows={6} />
      ) : (
        <div className="grid gap-2 sm:grid-cols-2">
          {recruiters.map((r) => (
            <Choice
              key={r.slug}
              selected={company === r.name}
              onSelect={() => onCompany(r.name)}
              title={r.name}
              detail={r.short}
              meta={`${r.programs.length} ${r.programs.length === 1 ? 'track' : 'tracks'}`}
            />
          ))}
        </div>
      )}

      {selected && (
        <div className="mt-9">
          <p className="mk-eyebrow">Which programme</p>
          <div className="mt-4 grid gap-2 sm:grid-cols-2">
            {selected.programs.map((p) => (
              <Choice
                key={p.name}
                selected={program === p.name}
                onSelect={() => onProgram(p.name)}
                title={p.name}
                detail={p.detail}
              />
            ))}
          </div>
        </div>
      )}

      <Actions>
        <button
          type="button"
          onClick={onNext}
          disabled={!company || saving}
          className="mk-btn mk-btn-primary disabled:cursor-not-allowed disabled:opacity-45"
        >
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          Continue
          <ArrowRight className="mk-arrow h-4 w-4" strokeWidth={2.2} />
        </button>
      </Actions>
    </>
  );
}

/* ── 2 · RESUME ───────────────────────────────────────────────────────────
   The one hard gate in the product, and the one step here that can be skipped.
   Those are not in conflict: the gate is on starting an interview, not on
   having an account, and somebody on a phone with no PDF to hand should still
   reach the free rounds. */
function ResumeStep({
  resume,
  onBack,
  onNext,
}: {
  resume: { filename: string; parsed_skills: string[] | null } | null | undefined;
  onBack: () => void;
  onNext: () => void;
}) {
  const { submit, isUploading, awaitingConsent, consentGranted, cancelConsent } =
    useResumeUploadFlow();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [dragging, setDragging] = useState(false);

  return (
    <>
      <StepHead eyebrow="Step two" title="Give the panel something" turn="to ask you about.">
        The interviewer reads your resume and asks about what is actually on it — your
        projects, your stack, the gap between two roles. Without one it can only ask the
        generic paper.
      </StepHead>

      {resume ? (
        <div className="mk-card flex items-start gap-4 p-5">
          <FileCheck2 className="mt-0.5 h-5 w-5 shrink-0 text-[var(--mk-good)]" strokeWidth={2} />
          <div className="min-w-0">
            <p className="text-[0.9375rem] font-medium text-[var(--mk-ink)]">
              {resume.filename}
            </p>
            <p className="mt-1 text-[var(--mk-micro)] text-[var(--mk-muted)]">
              {resume.parsed_skills?.length
                ? `${resume.parsed_skills.length} skills read from it.`
                : 'Uploaded. The panel will read it before your first question.'}
            </p>
          </div>
        </div>
      ) : (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            const file = e.dataTransfer.files?.[0];
            if (file) submit(file);
          }}
          className={cn(
            'rounded-[var(--mk-r-card)] border border-dashed p-10 text-center transition-colors',
            dragging
              ? 'border-[var(--mk-gold)] bg-[var(--mk-gold-soft)]'
              : 'border-[var(--mk-border)] bg-[var(--mk-surface)]',
          )}
        >
          <Upload className="mx-auto h-6 w-6 text-[var(--mk-muted)]" strokeWidth={1.8} />
          <p className="mt-4 text-[0.9375rem] text-[var(--mk-ink)]">
            Drop your resume here, or
          </p>
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            disabled={isUploading}
            className="mk-btn mk-btn-ghost mt-4"
          >
            {isUploading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            {isUploading ? 'Reading it…' : 'Choose a file'}
          </button>
          <p className="mt-4 text-[var(--mk-micro)] text-[var(--mk-muted)]">
            PDF or DOCX, up to {RESUME_MAX_MB} MB.
          </p>
          <input
            ref={inputRef}
            type="file"
            accept=".pdf,.docx"
            hidden
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) submit(file);
              /* Reset so choosing the SAME file twice still fires a change event — otherwise a
                 failed upload cannot be retried without picking a different file. */
              e.target.value = '';
            }}
          />
        </div>
      )}

      <Actions>
        <button type="button" onClick={onBack} className="mk-btn mk-btn-ghost">
          <ArrowLeft className="h-4 w-4" strokeWidth={2.2} />
          Back
        </button>
        <button type="button" onClick={onNext} className="mk-btn mk-btn-primary">
          {resume ? 'Continue' : 'Do this later'}
          <ArrowRight className="mk-arrow h-4 w-4" strokeWidth={2.2} />
        </button>
      </Actions>

      {/* The cross-border processing disclosure. Rendered by the same component the profile
          and interview pages use, so there is exactly one wording and one consent record. */}
      {awaitingConsent && (
        <ResumeConsentGate onGranted={() => consentGranted()} onCancel={cancelConsent} />
      )}
    </>
  );
}

/* ── 3 · BACKGROUND ───────────────────────────────────────────────────────*/
const YEAR_BANDS = [
  { years: 0, label: 'Final year / fresher', detail: 'Campus drives and graduate programmes' },
  { years: 1, label: 'Under a year', detail: 'Internship or first role' },
  { years: 2, label: '1 – 3 years', detail: 'Switching, or a lateral drive' },
  { years: 4, label: '3 years or more', detail: 'Experienced hire' },
];

function BackgroundStep({
  years,
  bio,
  onYears,
  onBio,
  saving,
  onBack,
  onNext,
}: {
  years: number | null;
  bio: string;
  onYears: (n: number) => void;
  onBio: (s: string) => void;
  saving: boolean;
  onBack: () => void;
  onNext: () => void;
}) {
  return (
    <>
      <StepHead eyebrow="Step three" title="How much of this" turn="have you done before?">
        It changes the difficulty it opens on and how hard it pushes when an answer is thin.
        Optional — you can change both later in your profile.
      </StepHead>

      <div className="grid gap-2 sm:grid-cols-2">
        {YEAR_BANDS.map((b) => (
          <Choice
            key={b.label}
            selected={years === b.years}
            onSelect={() => onYears(b.years)}
            title={b.label}
            detail={b.detail}
          />
        ))}
      </div>

      <div className="mt-9">
        <label htmlFor="bio" className="mk-eyebrow">
          Anything it should know
        </label>
        <textarea
          id="bio"
          value={bio}
          onChange={(e) => onBio(e.target.value)}
          rows={4}
          maxLength={600}
          placeholder="Final-year CSE, mostly Java and Spring Boot. Built a payments side project. Weak on DP."
          className="mt-4 w-full rounded-[var(--mk-r-control)] border border-[var(--mk-border)] bg-[var(--mk-surface)] p-4 text-[0.9375rem] leading-[1.6] text-[var(--mk-ink)] outline-none transition-colors placeholder:text-[var(--mk-muted)] focus:border-[var(--mk-gold)]"
        />
        <p className="mt-2 text-[var(--mk-micro)] text-[var(--mk-muted)]">
          The interviewer reads this before it writes your first question.
          <span className="mk-num ml-2">{bio.length}/600</span>
        </p>
      </div>

      <Actions>
        <button type="button" onClick={onBack} className="mk-btn mk-btn-ghost">
          <ArrowLeft className="h-4 w-4" strokeWidth={2.2} />
          Back
        </button>
        <button
          type="button"
          onClick={onNext}
          disabled={saving}
          className="mk-btn mk-btn-primary disabled:opacity-45"
        >
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          Continue
          <ArrowRight className="mk-arrow h-4 w-4" strokeWidth={2.2} />
        </button>
      </Actions>
    </>
  );
}

/* ── 4 · READY ────────────────────────────────────────────────────────────
   THE ORDER OF THESE THREE IS THE WHOLE POINT OF THE WIZARD.

   A new account has one free communication round and unlimited quizzes, and zero
   interview credits. Leading with "Start an interview" sends a candidate who has
   just spent two minutes on setup straight into a 402 — which is the single worst
   moment in the product to meet a paywall, because it reads as a bait rather than
   as a price.

   So the two free things come first and say plainly that they are free, and the
   paid one is third and says what it is. Nobody is worse off and the first thing
   a new account does is get a real score. */
function ReadyStep({
  company,
  program,
  hasResume,
}: {
  company: string | null;
  program: string | null;
  hasResume: boolean;
}) {
  const interviewHref = company
    ? `/interview?company=${encodeURIComponent(company)}${
        program ? `&program=${encodeURIComponent(program)}` : ''
      }`
    : '/interview';

  return (
    <>
      <StepHead
        eyebrow="You're set up"
        title={company ? `The panel is ready for ${company}.` : 'The panel is ready.'}
        turn="Start with something free."
      >
        {hasResume
          ? 'Your resume is in and your target is set. Two of these cost nothing.'
          : 'Your target is set. You can add a resume any time from your profile — the interview round needs one, the two free rounds do not.'}
      </StepHead>

      <div className="space-y-3">
        <Route
          href="/communication"
          icon={<Mic className="h-5 w-5" strokeWidth={1.9} />}
          title="Speak for two minutes"
          detail="One full communication round, scored on pace, structure and filler. Free on every account."
          badge="Free"
          primary
        />
        <Route
          href="/quiz"
          icon={<MessageSquare className="h-5 w-5" strokeWidth={1.9} />}
          title="Take a quiz"
          detail={
            company
              ? `Questions generated for ${company}, or drawn from the curated bank. Never charged, on any plan.`
              : 'Generated for your target, or drawn from the curated bank. Never charged, on any plan.'
          }
          badge="Free"
        />
        <Route
          href={interviewHref}
          icon={<FileCheck2 className="h-5 w-5" strokeWidth={1.9} />}
          title="Set up a full mock interview"
          detail="Adaptive questions, cross-questioning, and the scored report at the end. Bought one session at a time."
          badge="Paid"
        />
      </div>

      <p className="mt-8 text-[var(--mk-micro)] text-[var(--mk-muted)]">
        Or go to{' '}
        <Link
          href="/dashboard"
          className="underline decoration-[var(--mk-border)] underline-offset-4 transition-colors hover:text-[var(--mk-ink)]"
        >
          your dashboard
        </Link>
        .
      </p>
    </>
  );
}

function Route({
  href,
  icon,
  title,
  detail,
  badge,
  primary,
}: {
  href: string;
  icon: React.ReactNode;
  title: string;
  detail: string;
  badge: string;
  primary?: boolean;
}) {
  return (
    <Link
      href={href}
      className={cn(
        'mk-card group flex items-start gap-4 p-5 transition-all duration-200 hover:-translate-y-[2px]',
        primary && 'border-[var(--mk-gold-line)]',
      )}
    >
      <span
        className={cn(
          'grid h-11 w-11 shrink-0 place-items-center rounded-[var(--mk-r-control)]',
          primary
            ? 'bg-[var(--mk-gold-soft)] text-[var(--mk-gold-ink)]'
            : 'bg-[rgb(59_43_28/0.05)] text-[var(--mk-body)]',
        )}
      >
        {icon}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-2">
          <span className="font-[family-name:var(--mk-font-display)] text-[1.0625rem] text-[var(--mk-ink)]">
            {title}
          </span>
          <span
            className={cn(
              'rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.1em]',
              badge === 'Free'
                ? 'bg-[var(--mk-good-bg)] text-[var(--mk-good)]'
                : 'bg-[rgb(59_43_28/0.06)] text-[var(--mk-muted)]',
            )}
          >
            {badge}
          </span>
        </span>
        <span className="mt-1 block text-[var(--mk-micro)] leading-[1.55] text-[var(--mk-muted)]">
          {detail}
        </span>
      </span>
      <ArrowRight
        className="mt-1 h-4 w-4 shrink-0 text-[var(--mk-muted)] transition-transform duration-200 group-hover:translate-x-1"
        strokeWidth={2.2}
      />
    </Link>
  );
}

function Actions({ children }: { children: React.ReactNode }) {
  return <div className="mt-10 flex flex-wrap items-center gap-3">{children}</div>;
}

function Skeleton({ rows }: { rows: number }) {
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className="h-[74px] animate-pulse rounded-[var(--mk-r-control)] bg-[rgb(59_43_28/0.05)]"
        />
      ))}
    </div>
  );
}
