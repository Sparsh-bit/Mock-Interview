'use client';

import { useRef } from 'react';
import { motion, useInView, useReducedMotion } from 'framer-motion';
import { cn } from '@/lib/utils';

/**
 * The landing page's one visual idea: it marks up its own sentences using the
 * product's own annotation language.
 *
 * InterviewOS annotates speech — it boxes your filler words, drops a timed chip
 * where you paused, strikes what was wrong and writes the better version beside
 * it. So the page does that to its own copy. The move escalates down the page and
 * ends by striking through the two claims this site itself used to make falsely
 * ("50+ company tracks", "2,000+ question bank") and replacing them with counted
 * numbers.
 *
 * That signature cannot be lifted onto another product's site: it only works for
 * something that annotates speech, and the finale only works for a company that
 * actually made those claims. That is the whole point — a generic move is a
 * template, and a template is what we are trying not to look like.
 *
 * ONE VERB, TWO GESTURES. Everything here is either a rule being drawn or content
 * wiping up from beneath a rule. Constraining the vocabulary this hard is what
 * keeps a page with this much motion from feeling like a slideshow.
 */

const EASE = [0.16, 1, 0.3, 1] as const;
const DRAW = [0.65, 0, 0.35, 1] as const;

/** Runs a child animation once, when it scrolls into view. */
function useReveal(margin: `${number}%` = '-15%') {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: false, margin });
  const reduced = useReducedMotion();
  return { ref, play: reduced ? true : inView, reduced: Boolean(reduced) };
}

/**
 * A filler word, boxed exactly as the product boxes it in a transcript.
 * The box is drawn, not faded — a fade would be decoration, a draw is a mark.
 */
export function Filler({ children }: { children: React.ReactNode }) {
  const { ref, play, reduced } = useReveal();
  return (
    <span ref={ref} className="relative inline-block px-1.5">
      <motion.span
        aria-hidden
        className="absolute inset-0 rounded-[3px] border border-current opacity-40"
        initial={reduced ? false : { clipPath: 'inset(0 100% 0 0)' }}
        animate={play ? { clipPath: 'inset(0 0% 0 0)' } : undefined}
        transition={{ duration: 0.45, ease: DRAW }}
      />
      <span className="relative">{children}</span>
    </span>
  );
}

/** A pause, shown where it happened, with its real duration. */
export function Pause({ seconds }: { seconds: number }) {
  const { ref, play, reduced } = useReveal();
  return (
    <motion.span
      ref={ref}
      className="mx-1 inline-flex translate-y-[-1px] items-center gap-1 rounded-full border border-current/25 px-2 py-0.5 align-middle font-mono text-[0.62em] opacity-55"
      initial={reduced ? false : { opacity: 0, scaleX: 0.6 }}
      animate={play ? { opacity: 0.55, scaleX: 1 } : undefined}
      transition={{ duration: 0.35, ease: EASE }}
      style={{ transformOrigin: 'left center' }}
    >
      {seconds}s
    </motion.span>
  );
}

/**
 * Text struck through by a rule that draws across it.
 *
 * `replacement` is the whole point of the finale: the false claim is struck and
 * the counted number rises from beneath the same rule.
 */
export function Strike({
  children,
  replacement,
  delay = 0,
}: {
  children: React.ReactNode;
  replacement?: React.ReactNode;
  delay?: number;
}) {
  const { ref, play, reduced } = useReveal();

  return (
    <span ref={ref} className="relative inline-flex flex-col items-start">
      <span className="relative inline-block opacity-45">
        {children}
        <motion.span
          aria-hidden
          className="absolute left-0 top-1/2 h-[1.5px] w-full bg-current"
          initial={reduced ? false : { scaleX: 0 }}
          animate={play ? { scaleX: 1 } : undefined}
          transition={{ duration: 0.5, delay, ease: DRAW }}
          style={{ transformOrigin: 'left center' }}
        />
      </span>

      {replacement && (
        <span className="relative overflow-hidden">
          <motion.span
            className="inline-block"
            initial={reduced ? false : { y: '105%' }}
            animate={play ? { y: '0%' } : undefined}
            transition={{ duration: 0.55, delay: delay + 0.35, ease: EASE }}
          >
            {replacement}
          </motion.span>
        </span>
      )}
    </span>
  );
}

/**
 * A hairline that draws itself across the width when it enters view.
 * The page's structural element — sections are divided by these, not by boxes.
 */
export function Rule({ className, delay = 0 }: { className?: string; delay?: number }) {
  const { ref, play, reduced } = useReveal('-5%');
  return (
    <span ref={ref} className={cn('block h-px w-full bg-border', className)}>
      <motion.span
        className="block h-full w-full bg-foreground/25"
        initial={reduced ? false : { scaleX: 0 }}
        animate={play ? { scaleX: 1 } : undefined}
        transition={{ duration: 0.7, delay, ease: DRAW }}
        style={{ transformOrigin: 'left center' }}
      />
    </span>
  );
}

/**
 * Content that wipes up from beneath a rule.
 *
 * The page's only entrance. Everything arrives the same way, which is what makes
 * a long page feel composed rather than assembled — and it reads as text being
 * written onto a page rather than a card floating in.
 */
export function WipeUp({
  children,
  delay = 0,
  className,
}: {
  children: React.ReactNode;
  delay?: number;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: false, margin: '-12%' as const });
  const reduced = useReducedMotion();

  return (
    <div ref={ref} className={cn('overflow-hidden', className)}>
      <motion.div
        initial={reduced ? false : { y: '100%', opacity: 0 }}
        animate={inView || reduced ? { y: '0%', opacity: 1 } : undefined}
        transition={{ duration: 0.75, delay, ease: EASE }}
      >
        {children}
      </motion.div>
    </div>
  );
}

/** A section number + label, set as a running head. */
export function SectionMark({ n, label }: { n: string; label: string }) {
  return (
    <WipeUp>
      <p className="flex items-baseline gap-3 font-mono text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
        <span className="tabular-nums">{n}</span>
        <span>{label}</span>
      </p>
    </WipeUp>
  );
}
