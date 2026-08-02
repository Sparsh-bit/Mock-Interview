'use client';

import { motion } from 'framer-motion';
import { Check, Play, Terminal } from 'lucide-react';
import { cn } from '@/lib/utils';

/**
 * The landing page's imagery: real pieces of the product, rebuilt as live
 * components.
 *
 * The page was pure typography and read as empty. The fix is not decoration —
 * gradient blobs and floating cards are what we are explicitly not doing — it is
 * showing the thing itself. A screenshot of the report is evidence; an icon next
 * to the word "report" is a claim.
 *
 * These are LIVE components rather than images: they stay crisp at any zoom, they
 * theme with the rest of the site, they weigh nothing, and they cannot go stale
 * the way an exported PNG of a UI does the moment that UI changes.
 *
 * Every one obeys the radius ladder — an outer card at rounded-xl (20px) with 16px
 * padding holds rounded-md (10px) children, so the curves stay concentric.
 */

const EASE = [0.16, 1, 0.3, 1] as const;
const inView = { once: true, margin: '-15%' as const };

/** Shared frame: the surface these artefacts sit on. */
function Frame({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={inView}
      transition={{ duration: 0.7, ease: EASE }}
      className={cn(
        'overflow-hidden rounded-xl border border-border bg-surface-elevated p-4 shadow-elev-2',
        className,
      )}
    >
      {children}
    </motion.div>
  );
}

/** A window title bar, so an artefact reads as an application, not a card. */
function Chrome({ title }: { title: string }) {
  return (
    <div className="mb-4 flex items-center gap-2 border-b border-border pb-3">
      <span className="flex gap-1.5">
        {['bg-foreground/15', 'bg-foreground/15', 'bg-foreground/15'].map((c, i) => (
          <span key={i} className={cn('h-2 w-2 rounded-full', c)} />
        ))}
      </span>
      <span className="ml-1 font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
        {title}
      </span>
    </div>
  );
}

/* ── The live interview ───────────────────────────────────────────────────── */

export function InterviewArtefact() {
  return (
    <Frame>
      <Chrome title="Cognizant · Java FSE — Q4 of 12" />

      <div className="space-y-4">
        <div>
          <p className="mb-1.5 font-mono text-[10px] uppercase tracking-[0.16em] text-primary">
            Interviewer
          </p>
          <p className="text-sm leading-relaxed">
            You&apos;ve used HashMap in your project. What happens when two keys have the same hash?
          </p>
        </div>

        <div>
          <p className="mb-1.5 font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
            You
          </p>
          <p className="text-sm leading-relaxed text-muted-foreground">
            They go in the same bucket as a linked list…
          </p>
        </div>

        {/* The cross-question. Arrives last and from the side — the visual grammar
            of being interrupted, which is the point of the feature. */}
        <motion.div
          initial={{ opacity: 0, x: 24 }}
          whileInView={{ opacity: 1, x: 0 }}
          viewport={inView}
          transition={{ duration: 0.55, delay: 0.5, ease: EASE }}
          className="rounded-md border-l-2 border-foreground/40 bg-secondary/60 py-2.5 pl-3 pr-3"
        >
          <p className="mb-1 font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
            Follow-up
          </p>
          <p className="text-sm leading-relaxed">
            And when that list gets long — what does Java actually do about it?
          </p>
        </motion.div>

        {/* Live mic level. A sine over index, so it reads as sound without a
            timer or any per-frame JS. */}
        <div className="flex items-center gap-1.5 border-t border-border pt-3">
          {[0, 1, 2, 3, 4, 5, 6].map((i) => (
            <motion.span
              key={i}
              className="w-[3px] rounded-full bg-foreground/40"
              initial={{ height: 4 }}
              whileInView={{ height: [4, 6 + Math.abs(Math.sin(i * 1.1)) * 14, 4] }}
              viewport={{ once: false }}
              transition={{ duration: 1.1, repeat: Infinity, delay: i * 0.08, ease: 'easeInOut' }}
            />
          ))}
          <span className="ml-1.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
            Listening
          </span>
        </div>
      </div>
    </Frame>
  );
}

/* ── The report ───────────────────────────────────────────────────────────── */

export function ReportArtefact() {
  const R = 34;
  const CIRC = 2 * Math.PI * R;
  const SCORE = 74;

  const bars = [
    ['Technical accuracy', 78],
    ['Answer completeness', 61],
    ['Communication clarity', 83],
    ['Confidence & composure', 57],
  ] as const;

  return (
    <Frame>
      <Chrome title="Technical evaluation report" />

      <div className="flex items-center gap-5">
        <div className="relative h-24 w-24 shrink-0">
          <svg viewBox="0 0 80 80" className="h-24 w-24 -rotate-90">
            <circle cx="40" cy="40" r={R} fill="none" strokeWidth="5" className="stroke-border" />
            <motion.circle
              cx="40"
              cy="40"
              r={R}
              fill="none"
              strokeWidth="5"
              strokeLinecap="round"
              className="stroke-foreground"
              strokeDasharray={CIRC}
              initial={{ strokeDashoffset: CIRC }}
              whileInView={{ strokeDashoffset: CIRC - (SCORE / 100) * CIRC }}
              viewport={inView}
              transition={{ duration: 1.1, ease: EASE }}
            />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-2xl font-medium tabular-nums tracking-[-0.03em]">{SCORE}</span>
            <span className="font-mono text-[9px] text-muted-foreground">/ 100</span>
          </div>
        </div>

        <div className="min-w-0 flex-1 space-y-2.5">
          {bars.map(([label, v], i) => (
            <div key={label}>
              <div className="mb-1 flex items-baseline justify-between gap-3">
                <span className="truncate text-[11px]">{label}</span>
                <span className="font-mono text-[11px] tabular-nums text-muted-foreground">{v}</span>
              </div>
              <div className="h-px w-full bg-border">
                <motion.div
                  className="h-px bg-foreground/70"
                  initial={{ scaleX: 0 }}
                  whileInView={{ scaleX: 1 }}
                  viewport={inView}
                  transition={{ duration: 0.8, delay: 0.15 + i * 0.08, ease: EASE }}
                  style={{ width: `${v}%`, transformOrigin: 'left center' }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2 border-t border-border pt-3">
        {['Close to ready', 'Fix JPA first · 20 hrs', 'Shareable · PDF'].map((c) => (
          <span
            key={c}
            className="rounded-sm border border-border px-2 py-0.5 font-mono text-[10px] text-muted-foreground"
          >
            {c}
          </span>
        ))}
      </div>
    </Frame>
  );
}

/* ── The code review, with the AI-authorship flag ─────────────────────────── */

export function CodeArtefact() {
  const CODE = [
    'public int[] twoSum(int[] nums, int target) {',
    '    Map<Integer,Integer> seen = new HashMap<>();',
    '    for (int i = 0; i < nums.length; i++) {',
    '        int need = target - nums[i];',
    '        if (seen.containsKey(need))',
    '            return new int[]{seen.get(need), i};',
    '        seen.put(nums[i], i);',
    '    }',
    '}',
  ];

  return (
    <Frame>
      <Chrome title="Solution.java" />

      <pre className="overflow-x-auto font-mono text-[10.5px] leading-[1.75] text-muted-foreground">
        {CODE.map((line, i) => (
          <motion.div
            key={i}
            initial={{ opacity: 0 }}
            whileInView={{ opacity: 1 }}
            viewport={inView}
            transition={{ duration: 0.25, delay: i * 0.045 }}
            className="flex gap-3"
          >
            <span className="w-4 shrink-0 text-right text-foreground/20 tabular-nums">{i + 1}</span>
            <span className="whitespace-pre">{line}</span>
          </motion.div>
        ))}
      </pre>

      <div className="mt-4 space-y-2 border-t border-border pt-3">
        {[
          ['Correctness', 'Correct'],
          ['Your complexity', 'O(n)'],
          ['Optimal', 'O(n)'],
        ].map(([k, v]) => (
          <div key={k} className="flex justify-between text-[11px]">
            <span className="text-muted-foreground">{k}</span>
            <span className="font-mono tabular-nums">{v}</span>
          </div>
        ))}
      </div>

      {/* The surprise beat: arrives last, and is the only marked element here. */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={inView}
        transition={{ duration: 0.5, delay: 0.75, ease: EASE }}
        className="mt-3 rounded-md border border-dashed border-foreground/25 px-3 py-2"
      >
        <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
          Flagged
        </p>
        <p className="mt-1 text-[11px] leading-relaxed">
          Optimal on the first attempt with no iteration — this may be AI-written.
        </p>
      </motion.div>
    </Frame>
  );
}

/* ── The study plan ───────────────────────────────────────────────────────── */

export function PlanArtefact() {
  const rows = [
    ['Arrays & Strings', '4h', true],
    ['Linked Lists', '3h', true],
    ['Trees & BST', '5h', false],
    ['Dynamic Programming', '5h', false],
  ] as const;

  return (
    <Frame>
      <Chrome title="Amazon · study plan" />

      <div className="mb-3 flex items-baseline justify-between">
        <span className="text-xs font-medium">Data Structures & Algorithms</span>
        <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
          45% of the paper
        </span>
      </div>
      <div className="mb-4 h-px w-full bg-border">
        <motion.div
          className="h-px bg-foreground"
          initial={{ scaleX: 0 }}
          whileInView={{ scaleX: 1 }}
          viewport={inView}
          transition={{ duration: 0.9, ease: EASE }}
          style={{ width: '90%', transformOrigin: 'left center' }}
        />
      </div>

      {rows.map(([name, hrs, done], i) => (
        <motion.div
          key={name}
          initial={{ opacity: 0, x: -8 }}
          whileInView={{ opacity: 1, x: 0 }}
          viewport={inView}
          transition={{ duration: 0.4, delay: 0.1 + i * 0.07, ease: EASE }}
          className="flex items-center gap-2.5 border-b border-border/60 py-2 last:border-0"
        >
          <span
            className={cn(
              'flex h-4 w-4 shrink-0 items-center justify-center rounded-sm border',
              done ? 'border-foreground bg-foreground' : 'border-border',
            )}
          >
            {done && <Check className="h-2.5 w-2.5 text-background" strokeWidth={3.5} />}
          </span>
          <span className={cn('flex-1 text-[11px]', done && 'text-muted-foreground line-through')}>
            {name}
          </span>
          <span className="font-mono text-[10px] tabular-nums text-muted-foreground">{hrs}</span>
          <span className="flex items-center gap-1 text-muted-foreground">
            <Play className="h-3 w-3" />
            <Terminal className="h-3 w-3" />
          </span>
        </motion.div>
      ))}
    </Frame>
  );
}
