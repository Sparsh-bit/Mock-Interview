import * as React from 'react';
import { cn } from '@/lib/utils';

/**
 * The one text input.
 *
 * `text-base sm:text-sm` — AND THE ORDER OF THOSE TWO MATTERS MORE THAN IT LOOKS.
 *
 * iOS Safari zooms the page in when a form field with a font size under 16px receives focus.
 * It is not configurable and `user-scalable=no` no longer suppresses it (nor should it — it
 * would break pinch-zoom for everyone). The result on this app was a real defect rather than a
 * cosmetic one: tapping the email box on the sign-in page scaled the viewport up, the page
 * became wider than the screen, and the submit button was pushed off to the right where the
 * user had to scroll sideways — while the keyboard covered the bottom — to find it. It never
 * zooms back out on blur either, so every screen after it stayed magnified and clipped.
 *
 * 16px (`text-base`) is exactly the threshold, so the field is 16px on phones and returns to
 * the design's 14px from 640px up, where no browser does this.
 *
 * `min-h-11` is a floor, not a height: 44px is the smallest reliable touch target, and
 * `py-2.5` around a 14px line box came to 40. It changes nothing above the breakpoint, where
 * the 16px line box already fills it.
 */
export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => {
    return (
      <input
        ref={ref}
        className={cn(
          'ease-out-expo min-h-11 w-full rounded-xl border border-border bg-surface-elevated px-4 py-2.5 text-base sm:text-sm ' +
            'text-foreground placeholder:text-muted-foreground transition-[color,background-color,border-color,box-shadow,transform,opacity] focus:border-primary ' +
            'focus:outline-none focus:ring-2 focus:ring-primary/30',
          className
        )}
        {...props}
      />
    );
  }
);
Input.displayName = 'Input';
