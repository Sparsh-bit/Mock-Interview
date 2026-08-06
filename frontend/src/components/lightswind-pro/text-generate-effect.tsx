'use client';

import { motion, useInView } from 'framer-motion';
import { useRef } from 'react';

import { cn } from '@/lib/utils';

/**
 * Text that resolves word by word — components/lightswind-pro/text-generate-effect.tsx
 *
 * Local implementation at the import path the brief named; `lightswind-pro` is not installed.
 *
 * ON SCROLL, NOT ON MOUNT. The landing page is long and this is used partway down it. An
 * effect that fires on mount has already finished by the time the reader arrives, so it costs
 * animation and buys nothing.
 *
 * ONCE. Re-animating every time a section scrolls back into view turns a nice reveal into a
 * page that will not settle.
 *
 * THE TEXT IS ALWAYS IN THE DOM. Words animate their opacity rather than being added, so the
 * paragraph is selectable, searchable and readable by assistive tech from the start — and if
 * JavaScript never runs, the reader gets the text rather than a blank space.
 */
export interface TextGenerateEffectProps {
  text: string;
  className?: string;
  /** Seconds between words. 0.03 reads as "resolving"; past ~0.08 it reads as slow. */
  stagger?: number;
  delay?: number;
}

export default function TextGenerateEffect({
  text,
  className,
  stagger = 0.028,
  delay = 0,
}: TextGenerateEffectProps) {
  const ref = useRef<HTMLParagraphElement | null>(null);
  const inView = useInView(ref, { once: true, margin: '-15% 0px -15% 0px' });
  const words = text.split(' ');

  return (
    <p ref={ref} className={cn(className)}>
      {words.map((word, i) => (
        <motion.span
          key={`${word}-${i}`}
          // Not `hidden`: the word occupies its space from the first frame, so the paragraph
          // never reflows as it resolves.
          initial={{ opacity: 0.12 }}
          animate={inView ? { opacity: 1 } : { opacity: 0.12 }}
          transition={{ duration: 0.4, delay: delay + i * stagger, ease: 'easeOut' }}
          className="inline-block"
        >
          {word}
          {i < words.length - 1 ? ' ' : ''}
        </motion.span>
      ))}
    </p>
  );
}
