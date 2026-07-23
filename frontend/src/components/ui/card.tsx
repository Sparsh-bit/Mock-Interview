'use client';

import * as React from 'react';
import { motion, type HTMLMotionProps } from 'framer-motion';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const cardVariants = cva('rounded-2xl', {
  variants: {
    variant: {
      glass: 'glass',
      elevated: 'bg-surface-elevated shadow-card',
      flat: 'bg-surface border border-border/60',
      outline: 'bg-surface-elevated border border-border',
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
          hoverable && 'ease-out-expo transition-shadow duration-300 hover:shadow-card-hover',
          className
        )}
        whileHover={hoverable ? { y: -3 } : undefined}
        transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
        {...props}
      >
        {children}
      </motion.div>
    );
  }
);
Card.displayName = 'Card';
