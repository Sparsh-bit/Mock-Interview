'use client';

import { motion, useInView } from 'framer-motion';
import { useRef } from 'react';

import { cn } from '@/lib/utils';

/**
 * A vertical timeline with a drawn spine — components/lightswind-pro/timeline-layout.tsx
 *
 * Local implementation at the import path the brief named; `lightswind-pro` is not installed.
 * See the note in flip-words.tsx.
 *
 * WHY A STUDY ROADMAP WANTS THIS. The phases were rendered as a stack of sections, which is
 * accurate and says nothing about the shape of the plan. A spine says "this is a sequence with
 * a beginning and an end", which is the single most useful thing a candidate counting weeks
 * until a placement drive needs to see.
 *
 * THE SPINE DRAWS ITSELF as each phase scrolls in, rather than all at once on mount. A plan is
 * read top to bottom, so the line arriving with the reader reinforces the sequence; a
 * pre-drawn line is just a border.
 *
 * A COMPOSITION WRAPPER, not a renderer. It supplies the spine, the node and the reveal, and
 * the caller keeps its own content. Roadmap phases already render topics, subtopics, progress
 * and hours — reimplementing all of that inside a timeline component would have been a
 * rewrite of a working page for a decoration.
 */
export interface TimelineItemProps {
  /** Shown inside the node. A phase number, or a short label. */
  marker?: React.ReactNode;
  /** Last item — its spine segment is not drawn, so the line ends rather than trailing off. */
  isLast?: boolean;
  /** Emphasises the node. Used for the phase a candidate is currently in. */
  active?: boolean;
  index?: number;
  children: React.ReactNode;
  className?: string;
}

export function TimelineItem({
  marker,
  isLast = false,
  active = false,
  index = 0,
  children,
  className,
}: TimelineItemProps) {
  const ref = useRef<HTMLDivElement | null>(null);
  const inView = useInView(ref, { once: true, margin: '-10% 0px -10% 0px' });

  return (
    <div ref={ref} className={cn('relative pl-10 sm:pl-12', className)}>
      {/* The spine segment for THIS item, drawn downward as it enters. scaleY with a top
          origin so it grows from the node rather than fading in along its whole length. */}
      {!isLast && (
        <motion.span
          aria-hidden
          className="absolute left-[13px] top-7 w-px bg-border sm:left-[17px]"
          style={{ bottom: '-1.75rem', transformOrigin: 'top' }}
          initial={{ scaleY: 0 }}
          animate={inView ? { scaleY: 1 } : { scaleY: 0 }}
          transition={{ duration: 0.5, delay: 0.12, ease: 'easeOut' }}
        />
      )}

      <motion.span
        aria-hidden
        className={cn(
          'absolute left-0 top-1 flex h-[27px] w-[27px] items-center justify-center rounded-full',
          'border font-mono text-[10px] tabular-nums sm:h-[35px] sm:w-[35px] sm:text-[11px]',
          active
            ? 'border-primary/50 bg-primary/10 text-primary'
            : 'border-border bg-card text-muted-foreground',
        )}
        initial={{ opacity: 0, scale: 0.8 }}
        animate={inView ? { opacity: 1, scale: 1 } : { opacity: 0, scale: 0.8 }}
        transition={{ duration: 0.32, delay: index * 0.04, ease: [0.22, 1, 0.36, 1] }}
      >
        {marker}
      </motion.span>

      {children}
    </div>
  );
}

export interface TimelineLayoutProps {
  children: React.ReactNode;
  className?: string;
}

export default function TimelineLayout({ children, className }: TimelineLayoutProps) {
  return <div className={cn('relative', className)}>{children}</div>;
}
