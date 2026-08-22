'use client';

import * as React from 'react';
import { motion, type HTMLMotionProps } from 'framer-motion';
import { cva, type VariantProps } from 'class-variance-authority';
import { Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';

/**
 * WHY THE LABEL WRAPS AND THE HEIGHT IS A FLOOR.
 *
 * This used to be `whitespace-nowrap` with a fixed `h-9`/`h-11`/`h-12`. Both halves of that
 * broke the same way, and only at narrow widths, which is why it survived so long.
 *
 * `whitespace-nowrap` means a button is at least as wide as its longest label, forever. A
 * button is a flex item, so when the row it sits in is narrower than that — a two-button
 * action row at 320px, a card action inside a collapsed grid column, anything at 200% browser
 * zoom — the button cannot shrink and cannot wrap, so it pushes past its container. Because the
 * container is usually a card or a shell with `overflow-hidden`, the right-hand end of the
 * label (and often the button's own right edge) is simply gone: not scrollable, not reachable.
 * Where the ancestor does scroll, it is the whole PAGE body that scrolls sideways, which is
 * the reported complaint from the other direction.
 *
 * Removing it is safe for the desktop layout that already works: a label only wraps when it
 * genuinely cannot fit on one line, and where there is room nothing moves. In a `flex-wrap`
 * row the button still takes a whole new line rather than squeezing, because flex wrapping is
 * decided on the item's content width before any shrinking happens.
 *
 * But a wrapped label inside a FIXED height overflows it vertically — the second line renders
 * outside the pill. So the heights are floors (`min-h-*`) rather than fixed: identical to
 * before for the single-line case that is every button on a wide screen, and grows by exactly
 * one line where the label had to wrap. `text-center` is what keeps the second line aligned
 * under the first; `justify-center` alone centres the text BLOCK, not the lines inside it.
 *
 * `size: 'icon'` deliberately keeps `h-10 w-10`. It holds a glyph, never a wrapping label, so
 * neither failure applies to it.
 */
export const buttonVariants = cva(
  'inline-flex max-w-full items-center justify-center gap-2 rounded-full text-center font-medium ' +
    'transition-[color,background-color,border-color,box-shadow,transform,opacity] ease-out-expo disabled:pointer-events-none disabled:opacity-40 ' +
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ' +
    'focus-visible:ring-offset-background',
  {
    variants: {
      variant: {
        primary:
          'bg-primary text-primary-foreground shadow-btn-primary hover:bg-primary/90',
        secondary:
          'bg-secondary text-secondary-foreground hover:bg-accent',
        ghost: 'text-muted-foreground hover:text-foreground hover:bg-secondary',
        destructive: 'bg-destructive text-destructive-foreground hover:bg-destructive/90',
        outline: 'border border-border bg-surface-elevated text-foreground hover:bg-secondary',
      },
      size: {
        sm: 'min-h-9 px-4 py-1.5 text-[13px]',
        md: 'min-h-11 px-6 py-2 text-sm',
        lg: 'min-h-12 px-8 py-2.5 text-base',
        icon: 'h-10 w-10 shrink-0 p-0',
      },
    },
    defaultVariants: {
      variant: 'primary',
      size: 'md',
    },
  }
);

export interface ButtonProps
  extends Omit<HTMLMotionProps<'button'>, 'children'>,
    VariantProps<typeof buttonVariants> {
  loading?: boolean;
  children?: React.ReactNode;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, loading, disabled, children, ...props }, ref) => {
    return (
      <motion.button
        ref={ref}
        className={cn(buttonVariants({ variant, size }), className)}
        disabled={disabled || loading}
        whileHover={{ scale: disabled || loading ? 1 : 1.02 }}
        whileTap={{ scale: disabled || loading ? 1 : 0.96 }}
        transition={{ duration: 0.15 }}
        {...props}
      >
        {/* shrink-0: the label beside it is now allowed to wrap and therefore to shrink, and a
            flex row shrinks every item that will let it — without this the spinner squashes to
            an ellipse on a narrow button. */}
        {loading && <Loader2 className="h-4 w-4 shrink-0 animate-spin" />}
        {children}
      </motion.button>
    );
  }
);
Button.displayName = 'Button';
