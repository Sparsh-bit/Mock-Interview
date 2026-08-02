import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

/**
 * Rounded-square icon tile with a soft tinted fill — the main device for
 * carrying the palette into otherwise white surfaces (stat cards, feature
 * rows, section headers).
 *
 * The fills are the designed `-soft` tints rather than an alpha of the base
 * colour. An alpha fill composites against whatever is behind it, so the same
 * tile came out one colour on the white cards and another on the warm page
 * ground. `-soft` is a fixed value and looks identical on both.
 *
 * The keys are colour names because that is what every existing caller passes.
 * The colour each one resolves to is the semantic one — `pink` is the plum used
 * for behavioural rounds, `cyan` the teal used for data.
 */
const tileVariants = cva(
  'inline-flex items-center justify-center rounded-2xl',
  {
    variants: {
      color: {
        blue: 'bg-accent-indigo-soft text-accent-indigo-ink',
        violet: 'bg-accent-plum-soft text-accent-plum-ink',
        emerald: 'bg-accent-emerald-soft text-accent-emerald-ink',
        amber: 'bg-accent-amber-soft text-accent-amber-ink',
        cyan: 'bg-accent-teal-soft text-accent-teal-ink',
        pink: 'bg-accent-plum-soft text-accent-plum-ink',
        red: 'bg-accent-coral-soft text-accent-coral-ink',
      },
      size: {
        sm: 'h-9 w-9',
        md: 'h-11 w-11',
        lg: 'h-14 w-14',
      },
    },
    defaultVariants: { color: 'blue', size: 'md' },
  }
);

export interface IconTileProps
  extends Omit<React.HTMLAttributes<HTMLSpanElement>, 'color'>,
    VariantProps<typeof tileVariants> {}

export function IconTile({ className, color, size, ...props }: IconTileProps) {
  return <span className={cn(tileVariants({ color, size }), className)} {...props} />;
}
