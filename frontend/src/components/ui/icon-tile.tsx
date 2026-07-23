import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

/**
 * iOS-style rounded-square icon tile with a soft colored fill — the main
 * device for injecting restrained, Apple-flavored color into otherwise
 * white/neutral surfaces (stat cards, feature rows, section headers).
 */
const tileVariants = cva(
  'inline-flex items-center justify-center rounded-2xl',
  {
    variants: {
      color: {
        blue: 'bg-primary/10 text-primary',
        violet: 'bg-accent-violet/10 text-accent-violet',
        emerald: 'bg-emerald-500/10 text-emerald-600',
        amber: 'bg-amber-500/10 text-amber-600',
        cyan: 'bg-accent-cyan/15 text-cyan-600',
        pink: 'bg-pink-500/10 text-pink-600',
        red: 'bg-red-500/10 text-red-600',
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
