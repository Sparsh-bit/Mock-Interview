'use client';

import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import TimelineLayout, { TimelineItem } from '@/components/lightswind-pro/timeline-layout';
import {
  ArrowRight,
  BookOpen,
  Check,
  ChevronLeft,
  Clock,
  Dumbbell,
  Info,
  Loader2,
  PlayCircle,
  RefreshCw,
  Sliders,
  Target,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { DataError } from '@/components/ui/data-error';
import {
  usePrepProgress,
  useRecruiters,
  useRoadmap,
  useToggleProgress,
  type Recruiter,
  type RoadmapTopic,
} from '@/hooks/useData';
import { cn } from '@/lib/utils';
import { brandFill, brandInk } from '@/lib/brand-accent';

export const runtime = 'edge';

/**
 * Target company → study plan.
 *
 * REBUILT AS A DOCUMENT, NOT A DASHBOARD. The previous version nested cards four
 * deep — a phase card holding a topic card holding a subtopic card holding a
 * resource card — behind an accordion that opened one topic at a time. Reaching a
 * video took a company click, a scroll, an expand, another scroll and a click, and
 * opening the next topic closed the one you were reading.
 *
 * A study plan is a document. It is read top to bottom, everything visible,
 * structured by typography and hairline rules rather than by boxes. So:
 *
 *   * no nested cards — one surface, sections divided by rules
 *   * nothing collapsed — every link is reachable without a click
 *   * the controls are sticky, so changing weeks never means scrolling back up
 *   * one accent (the company's hue, re-rendered at the palette's own
 *     saturation and lightness — lib/brand-accent.ts), carrying state only — progress and
 *     completion. Never decoration.
 *
 * Radii follow the nesting rule: the page surface is rounded-2xl (16px) with 16px
 * padding, so anything sitting directly inside it is rounded-lg (8px). Equal radii
 * nested inside each other is the most reliable tell of an unconsidered UI.
 */

const TIERS = [
  { key: 'mass_recruiter', label: 'Mass recruiters', blurb: 'Highest intake. Fundamentals and aptitude decide it.' },
  { key: 'consulting', label: 'Consulting & IT', blurb: 'Smaller intake, higher bar, communication counts.' },
  { key: 'product', label: 'Product companies', blurb: 'Smallest intake. Algorithms dominate.' },
];

const EASE = [0.16, 1, 0.3, 1] as const;

/**
 * Both views of this page — pick a company, then read the plan — open with a
 * title in this treatment. Larger than the standard PageHeader on purpose: this
 * is the entry screen of a flow, not a section of the app. Weight and tracking
 * still match it, so it reads as the same family at a bigger size.
 *
 * It is a constant because the two h1s previously carried identical hand-typed
 * classes, which is exactly the setup where a change lands on one and misses
 * the other.
 */
const FLOW_TITLE =
  'mt-2 text-[clamp(1.9rem,3.4vw,2.5rem)] font-medium leading-[1.1] tracking-[-0.03em]';

// ─── Company picker ───────────────────────────────────────────────────────────

function CompanyCard({ r, onPick }: { r: Recruiter; onPick: () => void }) {
  // The company's hue at the palette's saturation and lightness — never the
  // raw brand hex. See lib/brand-accent.ts for why.
  const accent = brandFill(r.accent);
  return (
    <button
      type="button"
      onClick={onPick}
      className="group relative overflow-hidden rounded-2xl border border-border bg-surface-elevated p-5 text-left transition-[color,background-color,border-color,box-shadow,transform,opacity] duration-200 hover:-translate-y-0.5 hover:border-foreground/20 hover:shadow-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
    >
      {/* A single hairline of the company's colour. The whole card is not tinted —
          twelve tinted cards in a grid is a colour-chart, not a page. */}
      <span aria-hidden className="absolute inset-x-0 top-0 h-px" style={{ backgroundColor: accent }} />

      <div className="flex items-start justify-between gap-3">
        <div
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-sm font-semibold text-white"
          style={{ backgroundColor: accent }}
        >
          {r.name.slice(0, 2).toUpperCase()}
        </div>
        <ArrowRight className="mt-1 h-4 w-4 text-muted-foreground/40 transition-[color,background-color,border-color,box-shadow,transform,opacity] group-hover:translate-x-0.5 group-hover:text-foreground" />
      </div>

      <h3 className="mt-4 text-base font-semibold tracking-[-0.01em]">{r.name}</h3>
      <p className="mt-0.5 text-xs text-muted-foreground">{r.hires_per_year}</p>

      <dl className="mt-4 space-y-1 border-t border-border/60 pt-3 text-[11px]">
        <div className="flex justify-between gap-3">
          <dt className="text-muted-foreground">Drive</dt>
          <dd className="truncate text-right font-medium">{r.drive_window}</dd>
        </div>
        <div className="flex justify-between gap-3">
          <dt className="text-muted-foreground">Programs</dt>
          <dd className="font-medium tabular-nums">{r.programs.length}</dd>
        </div>
      </dl>
    </button>
  );
}

// ─── One subtopic: a single row, everything on it ─────────────────────────────

function SubtopicRow({
  s,
  done,
  accent,
  onToggle,
}: {
  s: RoadmapTopic['subtopics'][number];
  done: boolean;
  accent: string;
  onToggle: () => void;
}) {
  const links = [
    s.video && { ...s.video, Icon: PlayCircle, kind: 'Video' },
    s.doc && { ...s.doc, Icon: BookOpen, kind: 'Read' },
    s.practice && { ...s.practice, Icon: Dumbbell, kind: 'Practice' },
  ].filter(Boolean) as Array<{ title: string; url: string; Icon: typeof BookOpen; kind: string }>;

  return (
    <div
      id={`sub-${s.id}`}
      className="group flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border/50 py-2.5 last:border-0"
    >
      <button
        type="button"
        onClick={onToggle}
        aria-pressed={done}
        aria-label={`${done ? 'Mark not done' : 'Mark done'}: ${s.name}`}
        className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-1"
        style={{
          borderColor: done ? accent : 'hsl(var(--border))',
          backgroundColor: done ? accent : 'transparent',
        }}
      >
        {done && <Check className="h-3 w-3 text-white" strokeWidth={3} />}
      </button>

      <span
        className={cn(
          'min-w-0 flex-1 text-sm font-medium transition-colors',
          done && 'text-muted-foreground line-through',
        )}
      >
        {s.name}
      </span>

      <span className="shrink-0 font-mono text-[11px] tabular-nums text-muted-foreground">
        {Math.round(s.minutes / 60)}h
      </span>

      {/* Links live on the row, right-aligned, so the whole column scans as one
          list of destinations instead of being buried under each item. */}
      <div className="flex shrink-0 items-center gap-1">
        {links.map((l) => (
          <a
            key={l.kind}
            href={l.url}
            target="_blank"
            rel="noopener noreferrer"
            title={l.title}
            className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
          >
            <l.Icon className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">{l.kind}</span>
          </a>
        ))}
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function PreparePage() {
  const router = useRouter();
  const { data: recruiters, isLoading, error, refetch, isFetching: refetching } = useRecruiters();

  const [selected, setSelected] = useState<Recruiter | null>(null);
  const [weeks, setWeeks] = useState(8);
  const [hours, setHours] = useState(10);
  const [showControls, setShowControls] = useState(false);

  const { data: roadmap, isFetching } = useRoadmap(selected?.slug ?? null, weeks, hours);
  const { data: progress } = usePrepProgress();
  const toggle = useToggleProgress();

  const doneSet = useMemo(() => new Set(progress?.completed ?? []), [progress]);

  const { total, doneCount } = useMemo(() => {
    const all = (roadmap?.phases ?? []).flatMap((p) => p.topics).flatMap((t) => t.subtopics);
    return { total: all.length, doneCount: all.filter((s) => doneSet.has(s.id)).length };
  }, [roadmap, doneSet]);

  const pct = total ? Math.round((doneCount / total) * 100) : 0;

  if (isLoading) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error || !recruiters?.length) {
    return (
      <DataError
        title="Company list unavailable"
        error={error}
        onRetry={() => refetch()}
        retrying={refetching}
      >
        <Button variant="ghost" onClick={() => router.push('/interview')}>
          Start an interview instead
        </Button>
      </DataError>
    );
  }

  // ── The plan ───────────────────────────────────────────────────────────────
  if (selected) {
    const accent = brandFill(selected.accent);

    return (
      <div className="mx-auto max-w-4xl pb-24">
        {/* Sticky control bar. The single biggest usability fix: progress and the
            plan controls stay reachable from anywhere in a long document, so
            changing "weeks until the drive" never means scrolling back to the top. */}
        <div className="sticky top-0 z-30 -mx-4 mb-8 border-b border-border/70 bg-background/85 px-4 py-3 backdrop-blur-xl">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setSelected(null)}
              className="flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
            >
              <ChevronLeft className="h-4 w-4" />
              <span className="hidden sm:inline">Companies</span>
            </button>

            <div className="h-5 w-px bg-border" />

            <div className="flex min-w-0 items-center gap-2">
              <span
                className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-[10px] font-bold text-white"
                style={{ backgroundColor: accent }}
              >
                {selected.name.slice(0, 2).toUpperCase()}
              </span>
              <span className="truncate text-sm font-semibold">{selected.name}</span>
            </div>

            <div className="ml-auto flex items-center gap-3">
              {/* Progress as a hairline bar and a number — legible at a glance,
                  no chart needed. */}
              <div className="hidden items-center gap-2 sm:flex">
                <div className="h-1 w-24 overflow-hidden rounded-full bg-secondary">
                  <motion.div
                    className="h-full rounded-full"
                    style={{ backgroundColor: accent }}
                    animate={{ width: `${pct}%` }}
                    transition={{ duration: 0.45, ease: EASE }}
                  />
                </div>
                <span className="font-mono text-xs tabular-nums text-muted-foreground">
                  {doneCount}/{total}
                </span>
              </div>

              <button
                onClick={() => setShowControls((v) => !v)}
                aria-expanded={showControls}
                className={cn(
                  'flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors',
                  showControls
                    ? 'border-foreground/20 bg-secondary text-foreground'
                    : 'border-border text-muted-foreground hover:text-foreground',
                )}
              >
                <Sliders className="h-3.5 w-3.5" />
                {weeks}w · {hours}h
              </button>
            </div>
          </div>

          {/* Controls unfold from the button that opened them, rather than
              appearing from nowhere. */}
          <motion.div
            initial={false}
            animate={{ height: showControls ? 'auto' : 0, opacity: showControls ? 1 : 0 }}
            transition={{ duration: 0.28, ease: EASE }}
            className="overflow-hidden"
          >
            <div className="grid gap-5 pb-1 pt-4 sm:grid-cols-2">
              {[
                { id: 'weeks', label: 'Weeks until the drive', v: weeks, set: setWeeks, min: 2, max: 24 },
                { id: 'hours', label: 'Hours per week', v: hours, set: setHours, min: 3, max: 40 },
              ].map((c) => (
                <div key={c.id}>
                  <div className="mb-1.5 flex items-baseline justify-between">
                    <label htmlFor={c.id} className="text-xs text-muted-foreground">
                      {c.label}
                    </label>
                    <span className="font-mono text-xs font-semibold tabular-nums">{c.v}</span>
                  </div>
                  <input
                    id={c.id}
                    type="range"
                    min={c.min}
                    max={c.max}
                    value={c.v}
                    onChange={(e) => c.set(Number(e.target.value))}
                    className="w-full accent-primary"
                  />
                </div>
              ))}
            </div>
          </motion.div>
        </div>

        {/* Title block */}
        <header className="mb-10">
          <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
            Study plan
          </p>
          <h1 className={FLOW_TITLE}>
            {selected.name}
          </h1>
          <p className="mt-3 max-w-2xl text-sm leading-relaxed text-muted-foreground">
            {selected.business_context || selected.short}
          </p>

          <dl className="mt-6 grid grid-cols-2 gap-x-6 gap-y-4 border-t border-border pt-5 sm:grid-cols-4">
            {[
              { k: 'Total', v: `${roadmap?.total_hours ?? 0}h` },
              { k: 'Ready by', v: roadmap ? new Date(roadmap.target_date).toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) : '—' },
              { k: 'Topics', v: `${roadmap?.phases.reduce((n, p) => n + p.topics.length, 0) ?? 0}` },
              { k: 'Done', v: `${pct}%` },
            ].map((s) => (
              <div key={s.k}>
                <dt className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                  {s.k}
                </dt>
                <dd className="mt-1 text-xl font-semibold tabular-nums tracking-[-0.02em]">{s.v}</dd>
              </div>
            ))}
          </dl>
        </header>

        {/* Feasibility, stated inline as a note rather than as an alarm card. */}
        {roadmap?.feasibility_warning && (
          <div className="mb-8 flex gap-2.5 rounded-lg border-l-2 border-foreground/20 bg-secondary/40 py-3 pl-3 pr-4">
            <Info className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
            <div className="text-xs leading-relaxed text-muted-foreground">
              {roadmap.feasibility_warning}
              {roadmap.omitted_topics.length > 0 && (
                <span className="mt-1 block">Left out: {roadmap.omitted_topics.join(' · ')}</span>
              )}
            </div>
          </div>
        )}

        {/* ── The plan itself ──────────────────────────────────────────────────
            On a spine, because a study plan IS a sequence and a stack of sections does not
            say so. The line draws itself as each phase scrolls in, which is the shape a
            candidate counting weeks to a drive actually needs to see. The phase content is
            unchanged — TimelineItem supplies the spine and node and nothing else. */}
        <TimelineLayout>
        {roadmap?.phases.map((phase, pi) => (
          <TimelineItem
            key={phase.phase}
            index={pi}
            marker={String(phase.phase).padStart(2, '0')}
            isLast={pi === (roadmap?.phases.length ?? 0) - 1}
            // The phase we are in today, so the eye lands on what to do now rather than on
            // the top of a plan that may be weeks old.
            active={
              new Date(phase.starts_on) <= new Date() && new Date(phase.ends_on) >= new Date()
            }
          >
          <motion.section
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: pi * 0.06, ease: EASE }}
            className="mb-12"
          >
            <div className="mb-5 flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-foreground/15 pb-2">
              <h2 className="text-base font-semibold tracking-[-0.01em]">{phase.title}</h2>
              <span className="ml-auto font-mono text-[11px] tabular-nums text-muted-foreground">
                {new Date(phase.starts_on).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })} –{' '}
                {new Date(phase.ends_on).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })} · {phase.hours}h
              </span>
            </div>

            {phase.topics.map((topic) => {
              const tDone = topic.subtopics.filter((s) => doneSet.has(s.id)).length;
              return (
                <div key={topic.name} className="mb-7">
                  <div className="mb-1 flex flex-wrap items-baseline gap-x-3">
                    <h3 className="text-sm font-semibold">{topic.name}</h3>
                    <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
                      {topic.weight}% of the paper · {topic.hours}h
                    </span>
                    {topic.subtopics.length > 0 && (
                      <span className="ml-auto font-mono text-[11px] tabular-nums text-muted-foreground">
                        {tDone}/{topic.subtopics.length}
                      </span>
                    )}
                  </div>

                  {/* Weight as a hairline under the heading — the chart IS the rule. */}
                  <div className="mb-2 h-px w-full bg-border">
                    <div
                      className="h-px"
                      style={{ width: `${Math.min(topic.weight * 2.5, 100)}%`, backgroundColor: accent }}
                    />
                  </div>

                  {topic.subtopics.map((s) => (
                    <SubtopicRow
                      key={s.id}
                      s={s}
                      done={doneSet.has(s.id)}
                      accent={accent}
                      onToggle={() =>
                        toggle.mutate({
                          subtopicId: s.id,
                          completed: !doneSet.has(s.id),
                          companySlug: selected.slug,
                        })
                      }
                    />
                  ))}

                  <button
                    onClick={() => router.push(`/quiz?topic=${encodeURIComponent(topic.name)}&autostart=1`)}
                    className="mt-2.5 inline-flex items-center gap-1.5 text-xs font-medium transition-opacity hover:opacity-70"
                    style={{ color: brandInk(selected.accent) }}
                  >
                    <Target className="h-3.5 w-3.5" />
                    Quiz yourself on {topic.name}
                  </button>
                </div>
              );
            })}
          </motion.section>
          </TimelineItem>
        ))}
        </TimelineLayout>

        {/* Rounds */}
        <section className="mb-10">
          <h2 className="mb-4 border-b border-foreground/15 pb-2 text-base font-semibold">
            The rounds you will face
          </h2>
          <ol className="space-y-2">
            {selected.rounds.map((round, i) => (
              <li key={round} className="flex gap-3 text-sm">
                <span className="font-mono text-xs tabular-nums text-muted-foreground">
                  {String(i + 1).padStart(2, '0')}
                </span>
                {round}
              </li>
            ))}
          </ol>
        </section>

        <div className="flex flex-wrap items-center gap-3 border-t border-border pt-6">
          <Button onClick={() => router.push(`/interview?company=${encodeURIComponent(selected.name)}`)}>
            <Target className="h-4 w-4" />
            Start a {selected.name} mock interview
          </Button>
          {isFetching && (
            <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" /> updating
            </span>
          )}
        </div>

        {roadmap?.disclaimer && (
          <p className="mt-6 text-[11px] leading-relaxed text-muted-foreground">{roadmap.disclaimer}</p>
        )}
      </div>
    );
  }

  // ── Company picker ─────────────────────────────────────────────────────────
  return (
    <div className="mx-auto max-w-5xl pb-20">
      <header className="mb-10">
        <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
          Step one
        </p>
        <h1 className={FLOW_TITLE}>
          Who are you targeting?
        </h1>
        <p className="mt-3 max-w-xl text-sm leading-relaxed text-muted-foreground">
          Pick the company you want an offer from. You get what they actually test, weighted by
          how much it counts, and a plan dated to your drive.
        </p>
      </header>

      {TIERS.map(({ key, label, blurb }) => {
        const list = (recruiters ?? []).filter((r) => r.tier === key);
        if (!list.length) return null;
        return (
          <section key={key} className="mb-12">
            <div className="mb-4 flex flex-wrap items-baseline gap-x-3 border-b border-foreground/15 pb-2">
              <h2 className="text-base font-semibold">{label}</h2>
              <p className="text-xs text-muted-foreground">{blurb}</p>
              <span className="ml-auto font-mono text-[11px] tabular-nums text-muted-foreground">
                {list.length}
              </span>
            </div>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {list.map((r) => (
                <CompanyCard key={r.slug} r={r} onPick={() => setSelected(r)} />
              ))}
            </div>
          </section>
        );
      })}

      <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <Clock className="h-3 w-3" />
        Drive windows and eligibility are indicative and change every year — always confirm
        against the company&apos;s official notification.
      </p>
    </div>
  );
}
