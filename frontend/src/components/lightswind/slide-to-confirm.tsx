'use client';

import { motion, useMotionValue, useTransform } from 'framer-motion';
import { ChevronRight } from 'lucide-react';
import { useRef, useState } from 'react';

import { cn } from '@/lib/utils';

/**
 * Slide to confirm — components/lightswind/slide-to-confirm.tsx
 *
 * Local implementation at the import path the brief named; `lightswind` is not installed. See
 * the note in lightswind-pro/flip-words.tsx.
 *
 * WHERE THIS IS THE RIGHT CONTROL, AND WHERE IT IS THEATRE. A slide is worth it only when the
 * action is irreversible and a mis-tap is expensive. "End the interview" qualifies: it closes
 * the session, triggers report generation, and there is no way back into the round. A slide
 * makes that a deliberate gesture rather than something you can do by brushing the screen on
 * a phone mid-answer.
 *
 * It would be theatre on anything ordinary, which is why it is used once.
 *
 * WHY NOT A CONFIRM DIALOG. A dialog is one extra tap and a modal that steals focus, in the
 * middle of a timed round where the candidate may be mid-sentence. This asks for intent
 * without taking over the screen.
 *
 * SNAPS BACK IF NOT COMPLETED, so an accidental partial drag is visibly nothing rather than
 * ambiguously something. And the whole control is a real <button> underneath: a keyboard user
 * gets Enter, because a drag-only control is unusable without a pointer.
 */
export interface SlideToConfirmProps {
  onConfirm: () => void;
  label?: string;
  confirmedLabel?: string;
  disabled?: boolean;
  className?: string;
  /** 'danger' tints it destructive. Used for actions that end something. */
  tone?: 'default' | 'danger';
}

export function SlideToConfirm({
  onConfirm,
  label = 'Slide to confirm',
  confirmedLabel = 'Confirmed',
  disabled = false,
  className,
  tone = 'default',
}: SlideToConfirmProps) {
  const trackRef = useRef<HTMLDivElement | null>(null);
  const [done, setDone] = useState(false);
  const x = useMotionValue(0);

  // The label fades out as the thumb crosses it, so it is never read through the handle.
  const labelOpacity = useTransform(x, [0, 90], [1, 0]);

  const complete = () => {
    if (done || disabled) return;
    setDone(true);
    onConfirm();
  };

  const trackWidth = () => (trackRef.current?.offsetWidth ?? 260) - 48;

  return (
    <div
      ref={trackRef}
      className={cn(
        'relative h-12 w-full select-none overflow-hidden rounded-full border',
        tone === 'danger'
          ? 'border-destructive/40 bg-destructive/5'
          : 'border-border bg-surface-elevated',
        disabled && 'pointer-events-none opacity-50',
        className,
      )}
    >
      <motion.span
        style={{ opacity: done ? 1 : labelOpacity }}
        className={cn(
          'pointer-events-none absolute inset-0 flex items-center justify-center text-xs font-semibold',
          tone === 'danger' ? 'text-destructive' : 'text-muted-foreground',
        )}
      >
        {done ? confirmedLabel : label}
      </motion.span>

      <motion.button
        type="button"
        // A real button, so Enter and Space work. A drag-only control is unusable for anyone
        // without a pointer, and this one ends an interview.
        onClick={complete}
        aria-label={label}
        drag={done ? false : 'x'}
        dragConstraints={{ left: 0, right: trackWidth() }}
        dragElastic={0}
        dragMomentum={false}
        style={{ x }}
        onDragEnd={() => {
          // 85% of the track. Requiring the full width means a slightly short drag on a
          // narrow phone silently does nothing.
          if (x.get() >= trackWidth() * 0.85) {
            x.set(trackWidth());
            complete();
          } else {
            x.set(0);
          }
        }}
        className={cn(
          'absolute left-1 top-1 flex h-10 w-10 cursor-grab items-center justify-center rounded-full',
          'outline-none transition-colors active:cursor-grabbing',
          'focus-visible:ring-2 focus-visible:ring-primary/40',
          tone === 'danger'
            ? 'bg-destructive text-destructive-foreground'
            : 'bg-primary text-primary-foreground',
        )}
      >
        <ChevronRight className="h-4 w-4" />
      </motion.button>
    </div>
  );
}

export default SlideToConfirm;
