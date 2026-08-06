'use client';

import { forwardRef, useId, useState } from 'react';

import { cn } from '@/lib/utils';

/**
 * An input whose label moves out of the way — components/lightswind-pro/floating-label-input.tsx
 *
 * Local implementation at the import path the brief named; `lightswind-pro` is not installed.
 * See the note in flip-words.tsx.
 *
 * WHY IT IS BETTER THAN A PLACEHOLDER, which is what it replaces. A placeholder disappears the
 * moment you type, so anyone who is interrupted mid-form comes back to a filled box with no
 * idea what it wanted. That is a real usability defect, not a style preference — and it is
 * worse on a signup form, where getting it wrong means the account is created with the wrong
 * details.
 *
 * A REAL <label>, not a positioned span. It carries htmlFor, so clicking it focuses the field
 * and a screen reader announces the two together. A floating label built from a div is a
 * decoration that has removed an accessible name.
 *
 * The label floats when the field has focus OR content — content matters, or the label drops
 * back over the user's own text the moment they tab away.
 */
export interface FloatingLabelInputProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'placeholder'> {
  label: string;
  /** Shown under the field, in the destructive colour. Also sets aria-invalid. */
  error?: string;
  /** Shown under the field when there is no error — a format hint, for instance. */
  hint?: string;
}

const FloatingLabelInput = forwardRef<HTMLInputElement, FloatingLabelInputProps>(
  function FloatingLabelInput({ label, error, hint, className, value, onChange, ...props }, ref) {
    const reactId = useId();
    const id = props.id ?? reactId;
    const [focused, setFocused] = useState(false);
    // Uncontrolled inputs have no `value` to read, so track whether anything was typed.
    const [hasText, setHasText] = useState(false);
    const filled = value !== undefined ? String(value).length > 0 : hasText;
    const floating = focused || filled;

    return (
      <div className="w-full">
        <div className="relative">
          <input
            {...props}
            id={id}
            ref={ref}
            value={value}
            aria-invalid={!!error}
            aria-describedby={error || hint ? `${id}-msg` : undefined}
            onChange={(e) => {
              setHasText(e.target.value.length > 0);
              onChange?.(e);
            }}
            onFocus={(e) => {
              setFocused(true);
              props.onFocus?.(e);
            }}
            onBlur={(e) => {
              setFocused(false);
              props.onBlur?.(e);
            }}
            // Top padding leaves room for the floated label; without it the label lands on
            // the text.
            className={cn(
              'peer w-full rounded-xl border bg-surface-elevated px-4 pb-2 pt-6 text-sm',
              'outline-none transition-colors placeholder:text-transparent',
              error
                ? 'border-destructive/50 focus:border-destructive'
                : 'border-border focus:border-primary/60',
              className,
            )}
          />
          <label
            htmlFor={id}
            className={cn(
              'pointer-events-none absolute left-4 origin-left transition-all duration-200',
              floating
                ? 'top-1.5 text-[10px] font-semibold uppercase tracking-wider'
                : 'top-1/2 -translate-y-1/2 text-sm',
              error
                ? 'text-destructive'
                : floating
                  ? 'text-muted-foreground'
                  : 'text-muted-foreground/70',
            )}
          >
            {label}
          </label>
        </div>
        {(error || hint) && (
          <p
            id={`${id}-msg`}
            className={cn(
              'mt-1.5 text-[11px] leading-snug',
              error ? 'text-destructive' : 'text-muted-foreground',
            )}
          >
            {error || hint}
          </p>
        )}
      </div>
    );
  },
);

export default FloatingLabelInput;
