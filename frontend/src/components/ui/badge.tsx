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
        success: 'border-emerald-200 text-emerald-700 bg-emerald-50',
        warning: 'border-amber-200 text-amber-700 bg-amber-50',
        danger: 'border-red-200 text-red-700 bg-red-50',
        violet: 'border-accent-violet/20 text-accent-violet bg-accent-violet/10',
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
