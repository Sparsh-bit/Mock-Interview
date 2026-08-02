import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const badgeVariants = cva(
  'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold border',
  {
    variants: {
      variant: {
        neutral: 'border-border text-muted-foreground bg-secondary',
        primary: 'border-primary/20 text-primary bg-primary/10',
        success: 'border-accent-emerald/25 text-accent-emerald-ink bg-accent-emerald-soft',
        warning: 'border-accent-amber/30 text-accent-amber-ink bg-accent-amber-soft',
        danger: 'border-accent-coral/25 text-accent-coral-ink bg-accent-coral-soft',
        // Behavioural / HR. Named `violet` for its callers; plum is the colour.
        violet: 'border-accent-plum/25 text-accent-plum-ink bg-accent-plum-soft',
        info: 'border-accent-teal/25 text-accent-teal-ink bg-accent-teal-soft',
      },
    },
    defaultVariants: { variant: 'neutral' },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
