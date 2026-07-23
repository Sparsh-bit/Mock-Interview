import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const badgeVariants = cva(
  'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold border',
  {
    variants: {
      variant: {
        neutral: 'border-border text-muted-foreground bg-transparent',
        primary: 'border-primary/30 text-primary bg-primary/10',
        success: 'border-emerald-500/30 text-emerald-400 bg-emerald-500/10',
        warning: 'border-yellow-500/30 text-yellow-400 bg-yellow-500/10',
        danger: 'border-red-500/30 text-red-400 bg-red-500/10',
        violet: 'border-accent-violet/30 text-accent-violet bg-accent-violet/10',
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
