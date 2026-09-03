'use client';

import type { ReactNode } from 'react';
import { Check } from 'lucide-react';

import { cn } from '@/lib/utils';

/**
 * ONBOARDING FURNITURE — components/onboarding/shared.tsx
 *
 * The wizard is rendered in the public site's `.mk` theme rather than the product's, and that
 * is a deliberate hand-over rather than an inconsistency. Somebody arriving here has just come
 * from the landing page and has never seen the signed-in interface; keeping the cream, the
 * gold and Fraunces for four more screens means the first thing they do inside the product
 * looks like the thing that persuaded them, and the dashboard is where the language changes.
 *
 * Everything here is presentational. The wizard's state, its persistence and its API calls all
 * live in `app/welcome/page.tsx`, so a step can be reordered or dropped without touching a
 * component.
 */

/** A selectable tile. The whole tile is the hit area — a radio you have to hit exactly is the
    single most common reason a step like this feels bad on a phone. */
export function Choice({
  selected,
  onSelect,
  title,
  detail,
  meta,
}: {
  selected: boolean;
  onSelect: () => void;
  title: string;
  detail?: string;
  meta?: string;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={cn(
        'group flex w-full items-start gap-3 rounded-[var(--mk-r-control)] border p-4 text-left transition-all duration-200',
        selected
          ? 'border-[var(--mk-gold)] bg-[var(--mk-gold-soft)] shadow-[0_10px_26px_-18px_rgb(200_146_58/0.8)]'
          : 'border-[var(--mk-border)] bg-[var(--mk-surface)] hover:border-[var(--mk-gold-line)]',
      )}
    >
      <span
        className={cn(
          'mt-0.5 grid h-[18px] w-[18px] shrink-0 place-items-center rounded-full border transition-colors',
          selected
            ? 'border-[var(--mk-gold)] bg-[var(--mk-gold)] text-[#1b150e]'
            : 'border-[var(--mk-border)] bg-transparent text-transparent',
        )}
      >
        <Check className="h-[11px] w-[11px]" strokeWidth={3} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[0.9375rem] font-medium text-[var(--mk-ink)]">{title}</span>
        {detail && (
          <span className="mt-0.5 block text-[var(--mk-micro)] leading-[1.5] text-[var(--mk-muted)]">
            {detail}
          </span>
        )}
      </span>
      {meta && (
        <span className="mk-num shrink-0 text-[var(--mk-micro)] text-[var(--mk-muted)]">
          {meta}
        </span>
      )}
    </button>
  );
}

/**
 * The id the wizard moves focus to on every step change. Exported so the two halves of that
 * behaviour — the heading that receives focus and the effect that sends it — cannot drift
 * apart on a rename.
 */
export const STEP_TITLE_ID = 'welcome-step-title';

/** The heading block every step opens with. */
export function StepHead({
  eyebrow,
  title,
  turn,
  children,
}: {
  eyebrow: string;
  title: string;
  turn?: string;
  children?: ReactNode;
}) {
  return (
    <header className="mb-7">
      <p className="mk-eyebrow">{eyebrow}</p>
      {/*
        * `tabIndex={-1}` makes this programmatically focusable without putting it in the tab
        * order, which is the standard way to land focus on a heading after a view change.
        * `outline-none` because the focus ring here would be a ring around a heading nobody
        * clicked — the announcement is the feedback, not a visible ring.
        */}
      <h1
        id={STEP_TITLE_ID}
        tabIndex={-1}
        className="mt-4 max-w-[20ch] text-balance leading-[1.1] outline-none"
        style={{ fontSize: 'var(--mk-h3)' }}
      >
        {title} {turn && <span className="mk-turn">{turn}</span>}
      </h1>
      {children && (
        <p className="mt-3 max-w-[52ch] text-[0.9375rem] leading-[1.6] text-[var(--mk-body)]">
          {children}
        </p>
      )}
    </header>
  );
}

/** The left rail: where you are, what is left, and what each step is for. */
export function StepRail({
  steps,
  current,
  onJump,
}: {
  steps: readonly { id: string; label: string; hint: string }[];
  current: number;
  onJump: (index: number) => void;
}) {
  return (
    <ol className="space-y-1">
      {steps.map((step, i) => {
        const done = i < current;
        const active = i === current;
        return (
          <li key={step.id}>
            <button
              type="button"
              /* Only backwards. Jumping forward past a step whose answer the next step depends
                 on produces a screen that cannot be filled in, and the visitor has no way to
                 know which earlier answer is missing. */
              onClick={() => done && onJump(i)}
              disabled={!done}
              aria-current={active ? 'step' : undefined}
              className={cn(
                'flex w-full items-center gap-3 rounded-[var(--mk-r-control)] px-3 py-2.5 text-left transition-colors',
                active && 'bg-[var(--mk-surface)] shadow-[var(--mk-shadow-card)]',
                done && 'cursor-pointer hover:bg-[rgb(59_43_28/0.04)]',
                !done && !active && 'opacity-55',
              )}
            >
              <span
                className={cn(
                  'mk-num grid h-6 w-6 shrink-0 place-items-center rounded-full text-[10px] transition-colors',
                  done && 'bg-[var(--mk-gold)] text-[#1b150e]',
                  active && !done && 'bg-[var(--mk-ink)] text-[var(--mk-paper)]',
                  !done && !active && 'border border-[var(--mk-border)] text-[var(--mk-muted)]',
                )}
              >
                {done ? <Check className="h-3 w-3" strokeWidth={3} /> : i + 1}
              </span>
              <span className="min-w-0">
                <span className="block text-[0.875rem] font-medium text-[var(--mk-ink)]">
                  {step.label}
                </span>
                <span className="block truncate text-[var(--mk-micro)] text-[var(--mk-muted)]">
                  {step.hint}
                </span>
              </span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
