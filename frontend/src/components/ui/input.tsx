import * as React from 'react';
import { cn } from '@/lib/utils';

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => {
    return (
      <input
        ref={ref}
        className={cn(
          'ease-out-expo w-full rounded-lg border border-border bg-surface px-4 py-2.5 text-sm ' +
            'placeholder:text-muted-foreground transition-all focus:border-primary focus:outline-none ' +
            'focus:ring-2 focus:ring-primary/50',
          className
        )}
        {...props}
      />
    );
  }
);
Input.displayName = 'Input';
