'use client';

import * as React from 'react';
import { motion, type HTMLMotionProps } from 'framer-motion';
import { type VariantProps } from 'class-variance-authority';
import { buttonVariants } from './button-variants';
import { Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';

/*
 * `buttonVariants` moved to ./button-variants so SERVER components can use it — this module is
 * `'use client'` for framer-motion's sake, and that marks every one of its exports as
 * client-only. Re-exported here so the ten existing importers did not have to change.
 */
export { buttonVariants } from './button-variants';

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
