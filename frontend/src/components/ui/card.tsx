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
/*
 * `min-w-0` IS PART OF WHAT A CARD IS, and is the one responsive fact worth baking in here
 * rather than repeating at ~50 call sites.
 *
 * A card is nearly always a flex or grid child, and both default those children to
 * `min-width: auto` — "never narrower than my own content". So a single long unbreakable
 * string inside a card (a payment id, an order id, an email, a URL) makes the CARD wider than
 * its track, which makes the grid wider than the page, which makes the page body scroll
 * sideways at 320px. Where an ancestor is `overflow-hidden` — the dashboard shell is — there is
 * no sideways scroll either and the overflow is simply gone, with no gesture that reaches it.
 * `min-w-0` lets the card take the width it is given; wrapping the content is then the
 * content's job (`break-words` on the specific field), which is a fix that stays local to the
 * field that needs it.
 *
 * It also switches ON the `overflow-x-auto` that two admin cards already carry: a scroll
 * container does nothing until its own width is constrained, which `min-width: auto` was
 * preventing.
 *
 * THE PADDING SCALE IS DELIBERATELY NOT RESPONSIVE, though `p-8` at 320px does crowd text.
 * `cn` is tailwind-merge, and roughly fifty call sites already override padding with a bare
 * `p-5`/`p-8`/`p-0` in `className`. tailwind-merge treats `p-5` and `sm:p-6` as different
 * groups, so a variant of `p-4 sm:p-6` would leave `sm:p-6` standing next to every one of
 * those overrides — silently resetting fifty cards to 24px padding from 640px up, and putting
 * padding back on the two `p-0` cards that are deliberately edge-to-edge. A page that needs
 * tighter padding on a phone asks for it (`className="p-5 sm:p-8"`), which is local and
 * visible.
 */
const cardVariants = cva('min-w-0 rounded-xl', {
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
