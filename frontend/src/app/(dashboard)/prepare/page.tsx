'use client';

import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { AnimatePresence, motion } from 'framer-motion';
import {
  AlertTriangle,
  ArrowRight,
  Building2,
  CalendarDays,
  CheckCircle2,

  ChevronLeft,
  ExternalLink,
  Clock,
  GraduationCap,
  Info,
  BookOpen,
  Dumbbell,
  Layers,
  Loader2,
  PlayCircle,
  RefreshCw,
  Target,
  Users,
} from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { CountUp, ParallaxLayer, Stage3D, TiltCard } from '@/components/motion/Scene3D';
import {
  usePrepProgress,
  useRecruiters,
  useRoadmap,
  useToggleProgress,
  type Recruiter,
} from '@/hooks/useData';
import { PhaseProgress, RoadmapRoad, type RoadMilestone } from '@/components/prep/RoadmapRoad';
import { fadeUp, staggerContainer } from '@/lib/motion';
import { cn } from '@/lib/utils';

export const runtime = 'edge';

const TIERS: Array<{ key: string; label: string; blurb: string }> = [
  { key: 'mass_recruiter', label: 'Mass recruiters', blurb: 'Highest intake. Fundamentals and aptitude decide it.' },
  { key: 'consulting', label: 'Consulting & IT', blurb: 'Smaller intake, higher bar, more communication weight.' },
  { key: 'product', label: 'Product companies', blurb: 'Smallest intake. Algorithms dominate.' },
];

const COST_TONE: Record<string, string> = {
  free: 'text-emerald-600 border-emerald-500/30 bg-emerald-500/10',
  freemium: 'text-amber-600 border-amber-500/30 bg-amber-500/10',
  paid: 'text-muted-foreground border-border bg-secondary/50',
};

/**
 * Turn a resource into a link that always works.
 *
 * Exercises ("write five small programs") deliberately have no URL — they are
 * instructions, not destinations. Rendering them as a dead anchor would be worse
 * than rendering them as text, so they stay plain.
 */
function resourceHref(r: { url: string | null; title: string; author: string | null }): string | null {
  if (r.url && /^https?:\/\/\S+\.\S+/i.test(r.url)) return r.url;
  return null;
}

/** Bar colour by how heavily a topic is weighted — the eye should find the big ones. */
function weightTone(w: number): string {
  // Deliberately no red or amber. Those read as "something is wrong", and a
  // heavily-weighted topic is the opposite — it is where the marks are. Weight is
  // shown by intensity within one brand hue instead, so the page looks like a
  // plan rather than a list of warnings.
  if (w >= 22) return 'from-primary to-accent-violet';
  if (w >= 15) return 'from-primary/85 to-accent-violet/85';
  if (w >= 10) return 'from-primary/65 to-accent-violet/65';
  return 'from-primary/40 to-accent-violet/40';
}

export default function PreparePage() {
  const router = useRouter();
  const { data: recruiters, isLoading, error, refetch, isFetching: refetching } = useRecruiters();

  const [selected, setSelected] = useState<Recruiter | null>(null);
  const [weeks, setWeeks] = useState(8);
  const [hours, setHours] = useState(10);

  const { data: roadmap, isFetching } = useRoadmap(selected?.slug ?? null, weeks, hours);
  const { data: progress } = usePrepProgress();
  const toggleProgress = useToggleProgress();

  const doneSet = useMemo(() => new Set(progress?.completed ?? []), [progress]);

  // Every subtopic across the plan, in phase order — this is what the road draws
  // and what the percentage is computed from.
  const milestones: RoadMilestone[] = useMemo(() => {
    if (!roadmap) return [];
    return roadmap.phases.flatMap((ph) =>
      ph.topics.flatMap((tp) =>
        tp.subtopics.map((s) => ({
          id: s.id,
          label: s.name,
          sublabel: tp.name,
          done: doneSet.has(s.id),
          phase: ph.phase,
        })),
      ),
    );
  }, [roadmap, doneSet]);

  const grouped = useMemo(() => {
    const map = new Map<string, Recruiter[]>();
    (recruiters ?? []).forEach((r) => {
      map.set(r.tier, [...(map.get(r.tier) ?? []), r]);
    });
    return map;
  }, [recruiters]);

  if (isLoading) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  // A failed or empty catalogue must SAY so. Falling through to the normal render
  // produced a page with a heading and nothing under it — indistinguishable from
  // "there are no companies", and impossible for anyone to debug or act on.
  if (error || !recruiters?.length) {
    const message = (error as { message?: string } | null)?.message?.trim();
    return (
      <motion.div initial="hidden" animate="visible" variants={staggerContainer(0.06)} className="mx-auto max-w-2xl">
        <motion.div variants={fadeUp}>
          <Card className="mt-12 border-destructive/20 p-8 text-center">
            <AlertTriangle className="mx-auto mb-4 h-10 w-10 text-amber-500" />
            <h2 className="mb-2 text-xl font-bold">Company list unavailable</h2>
            <p className="text-sm text-muted-foreground">
              {message || 'The recruiter catalogue could not be loaded right now.'}
            </p>
            <p className="mt-3 text-xs text-muted-foreground">
              If this persists, the API may be starting up after being idle — give it a
              few seconds and try again.
            </p>
            <div className="mt-6 flex flex-wrap justify-center gap-3">
              <Button variant="secondary" onClick={() => refetch()} loading={refetching}>
                <RefreshCw className="h-4 w-4" /> Try again
              </Button>
              <Button variant="ghost" onClick={() => router.push('/interview')}>
                Start an interview instead
              </Button>
            </div>
          </Card>
        </motion.div>
      </motion.div>
    );
  }

  // ─── Roadmap view ─────────────────────────────────────────────────────────
  if (selected) {
    return (
      <motion.div
        initial="hidden"
        animate="visible"
        variants={staggerContainer(0.06)}
        className="mx-auto max-w-5xl space-y-7 pb-20"
      >
        <motion.button
          variants={fadeUp}
          onClick={() => setSelected(null)}
          className="inline-flex items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          <ChevronLeft className="h-4 w-4" /> All companies
        </motion.button>

        {/* Header — the chosen target, lit in its own brand colour. */}
        <motion.div variants={fadeUp}>
          <Stage3D>
            <TiltCard max={5} lift={14} accent={selected.accent}>
              <Card
                className="relative overflow-hidden p-8"
                style={{
                  borderColor: `${selected.accent}44`,
                  backgroundImage: `radial-gradient(90% 120% at 0% 0%, ${selected.accent}1c 0%, transparent 60%)`,
                }}
              >
                <div className="flex flex-wrap items-start justify-between gap-6">
                  <div>
                    <Badge variant="neutral">Your target</Badge>
                    <h1 className="mt-3 text-3xl font-bold tracking-[-0.02em]">{selected.name}</h1>
                    <p className="mt-1 text-sm text-muted-foreground">{selected.short}</p>

                    <div className="mt-5 grid gap-4 sm:grid-cols-2">
                      <div className="flex items-start gap-2.5">
                        <CalendarDays className="mt-0.5 h-4 w-4 shrink-0" style={{ color: selected.accent }} />
                        <div>
                          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Drive window</p>
                          <p className="text-sm font-medium">{selected.drive_window}</p>
                        </div>
                      </div>
                      <div className="flex items-start gap-2.5">
                        <Users className="mt-0.5 h-4 w-4 shrink-0" style={{ color: selected.accent }} />
                        <div>
                          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Intake</p>
                          <p className="text-sm font-medium">{selected.hires_per_year}</p>
                        </div>
                      </div>
                      <div className="flex items-start gap-2.5 sm:col-span-2">
                        <GraduationCap className="mt-0.5 h-4 w-4 shrink-0" style={{ color: selected.accent }} />
                        <div>
                          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Typical eligibility</p>
                          <p className="text-sm font-medium">{selected.eligibility}</p>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="text-right">
                    <p
                      className="text-6xl font-bold tabular-nums"
                      style={{ color: selected.accent }}
                    >
                      <CountUp to={roadmap?.total_hours ?? 0} />
                    </p>
                    <p className="text-xs text-muted-foreground">hours of prep</p>
                  </div>
                </div>
              </Card>
            </TiltCard>
          </Stage3D>
        </motion.div>

        {/* Controls — the plan recomputes live as these move. */}
        <motion.div variants={fadeUp}>
          <Card className="p-6">
            <div className="grid gap-6 sm:grid-cols-2">
              <div>
                <div className="mb-2 flex items-baseline justify-between">
                  <label htmlFor="weeks" className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Weeks until the drive
                  </label>
                  <span className="text-sm font-bold tabular-nums">{weeks}</span>
                </div>
                <input
                  id="weeks"
                  type="range"
                  min={2}
                  max={24}
                  value={weeks}
                  onChange={(e) => setWeeks(Number(e.target.value))}
                  className="w-full accent-primary"
                />
              </div>
              <div>
                <div className="mb-2 flex items-baseline justify-between">
                  <label htmlFor="hours" className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    Hours you can study per week
                  </label>
                  <span className="text-sm font-bold tabular-nums">{hours}</span>
                </div>
                <input
                  id="hours"
                  type="range"
                  min={3}
                  max={40}
                  value={hours}
                  onChange={(e) => setHours(Number(e.target.value))}
                  className="w-full accent-primary"
                />
              </div>
            </div>

            {/* Live consequence of the sliders. Without this the only thing that
                visibly moved was one number in the header, so it read as though
                the controls did nothing. */}
            {roadmap && (
              <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-border/50 pt-4 text-xs">
                <span className="text-muted-foreground">
                  Total <strong className="text-foreground tabular-nums">{roadmap.total_hours}h</strong>
                </span>
                <span className="text-muted-foreground">
                  Covers{' '}
                  <strong className="text-foreground tabular-nums">
                    {roadmap.phases.reduce((n, ph) => n + ph.topics.length, 0)}
                  </strong>
                  {' of '}
                  <strong className="text-foreground tabular-nums">
                    {roadmap.phases.reduce((n, ph) => n + ph.topics.length, 0) +
                      roadmap.omitted_topics.length}
                  </strong>{' '}
                  topics
                </span>
                <span className="text-muted-foreground">
                  Ready by{' '}
                  <strong className="text-foreground">
                    {new Date(roadmap.target_date).toLocaleDateString(undefined, {
                      day: 'numeric',
                      month: 'short',
                      year: 'numeric',
                    })}
                  </strong>
                </span>
                {isFetching && (
                  <span className="inline-flex items-center gap-1.5 text-primary">
                    <Loader2 className="h-3 w-3 animate-spin" /> updating
                  </span>
                )}
              </div>
            )}
          </Card>
        </motion.div>

        {/* The road. Driven by real ticked-off subtopics — it only moves when the
            candidate actually studies, which is the entire reason to draw it. */}
        {milestones.length > 0 && (
          <motion.div variants={fadeUp}>
            <Card className="p-6">
              <RoadmapRoad
                milestones={milestones}
                accent={selected.accent}
                onSelect={(id) => {
                  // Nothing is collapsed any more, so clicking a milestone just
                  // scrolls to it rather than expanding anything.
                  document
                    .getElementById(`sub-${id}`)
                    ?.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }}
              />
            </Card>
          </motion.div>
        )}

        {/* Feasibility — when the budget cannot cover the syllabus, say so here
            rather than letting the plan imply full coverage. */}
        {roadmap?.feasibility_warning && (
          <motion.div variants={fadeUp}>
            <div className="flex items-start gap-2.5 rounded-xl border border-amber-500/25 bg-amber-500/[0.07] p-4">
              <Info className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
              <div>
                <p className="text-xs font-semibold text-amber-700 dark:text-amber-400">
                  Not enough time to cover everything
                </p>
                <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                  {roadmap.feasibility_warning}
                </p>
                {roadmap.omitted_topics.length > 0 && (
                  <p className="mt-2 text-[11px] text-muted-foreground">
                    Left out: {roadmap.omitted_topics.join(' · ')}
                  </p>
                )}
              </div>
            </div>
          </motion.div>
        )}

        {/* The phase cards. Each sits at its own depth and tilts to the pointer. */}
        <Stage3D depth={1500} className="space-y-5">
          {roadmap?.phases.map((phase, i) => (
            <motion.div key={phase.phase} variants={fadeUp}>
              <TiltCard max={6} lift={22} accent={selected.accent}>
                <Card className="relative overflow-hidden p-6">
                  {/* Depth cue: later phases sit visually further back. */}
                  <div
                    aria-hidden
                    className="pointer-events-none absolute inset-0"
                    style={{ background: `linear-gradient(90deg, ${selected.accent}0e, transparent 45%)` }}
                  />
                  <div className="relative">
                    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                      <div className="flex items-center gap-3">
                        <div
                          className="flex h-10 w-10 items-center justify-center rounded-xl text-sm font-bold text-white"
                          style={{ backgroundColor: selected.accent }}
                        >
                          {phase.phase}
                        </div>
                        <div>
                          <p className="text-sm font-bold">{phase.title}</p>
                          <p className="text-[11px] text-muted-foreground">
                            {new Date(phase.starts_on).toLocaleDateString()} →{' '}
                            {new Date(phase.ends_on).toLocaleDateString()}
                          </p>
                        </div>
                      </div>
                      <span className="rounded-full border border-border bg-secondary/50 px-3 py-1 text-xs font-bold tabular-nums">
                        {phase.hours}h
                      </span>
                    </div>

                    <div className="space-y-3">
                      {phase.topics.map((topic, ti) => {
                        return (
                          <div key={topic.name} className="rounded-xl border border-border/50 p-4">
                            <div>
                              <div className="mb-1.5 flex items-baseline justify-between gap-3 text-xs">
                                <span className="flex items-center gap-1.5 text-sm font-bold">
                                  {topic.name}
                                </span>
                                <span className="flex shrink-0 items-center gap-2 text-muted-foreground tabular-nums">
                                  {topic.subtopics.length > 0 && (
                                    <PhaseProgress
                                      done={topic.subtopics.filter((s) => doneSet.has(s.id)).length}
                                      total={topic.subtopics.length}
                                      accent={selected.accent}
                                    />
                                  )}
                                  {topic.weight}% · {topic.hours}h
                                </span>
                              </div>
                              <div className="h-2 w-full overflow-hidden rounded-full bg-secondary">
                                <motion.div
                                  className={cn('h-full rounded-full bg-gradient-to-r', weightTone(topic.weight))}
                                  initial={{ width: 0 }}
                                  animate={{ width: `${Math.min(topic.weight * 2.2, 100)}%` }}
                                  transition={{ duration: 0.7, delay: 0.05 * ti + 0.1 * i, ease: [0.16, 1, 0.3, 1] }}
                                />
                              </div>
                            </div>

                            {/* EVERYTHING VISIBLE. This was an accordion that opened one
                                topic at a time, so reaching a video meant expand, scroll,
                                click, collapse, expand the next. The links ARE the content
                                — hiding them behind a click to keep the page "scannable"
                                optimised for the wrong thing. */}
                            <div>
                                <div>
                                  <div className="mt-3 space-y-3 border-l-2 pl-3" style={{ borderColor: `${selected.accent}44` }}>
                                    {/* Subtopics — the actual checklist. Ticking one
                                        persists immediately and moves the road. */}
                                    {topic.subtopics.length > 0 && (
                                      <div className="space-y-1.5">
                                        {topic.subtopics.map((s) => {
                                          const done = doneSet.has(s.id);
                                          return (
                                            <div
                                              key={s.id}
                                              id={`sub-${s.id}`}
                                              className="group/sub rounded-lg border border-border/50 bg-surface/40 p-2.5 transition-colors hover:border-primary/40"
                                            >
                                              <div className="flex items-start gap-2.5">
                                                <button
                                                  type="button"
                                                  onClick={() =>
                                                    toggleProgress.mutate({
                                                      subtopicId: s.id,
                                                      completed: !done,
                                                      companySlug: selected.slug,
                                                    })
                                                  }
                                                  aria-pressed={done}
                                                  aria-label={done ? `Mark ${s.name} not done` : `Mark ${s.name} done`}
                                                  className="mt-0.5 shrink-0"
                                                >
                                                  {done ? (
                                                    <CheckCircle2
                                                      className="h-4 w-4"
                                                      style={{ color: selected.accent }}
                                                    />
                                                  ) : (
                                                    <span className="block h-4 w-4 rounded-full border-2 border-border transition-colors group-hover/sub:border-primary" />
                                                  )}
                                                </button>

                                                <div className="min-w-0 flex-1">
                                                  <div className="flex flex-wrap items-baseline gap-x-2">
                                                    <span
                                                      className={cn(
                                                        'text-xs font-semibold',
                                                        done && 'text-muted-foreground line-through',
                                                      )}
                                                    >
                                                      {s.name}
                                                    </span>
                                                    <span className="text-[10px] text-muted-foreground tabular-nums">
                                                      ~{Math.round(s.minutes / 60)}h
                                                    </span>
                                                  </div>

                                                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                                                    {s.video && (
                                                      <a
                                                        href={s.video.url}
                                                        target="_blank"
                                                        rel="noopener noreferrer"
                                                        className="inline-flex items-center gap-1 rounded-md border border-border bg-secondary/60 px-2 py-1 text-[11px] font-semibold text-foreground/75 transition-colors hover:border-primary/40 hover:text-primary"
                                                      >
                                                        <PlayCircle className="h-3 w-3" />
                                                        {s.video.channel ?? 'Video'}
                                                      </a>
                                                    )}
                                                    {s.doc && (
                                                      <a
                                                        href={s.doc.url}
                                                        target="_blank"
                                                        rel="noopener noreferrer"
                                                        className="inline-flex items-center gap-1 rounded-md border border-border bg-secondary/60 px-2 py-1 text-[11px] font-semibold text-foreground/75 transition-colors hover:border-primary/40 hover:text-primary"
                                                      >
                                                        <BookOpen className="h-3 w-3" />
                                                        {s.doc.title}
                                                      </a>
                                                    )}
                                                    {s.practice && (
                                                      <a
                                                        href={s.practice.url}
                                                        target="_blank"
                                                        rel="noopener noreferrer"
                                                        className="inline-flex items-center gap-1 rounded-md border border-border bg-secondary/60 px-2 py-1 text-[11px] font-semibold text-foreground/75 transition-colors hover:border-primary/40 hover:text-primary"
                                                      >
                                                        <Dumbbell className="h-3 w-3" />
                                                        {s.practice.title}
                                                      </a>
                                                    )}
                                                  </div>
                                                </div>
                                              </div>
                                            </div>
                                          );
                                        })}
                                      </div>
                                    )}

                                    {/* Test yourself on exactly this topic. Goes straight
                                        into the quiz with the topic pre-set, so the
                                        candidate never has to configure anything. */}
                                    <button
                                      type="button"
                                      onClick={() =>
                                        router.push(
                                          `/quiz?topic=${encodeURIComponent(topic.name)}&autostart=1`,
                                        )
                                      }
                                      className="inline-flex w-full items-center justify-center gap-2 rounded-lg border px-3 py-2 text-xs font-bold transition-colors"
                                      style={{
                                        borderColor: `${selected.accent}55`,
                                        backgroundColor: `${selected.accent}14`,
                                        color: selected.accent,
                                      }}
                                    >
                                      <Target className="h-3.5 w-3.5" />
                                      Take a quiz on {topic.name} — see what you actually know
                                    </button>

                                  </div>
                                </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </Card>
              </TiltCard>
            </motion.div>
          ))}
        </Stage3D>

        {/* Rounds */}
        <motion.div variants={fadeUp}>
          <Card className="p-6">
            <h2 className="mb-4 flex items-center gap-2 text-base font-bold">
              <Layers className="h-4 w-4" style={{ color: selected.accent }} /> The rounds you will face
            </h2>
            <div className="space-y-3">
              {selected.rounds.map((round, i) => (
                <div key={round} className="flex items-center gap-3">
                  <div
                    className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border text-[11px] font-bold"
                    style={{ borderColor: `${selected.accent}66`, color: selected.accent }}
                  >
                    {i + 1}
                  </div>
                  <span className="text-sm">{round}</span>
                </div>
              ))}
            </div>
          </Card>
        </motion.div>

        {/* Honesty note — eligibility genuinely changes every year. */}
        {roadmap?.disclaimer && (
          <motion.div variants={fadeUp}>
            <div className="flex items-start gap-2.5 rounded-xl border border-amber-500/25 bg-amber-500/[0.07] p-4">
              <Info className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
              <p className="text-xs leading-relaxed text-muted-foreground">{roadmap.disclaimer}</p>
            </div>
          </motion.div>
        )}

        <motion.div variants={fadeUp} className="flex flex-wrap gap-3">
          <Button onClick={() => router.push(`/interview?company=${encodeURIComponent(selected.name)}`)}>
            <Target className="h-4 w-4" />
            Start a {selected.name} mock interview
            <ArrowRight className="h-4 w-4" />
          </Button>
          {isFetching && (
            <span className="inline-flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" /> recalculating
            </span>
          )}
        </motion.div>
      </motion.div>
    );
  }

  // ─── Company picker ───────────────────────────────────────────────────────
  return (
    <motion.div
      initial="hidden"
      animate="visible"
      variants={staggerContainer(0.05)}
      className="mx-auto max-w-6xl space-y-10 pb-20"
    >
      <motion.div variants={fadeUp} className="relative">
        <ParallaxLayer depth={-0.25} className="pointer-events-none absolute inset-0 -z-10">
          <div className="absolute left-1/4 top-0 h-64 w-64 rounded-full bg-primary/10 blur-3xl" />
          <div className="absolute right-1/4 top-10 h-56 w-56 rounded-full bg-accent-violet/10 blur-3xl" />
        </ParallaxLayer>
        <h1 className="text-3xl font-bold tracking-[-0.02em]">Who are you targeting?</h1>
        <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
          Pick the company you want an offer from. You&apos;ll get what they actually test, weighted
          by how much it counts — and a study plan dated to your drive.
        </p>
      </motion.div>

      <AnimatePresence>
        {TIERS.map(({ key, label, blurb }) => {
          const list = grouped.get(key) ?? [];
          if (!list.length) return null;
          return (
            <motion.section key={key} variants={fadeUp} className="space-y-4">
              <div>
                <h2 className="text-lg font-bold">{label}</h2>
                <p className="text-xs text-muted-foreground">{blurb}</p>
              </div>

              <Stage3D className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
                {list.map((r) => (
                  <TiltCard key={r.slug} accent={r.accent} onClick={() => setSelected(r)}>
                    <Card
                      className="group h-full cursor-pointer overflow-hidden p-6 transition-colors"
                      style={{ borderColor: `${r.accent}2a` }}
                    >
                      <div
                        aria-hidden
                        className="pointer-events-none absolute inset-x-0 top-0 h-24 opacity-70"
                        style={{ background: `radial-gradient(70% 100% at 50% 0%, ${r.accent}22, transparent)` }}
                      />
                      <div className="relative">
                        <div className="mb-4 flex items-center justify-between">
                          <div
                            className="flex h-11 w-11 items-center justify-center rounded-xl text-base font-bold text-white"
                            style={{ backgroundColor: r.accent }}
                          >
                            {r.name.slice(0, 2).toUpperCase()}
                          </div>
                          <Building2 className="h-4 w-4 text-muted-foreground/40" />
                        </div>

                        <h3 className="text-lg font-bold">{r.name}</h3>
                        <p className="mt-0.5 text-xs text-muted-foreground">{r.hires_per_year}</p>

                        <div className="mt-4 flex items-center gap-1.5 text-[11px] text-muted-foreground">
                          <Clock className="h-3 w-3" />
                          {r.drive_window}
                        </div>

                        <div className="mt-4 flex flex-wrap gap-1.5">
                          {r.programs.slice(0, 3).map((p) => (
                            <span
                              key={p.name}
                              className="rounded-full border border-border bg-secondary/50 px-2 py-0.5 text-[10px] font-semibold text-muted-foreground"
                            >
                              {p.name}
                            </span>
                          ))}
                        </div>

                        <div className="mt-5 flex items-center gap-1.5 text-xs font-semibold" style={{ color: r.accent }}>
                          <CheckCircle2 className="h-3.5 w-3.5" />
                          See the plan
                          <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-1" />
                        </div>
                      </div>
                    </Card>
                  </TiltCard>
                ))}
              </Stage3D>
            </motion.section>
          );
        })}
      </AnimatePresence>
    </motion.div>
  );
}
