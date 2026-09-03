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
import { formatDayMonth } from '@/lib/format-date';
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
  'mt-2 font-display text-[clamp(1.9rem,3.4vw,2.5rem)] font-[480] leading-[1.1] tracking-[-0.022em]';

// ─── Company picker ───────────────────────────────────────────────────────────

/**
 * WHEN THE DRIVE ACTUALLY RUNS, DRAWN — components/prepare month strip
 *
 * `drive_window` is the single most useful fact on this card and it was the one being thrown
 * away: "Aug – Dec (NQT runs multiple cycles a year)" in a right-aligned `truncate` cell
 * rendered as "Aug – Dec (NQT runs multiple cycl…", i.e. the parenthetical survived and the
 * months — the part a candidate is actually scanning for — were what got cut.
 *
 * Twelve marks, the drive months lit, the current month ringed. It answers "is this one open
 * now, and if not how long have I got" without being read at all, which is what a candidate is
 * doing when they scan nine of these.
 *
 * Returns null when the string does not parse. There is no clever fallback on purpose: a strip
 * that guesses is worse than no strip, because the whole value of the graphic is that it is
 * trustworthy at a glance. The full text still renders underneath either way.
 */
/** Twelve, for the strip. The letters went with the tiles — see MonthStrip. */
const MONTHS = new Array(12).fill(0);
const MONTH_INDEX: Record<string, number> = {
  jan: 0, feb: 1, mar: 2, apr: 3, may: 4, jun: 5,
  jul: 6, aug: 7, sep: 8, oct: 9, nov: 10, dec: 11,
};

/** Which of the twelve months this drive covers. `null` when it cannot be read. */
function driveMonths(window: string): boolean[] | null {
  if (/year[-\s]?round/i.test(window)) return new Array(12).fill(true);

  const found = [...window.matchAll(/\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)/gi)].map(
    (m) => MONTH_INDEX[m[1].toLowerCase()],
  );
  if (found.length < 2) return null;

  const [from, to] = found;
  const on = new Array(12).fill(false);
  /* Wrapping windows are the common case, not the edge case — "Sep – Feb" and "Sep – Jan" are
     two of the four largest recruiters. Walking forward with a modulo handles both directions
     without a branch. */
  for (let i = from; ; i = (i + 1) % 12) {
    on[i] = true;
    if (i === to) break;
  }
  return on;
}

function MonthStrip({ window: driveWindow, accent }: { window: string; accent: string }) {
  const on = driveMonths(driveWindow);
  if (!on) return null;
  const now = new Date().getMonth();

  /*
   * A SEGMENTED RULE, NOT TWELVE TILES — and the first attempt was the tiles.
   *
   * Eighteen-pixel blocks with month letters in them put a hundred and forty-four coloured
   * squares on one screen: it moved the rainbow off the avatars, which this redesign had just
   * fixed, and onto the strips, where it was worse. The letters were 8px and unreadable
   * anyway, and redundant — the line directly underneath already says "Drive Aug – Dec".
   *
   * So the strip carries SHAPE only. Four pixels tall, the drive months filled at 70% and the
   * rest in the neutral fill, which makes it the same mark as every other rule in this product
   * — the dash before an eyebrow, the hairline under a section, the ladder bar. Colour on this
   * page is now spent on exactly one thing per card that carries information: the weight bar.
   */
  return (
    <div aria-hidden className="flex items-center gap-[2px] pb-[5px]">
      {MONTHS.map((_, i) => (
        <span
          key={i}
          className="relative h-[4px] flex-1 rounded-full"
          style={{
            backgroundColor: on[i] ? accent : 'hsl(var(--muted))',
            opacity: on[i] ? 0.7 : 1,
          }}
        >
          {/* Where you are in the year. The one thing the text line cannot tell you, and the
              reason the strip is worth drawing at all: "Sep – Jan" means something different
              in August than it does in December. */}
          {i === now && (
            <span className="absolute -bottom-[5px] left-1/2 h-[3px] w-[3px] -translate-x-1/2 rounded-full bg-foreground/45" />
          )}
        </span>
      ))}
    </div>
  );
}

function CompanyCard({ r, onPick }: { r: Recruiter; onPick: () => void }) {
  /*
   * The company's hue at the palette's saturation and lightness — never the raw brand hex.
   * See lib/brand-accent.ts for why.
   *
   * WHERE THE COLOUR IS SPENT CHANGED, and that is most of this redesign. It used to be a
   * 40px square filled at full `brandFill` with white initials, plus a hairline of the same —
   * so nine cards in a grid put nine saturated blocks on warm paper and the page read as a
   * colour chart rather than as a list of companies. brand-accent.ts's own docstring names
   * that exact failure ("twelve full-chroma brand colours on one screen is a rainbow") and the
   * fill was still loud enough to cause it.
   *
   * Now the identity is a SOFT tint with ink initials — the same `-soft`/`-ink` pairing the
   * rest of the product uses — and full-strength colour is reserved for the one mark that
   * carries information: the weight bar, whose length is the fact. Colour stopped being
   * decoration and went back to meaning something.
   */
  const accent = brandFill(r.accent);
  const ink = brandInk(r.accent);

  /* The heaviest thing this recruiter tests. It is the page's entire argument — "Amazon gives
     algorithms 45%, TCS gives aptitude 25%" — so it belongs on the card that makes you choose,
     not two clicks later inside the plan. */
  const heaviest = [...(r.topics ?? [])].sort((a, b) => b.weight - a.weight)[0];

  return (
    <button
      type="button"
      onClick={onPick}
      className="group relative flex flex-col overflow-hidden rounded-2xl border border-border bg-surface-elevated p-5 text-left transition-[color,background-color,border-color,box-shadow,transform] duration-200 hover:-translate-y-0.5 hover:border-foreground/20 hover:shadow-elev-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
    >
      {/* One hairline of the company's colour, at 40% so nine of them read as edges rather
          than as stripes. It comes to full strength on hover — the card you are pointing at is
          the one allowed to be loud. */}
      <span
        aria-hidden
        className="absolute inset-x-0 top-0 h-[2px] opacity-40 transition-opacity duration-200 group-hover:opacity-100"
        style={{ backgroundColor: accent }}
      />

      <div className="flex items-start gap-3">
        <span
          className="grid h-11 w-11 shrink-0 place-items-center rounded-xl font-mono text-[13px] font-bold tracking-tight"
          /* A 20%-alpha hairline of the same hue, over a 12%-alpha fill. A flat tint at this
             lightness has no edge against warm paper and the initials float; the inset shadow
             gives the tile a boundary without adding a second colour or any more saturation.
             An inset box-shadow rather than Tailwind's `ring`, because the ring colour would
             have to be injected as a CSS variable through `style` and cast — and a cast on a
             style object to set one border is a lot of machinery for one border. */
          style={{
            backgroundColor: `${accent}1f`,
            color: ink,
            boxShadow: `inset 0 0 0 1px ${accent}33`,
          }}
        >
          {r.name.slice(0, 2).toUpperCase()}
        </span>

        <span className="min-w-0 flex-1">
          {/* THE DISPLAY FACE, and this is the only place in the product outside a page title
              that gets it. The rule in tailwind.config.ts is "the largest piece of type on a
              screen is a serif at a normal weight, everything below it is Inter" — and on this
              screen the company name IS the largest piece of type that matters, because the
              whole page is twelve names you are choosing between. Set in Inter semibold it read
              as a table cell; set in Fraunces it reads as a masthead, which is what a company
              name on a card you are about to commit to should read as. */}
          <span className="block truncate font-display text-[1.0625rem] font-[540] leading-tight tracking-[-0.015em]">
            {r.name}
          </span>
          <span className="mt-0.5 block font-mono text-[11px] tabular-nums text-muted-foreground">
            {r.hires_per_year}
          </span>
        </span>

        {/* A real affordance rather than a 4px grey glyph: the disc fills with the company's
            own colour on hover, so the hit target and the identity are the same object. */}
        <span
          className="relative grid h-7 w-7 shrink-0 place-items-center overflow-hidden rounded-full border border-border text-muted-foreground transition-colors duration-200 group-hover:border-transparent group-hover:text-white"
        >
          <span
            aria-hidden
            className="absolute h-7 w-7 rounded-full opacity-0 transition-opacity duration-200 group-hover:opacity-100"
            style={{ backgroundColor: accent }}
          />
          <ArrowRight className="relative h-3.5 w-3.5 transition-transform duration-200 group-hover:translate-x-px" strokeWidth={2.2} />
        </span>
      </div>

      {/*
        * THE FIGURE IS THE SUBJECT OF THE CARD, so it is set like one.
        *
        * It used to be a 12px number in the company's ink, right-aligned opposite the topic
        * name — the same size and weight as the caption under it, in a colour that made it
        * look like a label rather than a measurement. But this number is the entire reason
        * the page exists: "Amazon gives algorithms 45%, TCS gives aptitude 25%" is the
        * comparison a candidate is here to make, and it was the smallest thing on the card.
        *
        * Now it is 26px, mono, tabular, and in INK rather than in the brand hue. Ink because
        * twelve figures in twelve different colours cannot be compared — the eye reads the
        * colours before the digits — and because the card already spends its colour twice, on
        * the monogram and on the bar. The bar underneath is the same fact drawn; the digits
        * are the same fact stated. Neither needs to be coloured to be believed.
        */}
      {heaviest && (
        <div className="mt-5">
          <div className="flex items-baseline gap-2.5">
            <span className="mk-num font-mono text-[1.625rem] font-semibold leading-none tabular-nums tracking-[-0.035em] text-foreground">
              {heaviest.weight}%
            </span>
            <span className="min-w-0 flex-1 truncate text-[12px] leading-snug text-muted-foreground">
              {heaviest.name}
            </span>
          </div>
          {/* Scaled against 50%, not 100% — no single topic on any recruiter's paper exceeds
              45%, so a /100 bar would render every company as a stub and the comparison this
              card exists to make would be invisible. */}
          <div className="mt-3 h-[3px] overflow-hidden rounded-full bg-muted">
            <span
              className="block h-full rounded-full"
              style={{ width: `${Math.min((heaviest.weight / 50) * 100, 100)}%`, backgroundColor: accent }}
            />
          </div>
        </div>
      )}

      {/* The programme NAMES, not a count. "3" tells a candidate nothing; "NQT · Ninja ·
          Digital" is the thing they have actually heard of and are looking for. */}
      <p className="mt-3.5 truncate text-[11px] text-muted-foreground">
        {r.programs.map((p) => p.name).join(' · ')}
      </p>

      {/* Pushed to the bottom so every card in a row ends on the same line whatever the
          length of the programme list above it.

          RULED OFF FROM WHAT IS ABOVE IT, because the card carries two different kinds of
          fact and they were running together. Everything above is about the company — who
          they are, what they weight, which programmes they run. Everything below is about the
          calendar — when the drive opens and where in the year you are standing. A hairline is
          the whole separation; a second box would be a card inside a card. */}
      <div className="mt-auto border-t border-border/70 pt-3.5">
        <MonthStrip window={r.drive_window} accent={accent} />
        <p className="mt-2 truncate text-[11px] text-muted-foreground">
          <span className="text-foreground/70">Drive</span> {r.drive_window}
        </p>
      </div>
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
              // NAMED, BECAUSE ITS LABEL IS HIDDEN ON THE SCREENS THAT NEED IT MOST.
              //
              // The chevron-only back button is the right call on a phone — the convention is
              // universal and the word costs room in a sticky bar that is already tight. But
              // below `sm` the span is `hidden`, and `hidden` removes an element from the
              // accessibility tree as well as from the layout. So on exactly the narrow screens
              // where the text disappears, a screen reader was left announcing an unlabelled
              // button, and the only way back to the company list was unnameable.
              //
              // `aria-label` rather than un-hiding the text: the visual decision was correct,
              // and an accessible name does not have to be the visible one.
              aria-label="Back to companies"
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
          {/* The same 14px coloured rule PageHeader draws before every other eyebrow in the
              product, in this page's own tone (amber — preparation and effort, per
              ROUTE_TONE). This flow sets its own title treatment for the reason given on
              FLOW_TITLE, but there is no reason for it to opt out of the wayfinding. */}
          <p className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.18em] text-accent-amber-ink">
            <span aria-hidden className="h-px w-3.5 shrink-0 bg-accent-amber" />
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
              { k: 'Ready by', v: roadmap ? formatDayMonth(roadmap.target_date) : '—' },
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
                {formatDayMonth(phase.starts_on)} –{' '}
                {formatDayMonth(phase.ends_on)} · {phase.hours}h
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
        <p className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.18em] text-accent-amber-ink">
          <span aria-hidden className="h-px w-3.5 shrink-0 bg-accent-amber" />
          Step one
        </p>
        <h1 className={FLOW_TITLE}>
          Who are you targeting?
        </h1>
        <p className="mt-3 max-w-xl text-sm leading-relaxed text-muted-foreground">
          Pick the company you want an offer from. You get what they actually test, weighted by
          how much it counts, and a plan dated to your drive.
        </p>

        {/* WHAT THE CARDS ARE SHOWING YOU, said once. The month strip is the only unlabelled
            graphic on this page, and a twelve-mark row means nothing until somebody tells you
            it is a calendar — after which it never needs explaining again. Counted from the
            same array the grid renders, so it cannot disagree with what is below it. */}
        <dl className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-2 border-t border-border pt-4 text-[11px] text-muted-foreground">
          <div className="flex items-baseline gap-1.5">
            <dt className="font-mono text-[13px] font-semibold tabular-nums text-foreground">
              {recruiters?.length ?? 0}
            </dt>
            <dd>campus recruiters</dd>
          </div>
          <div className="flex items-baseline gap-1.5">
            <dt className="font-mono text-[13px] font-semibold tabular-nums text-foreground">
              {(recruiters ?? []).reduce((n, r) => n + r.programs.length, 0)}
            </dt>
            <dd>programmes</dd>
          </div>
          {/* The figure on each card is now the loudest thing in the grid, so it gets the
              same one-line explanation the month strip gets. Said here rather than repeated as
              an eyebrow on twelve cards, where it would be the most-printed sentence on the
              page and the least-read. */}
          <div className="flex items-baseline gap-1.5">
            <dt className="font-mono text-[13px] font-semibold tabular-nums text-foreground">%</dt>
            <dd>is the heaviest topic&rsquo;s share of the paper</dd>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <span aria-hidden className="flex items-center gap-[2px]">
              {[0, 1, 2, 3, 4, 5].map((i) => (
                <span
                  key={i}
                  className={cn(
                    'h-[4px] w-[7px] rounded-full',
                    i > 1 && i < 5 ? 'bg-foreground/45' : 'bg-muted',
                  )}
                />
              ))}
            </span>
            <span>the filled months are when the drive runs</span>
          </div>
        </dl>
      </header>

      {TIERS.map(({ key, label, blurb }) => {
        const list = (recruiters ?? []).filter((r) => r.tier === key);
        if (!list.length) return null;
        return (
          <section key={key} className="mb-12">
            {/* The count sits AGAINST the label as a chip, not at the far right edge of a
                1024px row where it read as a stray digit with nothing to attach to. */}
            <div className="mb-5 border-b border-border pb-2.5">
              <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
                <h2 className="font-display text-[1.0625rem] font-[520] tracking-[-0.015em]">
                  {label}
                </h2>
                {/* A filled grey pill is the shape this product uses for a STATUS — a
                    balance, a count of things left to do. This is neither; it is a numeral
                    belonging to the heading beside it, so it is set as one: mono, in the
                    amber ink, no container. The same treatment the price list gives its
                    section numerals, for the same reason. */}
                <span className="font-mono text-[11px] font-semibold tabular-nums text-accent-amber-ink">
                  {list.length}
                </span>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">{blurb}</p>
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
