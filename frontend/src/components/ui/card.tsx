'use client';

import * as React from 'react';
import { motion, type HTMLMotionProps } from 'framer-motion';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const cardVariants = cva('rounded-xl border', {
  variants: {
    variant: {
      glass: 'glass',
      elevated: 'bg-surface-elevated border-border/60 shadow-card',
      flat: 'bg-surface border-border/50',
      outline: 'bg-transparent border-border',
    },
    padding: {
      none: '',
      sm: 'p-4',
      md: 'p-6',
      lg: 'p-8',
    },
  },
  defaultVariants: { variant: 'glass', padding: 'md' },
});

export interface CardProps
  extends Omit<HTMLMotionProps<'div'>, 'children'>,
    VariantProps<typeof cardVariants> {
  hoverable?: boolean;
  children?: React.ReactNode;
}

export const Card = React.forwardRef<HTMLDivElement, CardProps>(
  ({ className, variant, padding, hoverable, children, ...props }, ref) => {
    return (
      <motion.div
        ref={ref}
        className={cn(
          cardVariants({ variant, padding }),
          hoverable && 'transition-colors duration-300 hover:border-primary/40',
          className
        )}
        whileHover={hoverable ? { y: -4 } : undefined}
        transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
        {...props}
      >
        {children}
      </motion.div>
    );
  }
);
Card.displayName = 'Card';
