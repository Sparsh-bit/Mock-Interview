'use client';

import { AlertTriangle, RefreshCw } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';

/**
 * What a page shows when its data could not be loaded.
 *
 * Exists because the alternative kept happening: a query fails, `isLoading` goes
 * false, `data` stays undefined, and the page renders its heading above nothing.
 * That blank space is indistinguishable from "you have no data yet" — the user
 * cannot tell whether the app is broken or empty, and there is nothing to click.
 *
 * One component rather than a block copied into each page, so the wording, the
 * retry affordance and the cold-start hint stay identical everywhere and cannot
 * drift.
 *
 * Always surfaces the server's own message when there is one: the API explains
 * why far better than a generic string can ("This report is not shared", "No
 * recruiter 'x' in the catalogue").
 */
export function DataError({
  title = 'Could not load this',
  error,
  onRetry,
  retrying,
  hint = true,
  children,
}: {
  title?: string;
  error?: unknown;
  onRetry?: () => void;
  retrying?: boolean;
  /** Show the "API may be waking up" note. Off for errors that clearly aren't that. */
  hint?: boolean;
  /** Extra actions — e.g. a link somewhere useful instead of just retrying. */
  children?: React.ReactNode;
}) {
  const message = (error as { message?: string } | null | undefined)?.message?.trim();

  return (
    <Card className="mx-auto mt-10 max-w-xl border-destructive/20 p-8 text-center">
      <AlertTriangle className="mx-auto mb-4 h-9 w-9 text-accent-amber-ink" />
      <h2 className="mb-2 text-lg font-semibold">{title}</h2>
      <p className="text-sm text-muted-foreground">
        {message || 'Something went wrong fetching this data.'}
      </p>
      {/* SAYS WHAT TO DO, NOT WHAT WE RUN ON.
          This used to read "the API may be starting up after being idle", which tells a
          visitor the backend sleeps when unused — that is a hosting tier, a spin-up window
          and a rough traffic level, handed to anyone who sees one slow request. None of it
          helps the person reading it, and all of it helps somebody probing.
          A retry hint is the useful part; where it runs is not. */}
      {hint && (
        <p className="mt-3 text-xs text-muted-foreground">
          This is usually temporary. Wait a moment and try again.
        </p>
      )}
      <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
        {onRetry && (
          <Button variant="secondary" onClick={onRetry} loading={retrying}>
            <RefreshCw className="h-4 w-4" /> Try again
          </Button>
        )}
        {children}
      </div>
    </Card>
  );
}
