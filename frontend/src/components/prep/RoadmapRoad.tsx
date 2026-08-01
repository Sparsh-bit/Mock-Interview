'use client';

import React, { useMemo } from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import { CheckCircle2, Circle, Lock, MapPin } from 'lucide-react';
import { cn } from '@/lib/utils';

/**
 * The roadmap as a road receding into the distance.
 *
 * A real perspective projection: the road surface is a single element rotated on
 * X inside a `perspective` container, so it genuinely recedes rather than being a
 * trapezoid drawn to look like it does. Milestones sit ON that surface at
 * decreasing scale, which is what makes the far end read as far away.
 *
 * WHY NOT WEBGL. This needs a receding plane and some markers — no meshes, no
 * lighting, no camera to fly. CSS 3D gives exactly that, composited on the GPU,
 * with the labels staying real DOM text that a screen reader can read and a phone
 * can render crisply. A 3D engine would cost ~600KB and turn the milestone labels
 * into pixels.
 *
 * The road is driven by ACTUAL progress. A progress visual that always shows the
 * same thing is decoration; this one only moves when the candidate ticks
 * something off, which is the entire point of drawing it.
 */

export type RoadMilestone = {
  id: string;
  label: string;
  sublabel?: string;
  done: boolean;
  /** Phase this milestone belongs to, for grouping colour. */
  phase: number;
};

export function RoadmapRoad({
  milestones,
  accent,
  onSelect,
}: {
  milestones: RoadMilestone[];
  accent: string;
  onSelect?: (id: string) => void;
}) {
  const reduced = useReducedMotion();

  const { doneCount, pct, current } = useMemo(() => {
    const d = milestones.filter((m) => m.done).length;
    return {
      doneCount: d,
      pct: milestones.length ? Math.round((d / milestones.length) * 100) : 0,
      // The first unfinished milestone — "you are here".
      current: milestones.findIndex((m) => !m.done),
    };
  }, [milestones]);

  if (!milestones.length) return null;

  return (
    <div className="relative">
      {/* Progress readout. Above the road, because the number is the fact and the
          road is the illustration of it. */}
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            Your progress
          </p>
          <p className="text-2xl font-bold tabular-nums">
            {doneCount}
            <span className="text-base font-medium text-muted-foreground"> / {milestones.length} done</span>
          </p>
        </div>
        <span
          className="rounded-full px-3 py-1 text-sm font-bold tabular-nums text-white"
          style={{ backgroundColor: accent }}
        >
          {pct}%
        </span>
      </div>

      {/* ── The road ──────────────────────────────────────────────────────── */}
      <div
        className="relative h-[340px] overflow-hidden rounded-2xl border border-border"
        style={{ perspective: '620px', perspectiveOrigin: '50% 18%' }}
      >
        {/* Sky / horizon glow */}
        <div
          aria-hidden
          className="absolute inset-0"
          style={{
            background: `linear-gradient(to bottom, ${accent}1f 0%, transparent 42%), var(--road-bg, hsl(var(--surface)))`,
          }}
        />

        {/* Road surface, laid flat and pushed back. */}
        <div
          aria-hidden
          className="absolute left-1/2 top-[18%] h-[520px] w-[280px] -translate-x-1/2 origin-top"
          style={{
            transform: 'rotateX(62deg)',
            background: `linear-gradient(to bottom, ${accent}00 0%, ${accent}26 22%, ${accent}3d 100%)`,
            borderLeft: `2px solid ${accent}55`,
            borderRight: `2px solid ${accent}55`,
          }}
        >
          {/* Centre line dashes — the strongest depth cue on the whole thing,
              because their spacing compresses toward the horizon for free once
              the parent is rotated. */}
          <div className="absolute inset-y-0 left-1/2 w-[3px] -translate-x-1/2">
            {Array.from({ length: 14 }).map((_, i) => (
              <div
                key={i}
                className="absolute w-full rounded-full"
                style={{
                  top: `${i * 7.2}%`,
                  height: '3.4%',
                  backgroundColor: `${accent}${i < 5 ? '44' : '77'}`,
                }}
              />
            ))}
          </div>
        </div>

        {/* Milestones. Positioned along the visual road, nearest at the bottom, so
            the candidate reads their progress from where they are toward the goal. */}
        <div className="absolute inset-0">
          {milestones.map((m, i) => {
            // Nearest milestone last => draw order puts near ones on top.
            const t = milestones.length === 1 ? 1 : i / (milestones.length - 1);
            // Non-linear so the far end compresses like real perspective.
            const depth = Math.pow(t, 1.55);
            const bottom = 18 + depth * 56; // % up the frame
            const scale = 1 - depth * 0.52;
            const isCurrent = i === current;

            return (
              <motion.button
                key={m.id}
                type="button"
                onClick={() => onSelect?.(m.id)}
                initial={reduced ? false : { opacity: 0, y: 14 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: reduced ? 0 : 0.04 * (milestones.length - i), duration: 0.4 }}
                className="absolute left-1/2 flex -translate-x-1/2 items-center gap-2 whitespace-nowrap rounded-full border px-3 py-1.5 text-xs font-semibold backdrop-blur-sm transition-colors"
                style={{
                  bottom: `${bottom}%`,
                  scale,
                  zIndex: milestones.length - i,
                  borderColor: m.done ? `${accent}` : isCurrent ? accent : 'hsl(var(--border))',
                  backgroundColor: m.done
                    ? accent
                    : isCurrent
                      ? `${accent}22`
                      : 'hsl(var(--surface-elevated))',
                  color: m.done ? '#fff' : 'hsl(var(--foreground))',
                  boxShadow: isCurrent ? `0 0 20px ${accent}66` : undefined,
                }}
                title={m.sublabel ? `${m.label} — ${m.sublabel}` : m.label}
              >
                {m.done ? (
                  <CheckCircle2 className="h-3.5 w-3.5" />
                ) : isCurrent ? (
                  <MapPin className="h-3.5 w-3.5" style={{ color: accent }} />
                ) : (
                  <Circle className="h-3.5 w-3.5 opacity-40" />
                )}
                <span className="max-w-[190px] truncate">{m.label}</span>
              </motion.button>
            );
          })}
        </div>

        {/* The destination. */}
        <div className="absolute inset-x-0 top-[9%] flex justify-center">
          <div
            className="flex items-center gap-1.5 rounded-full border px-3 py-1 text-[10px] font-bold uppercase tracking-wider"
            style={{
              borderColor: `${accent}66`,
              backgroundColor: `${accent}1a`,
              color: accent,
              opacity: pct === 100 ? 1 : 0.75,
            }}
          >
            {pct === 100 ? <CheckCircle2 className="h-3 w-3" /> : <Lock className="h-3 w-3" />}
            Interview ready
          </div>
        </div>
      </div>

      <p className="mt-3 text-center text-[11px] text-muted-foreground">
        {current === -1
          ? 'Every topic ticked off. Go and sit the interview.'
          : `Next up: ${milestones[current]?.label}`}
      </p>
    </div>
  );
}

/** Progress bar shown per phase, so a long plan still feels sectioned. */
export function PhaseProgress({
  done,
  total,
  accent,
  className,
}: {
  done: number;
  total: number;
  accent: string;
  className?: string;
}) {
  const pct = total ? (done / total) * 100 : 0;
  return (
    <div className={cn('flex items-center gap-2', className)}>
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-secondary">
        <motion.div
          className="h-full rounded-full"
          style={{ backgroundColor: accent }}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
        />
      </div>
      <span className="text-[10px] font-bold tabular-nums text-muted-foreground">
        {done}/{total}
      </span>
    </div>
  );
}
