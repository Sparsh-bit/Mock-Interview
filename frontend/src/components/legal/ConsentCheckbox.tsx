'use client';

import { forwardRef } from 'react';

/**
 * One consent question.
 *
 * DELIBERATELY UNCONTROLLED AND `forwardRef`, so it drops straight into react-hook-form's
 * `register()` without a Controller. That matters more than it looks: a Controller with a
 * `defaultValue` is how a checkbox quietly acquires a default, and a consent control that
 * starts ticked is the one thing DPDP §6 names explicitly as not consent. There is nowhere
 * here for a default to live.
 *
 * The error is rendered rather than only announced, and the label is clickable — a tick box
 * whose label is not a target is a control people miss and then blame the form for.
 */
const ConsentCheckbox = forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement> & { error?: string; children: React.ReactNode }
>(function ConsentCheckbox({ error, children, id, ...props }, ref) {
  return (
    <div>
      <label htmlFor={id} className="flex cursor-pointer items-start gap-3">
        <input
          ref={ref}
          id={id}
          type="checkbox"
          // 20px, not the browser default 13px. This is a legal control on a phone.
          className="mt-0.5 h-5 w-5 shrink-0 rounded border-border accent-primary"
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${id}-error` : undefined}
          {...props}
        />
        <span className="leading-snug text-muted-foreground">{children}</span>
      </label>
      {error && (
        <p id={`${id}-error`} role="alert" className="ml-8 mt-1 text-xs text-accent-rose-ink">
          {error}
        </p>
      )}
    </div>
  );
});

export default ConsentCheckbox;
