'use client';

import { useInterview } from '@/hooks/useInterview';
import { useTracks, usePrimaryResume } from '@/hooks/useData';
import { Play, Code2, Loader2, CheckCircle2, Sparkles, ArrowRight, ListChecks, FileCheck2 } from 'lucide-react';
import { useState, useEffect, useMemo, useRef, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { toast } from 'sonner';
import { Paywall, paywallFromError, type PaywallInfo } from '@/components/billing/Paywall';
import { InterviewReadiness } from '@/components/interview/InterviewReadiness';
import { CreditMeter } from '@/components/billing/CreditMeter';
import { parseIsTechnical } from '@/lib/interview/params';
import { FOCUS_SUGGESTIONS, addFocusTerm, focusMentions } from '@/lib/interview/focus';
import { cn } from '@/lib/utils';
import { ProgressBar } from '@/components/ui/progress-bar';
import { AIWorkingIndicator } from '@/components/ui/ai-working-indicator';

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
  /*
   * THE REST OF THE DEEP LINK, so a drive-specific entry point can hand over a fully decided
   * setup instead of a half-filled one.
   *
   * `program` is the load-bearing one. `syllabus.resolve(company, program)` keys on these two
   * strings and takes no track id, by explicit design — so a link that names the company but
   * not the program lands on the fallback path and the candidate gets the generic plan.
   *
   * `focus` is spelled `focus` here and held in state called `prompt` and sent on the wire as
   * `prompt`, while the backend's own orchestrator calls the argument `focus`. Three names for
   * one thing, and the URL is the half that a human reads and a support log records, so it
   * takes the name the backend and the docs use. That mismatch is a trap; it is named here
   * rather than silently inherited.
   */
  const requestedProgram = searchParams.get('program');
  const requestedFocus = searchParams.get('focus');
  const requestedTechnical = parseIsTechnical(searchParams.get('isTechnical'));
  const requestedAutostart = searchParams.get('autostart') === '1';
  const [selectedTrackId, setSelectedTrackId] = useState('');
  const [company, setCompany] = useState('');
  /*
   * TYPING YOUR OWN EMPLOYER DESELECTS THE CHIPS ABOVE.
   *
   * The chips and the free-text boxes were two ways of saying the same thing and both stayed
   * on at once, so a candidate typing "Morani Plastics" left "Cognizant" and "Digital Nurture
   * — Java FSE" selected. The backend has to send a track_id regardless (it is a non-null
   * foreign key), so "I chose Cognizant" and "I typed my own company and the chip is left
   * over from last time" arrived looking identical — and the panel read the track. That is
   * how a sales interview at Morani Plastics greeted somebody as an Advanced ASE at
   * Accenture.
   *
   * Deselecting makes the choice exclusive on screen, and `custom_setup` tells the backend
   * which of the two the candidate actually meant.
   */
  const [customSetup, setCustomSetup] = useState(false);
  /*
   * TECHNICAL OR NOT — ASKED, NOT INFERRED.
   *
   * The backend can infer it from the role title and does, but inference is keyword matching
   * over free text: it cannot know that "Civil Services" is the IAS exam rather than civil
   * engineering, only that it matches something. It matched civil ENGINEERING, and a UPSC
   * aspirant was offered "Structural Design".
   *
   * `null` means "infer", which is right for a catalogue track where the role is known.
   * Choosing one is a statement, and a statement beats a guess — it decides whether there is
   * a code editor at all, whether coding questions are asked, and whether the panel are
   * engineers or their own field's managers.
   */
  const [isTechnical, setIsTechnical] = useState<boolean | null>(null);
  const [program, setProgram] = useState('');
  /*
   * HAS THE CANDIDATE TYPED THEIR OWN PROGRAM?
   *
   * A ref rather than state because nothing renders differently because of it — it only decides
   * whether the derivation effect below is allowed to write. Once they have typed, it never
   * writes again: a hand-typed role is a stronger signal than anything a chip can infer, and
   * silently overwriting what somebody typed is the worst outcome available here.
   *
   * Note that this is deliberately NOT symmetrical with the company/program text boxes, which
   * clear each other. Clicking a company chip after typing a program keeps the typed program.
   * That is on purpose — typing is the stronger statement — but it is a judgement, not an
   * oversight, and it is written down here so the next person changes it on purpose too.
   */
  const programTouched = useRef(false);
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
    if (requestedProgram) {
      // Treated as typed, not derived: the link author named the program explicitly, and the
      // derivation effect below must not later overwrite it with a track name that happens to
      // differ.
      programTouched.current = true;
      setProgram((p) => p || requestedProgram);
    }
  }, [requestedProgram]);

  // The focus box. `p || …` so a candidate who has started typing is never overwritten by a
  // late re-run — the param is a starting point, not an instruction.
  useEffect(() => {
    if (requestedFocus) setPrompt((p) => p || requestedFocus);
  }, [requestedFocus]);

  // Only ever applied when the param parsed to one of the two literals. A malformed or absent
  // param leaves this at `null`, which is "work it out from the role" — today's behaviour — so
  // a mangled share link degrades to a guess rather than asserting the wrong answer and
  // removing the code editor from a Java FSE interview.
  useEffect(() => {
    if (requestedTechnical !== null) setIsTechnical(requestedTechnical);
  }, [requestedTechnical]);

  useEffect(() => {
    if (!tracks || tracks.length === 0 || selectedTrackId) return;
    if (requestedTrackId && tracks.some((t) => t.id === requestedTrackId)) {
      setSelectedTrackId(requestedTrackId);
      return;
    }
    /*
     * `?company=` WITHOUT A trackId MUST NOT FALL THROUGH TO tracks[0].
     *
     * It did, and the result was a live bug on the /prepare CTA. `/api/v1/questions/tracks`
     * orders by `InterviewTrack.name` across ALL companies, so `tracks[0]` is the
     * alphabetically first program name in the whole catalogue — "Advanced ASE", which is
     * Accenture's. Because a deep link leaves `customSetup` false, the backend reads that
     * carrier track as a real choice, and `_must_cover_block` built Accenture's must-cover
     * topics while the prompt said Cognizant. Same class of mismatch as the one the long
     * comment above `customSetup` was written for, arriving by a different door.
     *
     * So: match the requested company by name before giving up. Case-insensitively, because
     * the param is written by hand as often as it is generated.
     */
    if (requestedCompany) {
      const wanted = requestedCompany.trim().toLowerCase();
      const match = tracks.find((t) => t.company.name.trim().toLowerCase() === wanted);
      if (match) {
        setSelectedTrackId(match.id);
        return;
      }
    }
    setSelectedTrackId(tracks[0].id);
  }, [tracks, selectedTrackId, requestedTrackId, requestedCompany]);

  /*
   * THE PROGRAM IS DERIVED FROM WHICHEVER TRACK IS SELECTED. THIS IS THE FIX THAT MATTERS.
   *
   * `program` used to be written by exactly one thing: the text input near the bottom of this
   * form. Neither the company chip nor the program chip set it. So the ordinary catalogue path
   * — click Cognizant, click "Digital Nurture — Java FSE", press Build — put `program: ""` on
   * the wire. The one gesture that unambiguously names the program threw that fact away.
   *
   * That was invisible until the backend grew a per-program syllabus. `syllabus.resolve` keys
   * on (company, program) and takes NO track id, deliberately, so that a leftover carrier track
   * can never reach the decision. Which means an empty program resolves to None, which means
   * the fallback path, which means the Cognizant field research — the areas, the weightings,
   * the cross-question themes — was authored, imported, validated and then never once consulted
   * for any candidate who clicked rather than typed.
   *
   * One derivation here rather than a `setProgram` in each of the two chip handlers: two writers
   * of one field is how they drift, and this also covers every existing entry point into the
   * page (the dashboard link, the tracks grid, /prepare, the drive card) without touching any
   * of them. The DB track name is literally "Digital Nurture — Java FSE", which slugifies to
   * the exact key the syllabus index holds.
   *
   * Skipped on a custom setup, where the catalogue track is a foreign-key carrier and its name
   * is not the role; and skipped once the candidate has typed, per `programTouched`.
   */
  useEffect(() => {
    if (customSetup || programTouched.current) return;
    const selected = (tracks ?? []).find((t) => t.id === selectedTrackId);
    if (selected) setProgram(selected.name);
  }, [tracks, selectedTrackId, customSetup]);

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
    // A track id is still required on the wire — it is a non-null foreign key — so on a
    // custom setup the first track rides along purely as a carrier. `custom_setup` tells the
    // backend to ignore it for everything that decides what the interview is about.
    const carrierTrackId = selectedTrackId || tracks?.[0]?.id;
    if (!carrierTrackId) return;
    // THE ROLE IS THE ONE THING THAT CANNOT BE GUESSED. With a custom employer there is no
    // catalogue entry to fall back on, so a blank role leaves the interview with nothing to
    // be about — which is precisely when it reaches for the leftover track.
    if (customSetup && !program.trim()) return;
    /*
     * THE PROGRAM THAT GOES ON THE WIRE, DECIDED HERE RATHER THAN TRUSTED FROM STATE.
     *
     * The effect above keeps the visible box in step with the selected track, and that is the
     * half the candidate can see and edit. This is the guarantee. It exists because the effect
     * can be legitimately out of step — somebody types a program, clears the box again, and the
     * effect has no reason to re-run because none of its dependencies moved — and "the box
     * looks empty so we sent nothing" is exactly the failure that made the whole Cognizant
     * syllabus dead code in the first place.
     *
     * Applying the same rule at the send site is not a second source of truth: blank plus a
     * catalogue track means the track's name, because on a catalogue track the track name IS
     * the program. On a custom setup it stays blank, because there the track is a foreign-key
     * carrier and its name is some other company's job title — which is precisely the confusion
     * `custom_setup` exists to prevent.
     */
    const selectedTrack = (tracks ?? []).find((t) => t.id === selectedTrackId);
    const effectiveProgram = program.trim() || (customSetup ? '' : selectedTrack?.name ?? '');
    setPaywall(null);
    createPlan.mutate(
      {
        trackId: carrierTrackId,
        company,
        program: effectiveProgram,
        prompt,
        resumeText,
        customSetup,
        isTechnical,
      },
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

  /*
   * AUTOSTART — ONE CLICK FROM THE DRIVE CARD, AND AT MOST ONE CHARGE.
   *
   * `?autostart=1` says "submit this form for me". It is honoured only when every condition for
   * a GOOD interview already holds, and it fires at most once per mount. Both of those are
   * about money, not tidiness.
   *
   * POST /api/v1/interview/plan calls `consume(db, user_id, "interview")` BEFORE it generates
   * anything, and the endpoint is rate-limited. So each fire spends one of a free user's two
   * interviews whether or not the candidate ever reads the plan. Without the ref, this effect
   * re-runs whenever `usePrimaryResume` refetches — on window focus, on reconnect — and buys a
   * second interview; and a browser refresh of a shared link buys a third. A link passed around
   * a placement WhatsApp group would empty an allowance in a couple of taps.
   *
   * THE RESUME GATE IS NOT COSMETIC. The server does not require a resume; it quietly falls
   * back to the generic question set when there is none. So an ungated autostart would not
   * fail — it would succeed, silently spend a paid interview, and hand back the worst version
   * of the product to somebody whose first impression it is. When there is no resume this
   * effect does nothing at all: no spinner, no toast, no charge. The candidate simply lands on
   * a form that is already filled in except for the one field only they can supply, with the
   * explanation already beside it.
   *
   * The `plan` and `paywall` guards stop it re-firing behind the two screens that render
   * INSTEAD of this form: re-submitting under a plan the candidate is still reading would throw
   * their plan away, and re-submitting under a paywall would buy a second refusal.
   */
  const autostarted = useRef(false);
  useEffect(() => {
    if (!requestedAutostart || autostarted.current) return;
    if (!selectedTrackId || !hasResume) return;
    if (createPlan.isPending || plan || paywall) return;
    // A deep link is always a catalogue path — nothing in a URL sets `customSetup`, only typing
    // an employer does. So this being true means the candidate started editing the form while
    // the resume query was still in flight, and they have taken over. Bailing WITHOUT burning
    // the one-shot ref matters: `handleGenerate` refuses a custom setup with a blank role, so
    // arming the ref here would spend the autostart on a call that returns immediately and
    // leave the link looking like it did nothing.
    if (customSetup) return;
    autostarted.current = true;
    handleGenerate();
    // `handleGenerate` is intentionally absent from the dependency list. It is rebuilt on every
    // render, so including it would re-run this effect on every keystroke — and the deps that
    // ARE listed are the readiness conditions, which is what this effect is actually watching.
    // The one-shot ref makes re-entry impossible either way; this is about not pretending the
    // dependency list means something it does not.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestedAutostart, selectedTrackId, hasResume, createPlan.isPending, plan, paywall, customSetup]);

  // Appends through the functional form of setState rather than reading `prompt` from the
  // closure, so two fast taps on two chips both land — the second would otherwise be computed
  // from the pre-first-tap text and silently drop the first.
  const addFocus = (term: string) => setPrompt((current) => addFocusTerm(current, term));

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

          {/* IMMEDIATELY ABOVE THE BUTTON, which is the only placement that works. These are
              ten-second fixes — move rooms, plug in headphones, upload a resume — and they are
              worth nothing once the mic is open, because the candidate gets one attempt at the
              interview. Higher up the page they are read before the decision is real; lower,
              after it has been made. */}
          <div className="mb-5">
            <InterviewReadiness />
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
        {/* ── THE KIND OF INTERVIEW, FIRST ──────────────────────────────────
            Above the company, because it changes more than the company does: it decides
            whether there is a code editor at all, whether coding questions are asked, and
            whether the panel are engineers or their own field's managers.

            "Work it out" stays the default and is right for a catalogue track, where the
            role is known. The other two are for when it is not — and inference is keyword
            matching over free text, so it cannot tell that "Civil Services" is the IAS exam
            rather than civil engineering. It could not, and a UPSC aspirant was offered
            structural design. */}
        <p className="mb-3 text-xs font-semibold uppercase tracking-widest text-muted-foreground">
          What kind of interview?
        </p>
        <div className="mb-6 flex flex-wrap gap-2">
          {([
            { value: null, label: 'Work it out for me', hint: 'From the role you name' },
            { value: true, label: 'Technical', hint: 'Coding, DSA, a code editor' },
            { value: false, label: 'Non-technical', hint: 'Sales, HR, UPSC — no editor' },
          ] as const).map((opt) => {
            const active = isTechnical === opt.value;
            return (
              <button
                key={String(opt.value)}
                type="button"
                onClick={() => setIsTechnical(opt.value)}
                className={cn(
                  'rounded-xl border px-4 py-2.5 text-left transition-colors',
                  active
                    ? 'border-primary bg-primary/10'
                    : 'border-border/60 hover:border-border hover:bg-secondary/50',
                )}
              >
                <span
                  className={cn(
                    'block text-sm font-medium',
                    active ? 'text-primary' : 'text-foreground',
                  )}
                >
                  {opt.label}
                </span>
                <span className="block text-[11px] text-muted-foreground">{opt.hint}</span>
              </button>
            );
          })}
        </div>

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
                      // Choosing from the catalogue is the other direction of the same
                      // exclusivity: the typed company is now the chosen one, not a custom
                      // employer, so the track becomes meaningful again.
                      setCustomSetup(false);
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
              onChange={(e) => {
                const next = e.target.value;
                setCompany(next);
                // Any typing here means the catalogue is not what they want. Clearing the
                // track is what stops the backend having two answers to choose between.
                if (next.trim()) {
                  setCustomSetup(true);
                  setSelectedTrackId('');
                  // AND DROP A PROGRAM THAT WAS DERIVED RATHER THAN TYPED. The box is now
                  // showing the catalogue track's name — "Digital Nurture — Java FSE" — beside
                  // a company called Morani Plastics, which is the same two-answers-at-once
                  // confusion the chips deselect to avoid, and it would sail past the
                  // custom-setup required check because the field is not empty. A typed program
                  // is kept: that one the candidate meant.
                  if (!programTouched.current) setProgram('');
                } else {
                  setCustomSetup(false);
                }
              }}
              placeholder="e.g. Cognizant, Infosys, TCS…"
              className="w-full rounded-xl border border-border/50 bg-surface-elevated px-4 py-3 text-sm focus:border-primary/40 focus:outline-none focus:ring-2 focus:ring-primary/20"
            />
          </div>
          <div>
            <label className="mb-1.5 block text-sm font-medium">
              Program / role
              {/* REQUIRED ONLY ON A CUSTOM SETUP, and said out loud rather than enforced
                  silently. With a catalogue company the track already names the role; with
                  your own employer there is nothing else to go on, and a blank here is
                  exactly when the interview reaches for a leftover track and becomes an
                  interview for a different job. */}
              {customSetup && <span className="ml-1 text-destructive">*</span>}
            </label>
            <input
              value={program}
              onChange={(e) => {
                // Typing here retires the derivation effect for the rest of the session. Set
                // before the state write so it is already true when the effect next considers
                // running; a ref, so this does not itself schedule a render.
                programTouched.current = true;
                setProgram(e.target.value);
              }}
              placeholder={
                customSetup ? 'e.g. Sales Executive, HR Generalist, Analyst…' : 'e.g. GenC, GenC Next, Java FSE…'
              }
              className={cn(
                'w-full rounded-xl border bg-surface-elevated px-4 py-3 text-sm focus:outline-none focus:ring-2',
                customSetup && !program.trim()
                  ? 'border-destructive/50 focus:border-destructive/60 focus:ring-destructive/20'
                  : 'border-border/50 focus:border-primary/40 focus:ring-primary/20',
              )}
            />
            {customSetup && !program.trim() && (
              <p className="mt-1.5 text-xs text-destructive">
                Tell us the role — it decides what you are asked, and whether there is a code
                editor at all.
              </p>
            )}
          </div>
        </div>

        {/* ── The focus box ────────────────────────────────────────────────
            IT WAS LABELLED "Anything specific?" AND READ LIKE A COMMENT CARD.

            A candidate filled it in with the topics they were weakest on, sat the interview,
            and was asked about none of them — so they reported that the box does nothing.
            Half of that was the backend, which is being fixed separately. The other half is
            this surface, and it was two failures of its own.

            First, the label asked a question rather than making a promise. "Anything specific?"
            is what a form says when it is collecting free-text feedback nobody will read; it
            never claimed the words would change the interview, so there was nothing to hold it
            to. The label now says what the box DOES.

            Second — and this is the part that made the box hard to use even when it worked — a
            blank textarea with one example in the placeholder gave no clue which vocabulary
            lands. The backend matches a named topic against the areas and sub-topics of the
            resolved syllabus; a term it recognises pulls plan slots towards that area, and a
            term it does not recognise is simply passed to the panel as prose. Those two
            outcomes are invisibly different from here. The chips are the recognised vocabulary,
            made visible and one tap away, so the common case stops being a guess.

            THE CHIPS ARE THE SIX AREAS THE SYLLABUS ACTUALLY HAS. Project and HR are not
            among them on purpose: they are covered in every technical interview regardless
            (they are separate stages, not weighted areas), so offering them as a "focus" would
            promise a steer that has nothing to steer. The note under the box says so rather
            than leaving their absence to be read as an omission. */}
        <div className="mb-5">
          <label className="mb-1.5 block text-sm font-medium" htmlFor="focus-box">
            Topics you want the panel to push on{' '}
            <span className="text-muted-foreground">(optional)</span>
          </label>
          <p className="mb-2.5 text-xs text-muted-foreground">
            Name an area and more of the round goes there — it does not replace the rest of the
            interview, it changes the balance. Tap to add, or write it your own way.
          </p>
          <div className="mb-2.5 flex flex-wrap gap-1.5">
            {FOCUS_SUGGESTIONS.map((term) => {
              const added = focusMentions(prompt, term);
              return (
                <button
                  key={term}
                  type="button"
                  disabled={added}
                  onClick={() => addFocus(term)}
                  className={cn(
                    'rounded-full border px-3 py-1 text-xs font-medium transition-colors',
                    added
                      ? 'cursor-default border-primary/30 bg-primary/10 text-primary'
                      : 'border-border/60 bg-surface text-muted-foreground hover:border-primary/50 hover:text-foreground',
                  )}
                >
                  {added ? '✓ ' : '+ '}
                  {term}
                </button>
              );
            })}
          </div>
          <textarea
            id="focus-box"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={2}
            placeholder="e.g. OOP cross-questions and SQL joins; I am weakest on multithreading."
            className="w-full resize-none rounded-xl border border-border/50 bg-surface-elevated px-4 py-3 text-sm focus:border-primary/40 focus:outline-none focus:ring-2 focus:ring-primary/20"
          />
          <p className="mt-2 text-[11px] text-muted-foreground">
            Leave it blank for the full spread of the real round. Your project and the HR
            questions are asked either way.
          </p>
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

        {/* WHAT IS STOPPING THEM, STATED LOUDLY, PLUS THE ROOM ADVICE.
            This used to be one line of small grey text above a large button. The button is
            DISABLED without a resume, so a candidate who missed that line saw a dead control
            and no explanation — and a dead control with no reason is indistinguishable from a
            broken app. That is the most likely reason somebody lands here and leaves without
            starting, which is precisely the `dropped_off` segment the admin view reports, and
            it is the largest group. `resumeSatisfied` is passed because this form accepts
            PASTED text as well as a stored file, which the card cannot see on its own. */}
        <div className="mb-4">
          <InterviewReadiness resumeSatisfied={hasResume} emphasis="required" />
        </div>

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
          {/* THE BUTTON EXPLAINS ITSELF WHEN IT CANNOT BE PRESSED.
              A greyed-out "Build my interview plan" tells the candidate nothing about which of
              the two requirements is missing, and they are one tap from leaving. Saying what it
              is waiting for turns a dead end into an instruction. */}
          {createPlan.isPending ? (
            <>
              <Sparkles className="h-4 w-4 animate-pulse" /> Building your tailored interview…
            </>
          ) : !selectedTrackId ? (
            <>Choose a role above to continue</>
          ) : !hasResume ? (
            <>Add your resume to continue</>
          ) : (
            <>
              Build my interview plan <ArrowRight className="h-4 w-4" />
            </>
          )}
        </button>
        {/* A LOADING BAR FOR THE LONGEST WAIT IN THE PRODUCT.
            Requested: "try to show a loading bar while building the interview ... so that the
            user must not feel that something is stucked."

            Building a plan is one AI call with a 110-second ceiling, and until now the only
            sign of life was a pulsing sparkle inside the button. For a minute-long wait that
            is not enough — there is no way to tell a working request from a dead tab.

            The bar deliberately never completes: see components/ui/progress-bar.tsx. A bar
            that fills to 100% and then sits there is worse than none, because a full bar doing
            nothing reads as broken. 35s as the expected duration is measured against a warm
            deploy; a cold one takes longer and the curve keeps creeping, which is the honest
            shape for "taking longer than usual". */}
        {createPlan.isPending && (
          <div className="mt-4">
            <ProgressBar expectedMs={35_000} label="Building your interview" />
            <div className="mt-2 flex justify-center">
              <AIWorkingIndicator
                messages={[
                  'Reading your resume…',
                  'Looking up how this company really interviews…',
                  'Choosing the areas you will be asked about…',
                  'Writing your questions…',
                  'Almost there — this one takes a moment…',
                ]}
                intervalMs={6000}
              />
            </div>
          </div>
        )}
        {createPlan.isPending && (
          <p className="mt-3 text-center text-xs text-muted-foreground">
            Crafting questions for your company, program and resume — this usually takes a few
            seconds. Hang tight.
          </p>
        )}
        {/* DO NOT CLOSE IT, AND WHY. This is the longest wait in the product and the one most
            likely to be read as a stuck page, so it is the wait people abandon. The interview
            is charged when it starts, so abandoning here does not cost the attempt — but
            leaving does throw away a minute of work and, on a slow connection, the candidate
            usually returns to start again. Said plainly, and only while the request is in
            flight: a standing warning on a page that is idle is noise. */}
        {createPlan.isPending && (
          <p
            role="status"
            className="mx-auto mt-2 max-w-md text-center text-xs font-medium text-accent-amber-ink"
          >
            Please keep this page open while your interview is being prepared — closing or
            reloading now will discard it and you will have to start again.
          </p>
        )}
      </div>
    </div>
  );
}
