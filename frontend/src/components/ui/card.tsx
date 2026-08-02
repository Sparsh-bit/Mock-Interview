import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

/**
 * The card surface.
 *
 * A PLAIN DIV. This was a `motion.div` for all 44 of its uses, and not one
 * caller passed a single framer-motion prop — the only thing motion did here
 * was `whileHover={{ y: -3 }}`, a one-property hover that CSS does natively.
 *
 * The cost was not theoretical. Every card mounted a motion component: a
 * MotionContext subscription, a MotionValue tree, and pointer listeners
 * attached per element to drive the hover. A dashboard rendering a dozen cards
 * paid a dozen of each, on every render, for an effect a `hover:` class gives
 * for free.
 *
 * It also forced `'use client'`, which propagated to every page that renders a
 * card whether or not that page needed interactivity. Without motion the card
 * is static markup and renders on the server.
 *
 * The hover is compositor-only on purpose. `transform` never touches layout,
 * and naming both properties instead of `transition-all` stops the browser
 * watching every animatable property on every card for a change that only ever
 * affects two.
 */
const cardVariants = cva('rounded-xl', {
  variants: {
    variant: {
      glass: 'glass',
      elevated: 'bg-surface-elevated shadow-elev-1',
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
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof cardVariants> {
  hoverable?: boolean;
}

export const Card = React.forwardRef<HTMLDivElement, CardProps>(
  ({ className, variant, padding, hoverable, children, ...props }, ref) => {
    return (
      <div
        ref={ref}
        className={cn(
          cardVariants({ variant, padding }),
          hoverable &&
            'ease-out-expo transition-[transform,box-shadow] duration-300 ' +
              'hover:-translate-y-[3px] hover:shadow-elev-2 ' +
              'motion-reduce:transition-none motion-reduce:hover:translate-y-0',
          className,
        )}
        {...props}
      >
        {children}
      </div>
    );
  },
);
Card.displayName = 'Card';
