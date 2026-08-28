'use client';

import { Star } from 'lucide-react';
import { useState } from 'react';

import { cn } from '@/lib/utils';

/**
 * Five stars — components/ui/star-rating.tsx
 *
 * A RADIO GROUP, NOT FIVE BUTTONS, and the difference is whether this is usable without a
 * mouse. Five separate buttons put five stops in the tab order and give a screen reader no way
 * to say "3 of 5 selected"; a radiogroup is one stop, arrow keys move between options, and the
 * selected value is announced. The visual is identical either way — the semantics are the
 * whole change.
 *
 * HOVER PREVIEW IS DELIBERATELY NOT STATE THE PARENT SEES. It is a local `hover` value that
 * paints, nothing more. A parent that received hover changes would re-render on every mouse
 * move across the row, and a "rating" that changed as the cursor passed over it would submit
 * whatever the pointer happened to be under.
 */
export interface StarRatingProps {
  value: number;
  onChange: (value: number) => void;
  /** Accessible name for the group, e.g. "How was your interview?" */
  label: string;
  disabled?: boolean;
  className?: string;
}

const STARS = [1, 2, 3, 4, 5] as const;

//: What each value means, read out by assistive tech and shown on hover. A bare number tells
//: somebody nothing about which end is good.
const MEANING: Record<number, string> = {
  1: 'Poor',
  2: 'Fair',
  3: 'Good',
  4: 'Great',
  5: 'Excellent',
};

export function StarRating({
  value,
  onChange,
  label,
  disabled = false,
  className,
}: StarRatingProps) {
  const [hover, setHover] = useState(0);
  const shown = hover || value;

  return (
    <div className={cn('flex flex-col items-center gap-1.5', className)}>
      <div
        role="radiogroup"
        aria-label={label}
        className="flex items-center gap-1"
        onMouseLeave={() => setHover(0)}
      >
        {STARS.map((star) => {
          const filled = star <= shown;
          return (
            <button
              key={star}
              type="button"
              role="radio"
              aria-checked={value === star}
              aria-label={`${star} ${star === 1 ? 'star' : 'stars'} — ${MEANING[star]}`}
              disabled={disabled}
              // -1 for every star except the selected one (or the first, when nothing is
              // selected yet). That is the roving tabindex a radiogroup needs: one tab stop
              // for the whole control, arrows to move within it.
              tabIndex={value === star || (value === 0 && star === 1) ? 0 : -1}
              onMouseEnter={() => !disabled && setHover(star)}
              onFocus={() => !disabled && setHover(star)}
              onBlur={() => setHover(0)}
              onClick={() => !disabled && onChange(star)}
              onKeyDown={(e) => {
                if (disabled) return;
                // Arrow keys move and SELECT, which is the standard radiogroup behaviour —
                // moving focus without selecting would leave a keyboard user unable to choose.
                if (e.key === 'ArrowRight' || e.key === 'ArrowUp') {
                  e.preventDefault();
                  onChange(Math.min(5, (value || 0) + 1));
                } else if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') {
                  e.preventDefault();
                  onChange(Math.max(1, (value || 2) - 1));
                }
              }}
              className={cn(
                'rounded-md p-1 transition-transform',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                !disabled && 'hover:scale-110',
                disabled && 'cursor-not-allowed opacity-50',
              )}
            >
              <Star
                className={cn(
                  'h-7 w-7 transition-colors',
                  filled
                    ? 'fill-accent-amber text-accent-amber'
                    : 'fill-transparent text-muted-foreground/40',
                )}
                aria-hidden
              />
            </button>
          );
        })}
      </div>

      {/* The word, not just the count. `aria-live` is deliberately absent: the radio's own
          aria-label is announced on selection, and a live region would say it twice. */}
      <p className="h-4 text-xs text-muted-foreground">{shown ? MEANING[shown] : ' '}</p>
    </div>
  );
}

export default StarRating;
