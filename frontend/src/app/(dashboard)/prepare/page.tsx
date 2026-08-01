'use client';

import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { AnimatePresence, motion } from 'framer-motion';
import {
  ArrowRight,
  Building2,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ExternalLink,
  Clock,
  GraduationCap,
  Info,
  Layers,
  Loader2,
  Target,
  Users,
} from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { CountUp, ParallaxLayer, Stage3D, TiltCard } from '@/components/motion/Scene3D';
import { useRecruiters, useRoadmap, type Recruiter } from '@/hooks/useData';
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
  if (w >= 22) return 'from-red-500 to-orange-500';
  if (w >= 15) return 'from-amber-500 to-yellow-500';
  if (w >= 10) return 'from-primary to-accent-violet';
  return 'from-slate-500 to-slate-400';
}

export default function PreparePage() {
  const router = useRouter();
  const { data: recruiters, isLoading } = useRecruiters();

  const [selected, setSelected] = useState<Recruiter | null>(null);
  const [weeks, setWeeks] = useState(8);
  const [hours, setHours] = useState(10);
  // One topic open at a time — the plan should stay readable, not become a list of
  // every link we have.
  const [openTopic, setOpenTopic] = useState<string | null>(null);

  const { data: roadmap, isFetching } = useRoadmap(selected?.slug ?? null, weeks, hours);

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
          </Card>
        </motion.div>

        {/* The 3D roadmap. Each phase card sits at its own depth and tilts to the
            pointer, so the plan reads as a path receding into the distance rather
            than a list. */}
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
                        const key = `${phase.phase}-${topic.name}`;
                        const isOpen = openTopic === key;
                        return (
                          <div key={topic.name}>
                            <button
                              type="button"
                              onClick={() => setOpenTopic(isOpen ? null : key)}
                              className="group/topic w-full text-left"
                              aria-expanded={isOpen}
                            >
                              <div className="mb-1.5 flex items-baseline justify-between gap-3 text-xs">
                                <span className="flex items-center gap-1.5 font-semibold">
                                  {topic.name}
                                  {topic.resources.length > 0 && (
                                    <ChevronDown
                                      className={cn(
                                        'h-3 w-3 text-muted-foreground transition-transform',
                                        isOpen && 'rotate-180',
                                      )}
                                    />
                                  )}
                                </span>
                                <span className="shrink-0 text-muted-foreground tabular-nums">
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
                            </button>

                            {/* Resources, revealed on demand. Collapsed by default so the
                                plan stays scannable — twelve topics with four links each
                                is a wall, not a roadmap. */}
                            <AnimatePresence initial={false}>
                              {isOpen && topic.resources.length > 0 && (
                                <motion.div
                                  initial={{ height: 0, opacity: 0 }}
                                  animate={{ height: 'auto', opacity: 1 }}
                                  exit={{ height: 0, opacity: 0 }}
                                  transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
                                  className="overflow-hidden"
                                >
                                  <div className="mt-3 space-y-2 border-l-2 pl-3" style={{ borderColor: `${selected.accent}44` }}>
                                    {topic.resources.map((res) => {
                                      const href = resourceHref(res);
                                      const Inner = (
                                        <>
                                          <div className="flex flex-wrap items-center gap-2">
                                            <span className="text-xs font-semibold">{res.title}</span>
                                            <span className={cn('rounded-full border px-1.5 py-0.5 text-[9px] font-bold uppercase', COST_TONE[res.cost] ?? COST_TONE.paid)}>
                                              {res.cost}
                                            </span>
                                            <span className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground">
                                              {res.kind}
                                            </span>
                                            {href && <ExternalLink className="h-3 w-3 text-muted-foreground" />}
                                          </div>
                                          {res.author && (
                                            <p className="mt-0.5 text-[11px] text-muted-foreground">by {res.author}</p>
                                          )}
                                          {res.note && (
                                            <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">{res.note}</p>
                                          )}
                                        </>
                                      );
                                      return href ? (
                                        <a
                                          key={res.title}
                                          href={href}
                                          target="_blank"
                                          rel="noopener noreferrer"
                                          className="block rounded-lg p-2 transition-colors hover:bg-secondary/60"
                                        >
                                          {Inner}
                                        </a>
                                      ) : (
                                        <div key={res.title} className="rounded-lg p-2">
                                          {Inner}
                                        </div>
                                      );
                                    })}
                                  </div>
                                </motion.div>
                              )}
                            </AnimatePresence>
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
