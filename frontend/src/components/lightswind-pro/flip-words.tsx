'use client';

import { AnimatePresence, motion } from 'framer-motion';
import { useCallback, useEffect, useState } from 'react';

import { cn } from '@/lib/utils';

/**
 * A word that cycles — components/lightswind-pro/flip-words.tsx
 *
 * NOTE ON PROVENANCE: this is a local implementation at the import path the brief named.
 * `lightswind` / `lightswind-pro` are not installed in this project and are not in
 * package.json, so those imports would fail the build. Built against this codebase's own
 * design system instead, at the same path — so if the real package is added later, replacing
 * this file is the whole migration.
 *
 * WHERE IT EARNS ITS PLACE. This product covers twelve recruiters, and a static headline can
 * only name one. Cycling them says "we cover yours" to a candidate preparing for Wipro
 * without writing a list. Used once, in the hero.
 *
 * The width is reserved for the LONGEST word rather than animated per word. A container that
 * resizes on every flip shoves the rest of the line sideways, which reads as a layout bug
 * rather than an effect.
 */
export interface FlipWordsProps {
  words: string[];
  /** Milliseconds each word holds. Below ~1.8s it reads as a flicker rather than a list. */
  interval?: number;
  className?: string;
}

export default function FlipWords({ words, interval = 2400, className }: FlipWordsProps) {
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);

  const advance = useCallback(() => setIndex((i) => (i + 1) % words.length), [words.length]);

  useEffect(() => {
    if (paused || words.length < 2) return;
    const id = window.setInterval(advance, interval);
    return () => window.clearInterval(id);
  }, [advance, interval, paused, words.length]);

  // Respect the OS setting. An element that never stops moving is a genuine accessibility
  // problem for vestibular disorders, and this one sits in the first thing anyone reads.
  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const sync = () => setPaused(mq.matches);
    sync();
    mq.addEventListener('change', sync);
    return () => mq.removeEventListener('change', sync);
  }, []);

  const longest = words.reduce((a, b) => (b.length > a.length ? b : a), '');

  return (
    <span className={cn('relative inline-grid align-baseline', className)}>
      {/* Reserves the width of the longest word so the line never reflows. Hidden from
          assistive tech and from the pointer; it exists only to hold space open. */}
      <span aria-hidden className="invisible col-start-1 row-start-1 whitespace-nowrap">
        {longest}
      </span>
      <AnimatePresence mode="wait" initial={false}>
        <motion.span
          key={words[index]}
          className="col-start-1 row-start-1 whitespace-nowrap"
          initial={{ y: '0.4em', opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: '-0.4em', opacity: 0 }}
          transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
        >
          {words[index]}
        </motion.span>
      </AnimatePresence>
      {/* The full list, for screen readers and for anyone with motion reduced — otherwise
          the page only ever announces whichever word happened to be showing. */}
      <span className="sr-only">{words.join(', ')}</span>
    </span>
  );
}
