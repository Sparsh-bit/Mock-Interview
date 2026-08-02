import * as React from 'react';
import { cn } from '@/lib/utils';

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => {
    return (
      <input
        ref={ref}
        className={cn(
          'ease-out-expo w-full rounded-xl border border-border bg-surface-elevated px-4 py-2.5 text-sm ' +
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
