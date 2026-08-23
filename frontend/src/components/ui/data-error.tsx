'use client';

import { AlertTriangle, LifeBuoy, RefreshCw, ShieldAlert } from 'lucide-react';
import Link from 'next/link';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { ApiError } from '@/lib/api/errors';

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

  /*
   * A SUSPENDED ACCOUNT IS NOT A FAILED FETCH, AND MUST NOT BE SHOWN AS ONE.
   *
   * Reported as the account "not opening" with no way forward. The suspension arrived here as
   * an ordinary error, so this card said "this is usually temporary, wait a moment and try
   * again" — which is false, a suspension does not lapse in a moment — offered a Try again
   * button that could never succeed, and gave no link to the appeal even though the server's
   * own message tells the user to go and request a review. The appeal endpoint was reachable
   * the whole time (see _BAN_EXEMPT_SUFFIXES); nothing on screen pointed at it.
   *
   * HANDLED HERE RATHER THAN AT EACH CALL SITE. A suspension blocks nearly every endpoint, so
   * whichever page the candidate happens to land on renders it. Fixing the dashboard alone
   * would have left the same dead end on tracks, reports, analytics and the rest — and the
   * next page added would inherit it. One component already stands in for all of them.
   */
  const suspended = error instanceof ApiError && error.isAccountSuspended;
  const appealable = error instanceof ApiError && error.isAppealable;

  return (
    <Card className="mx-auto mt-10 max-w-xl border-destructive/20 p-8 text-center">
      {suspended ? (
        <ShieldAlert className="mx-auto mb-4 h-9 w-9 text-accent-amber-ink" />
      ) : (
        <AlertTriangle className="mx-auto mb-4 h-9 w-9 text-accent-amber-ink" />
      )}
      <h2 className="mb-2 text-lg font-semibold">
        {suspended ? 'This account is suspended' : title}
      </h2>
      <p className="text-sm text-muted-foreground">
        {message || 'Something went wrong fetching this data.'}
      </p>
      {/* WHAT HAPPENS NEXT, IN PLAIN TERMS. A suspension lifts on its own after a cooling-off
          period, and saying so is the single most useful sentence on this screen: it is the
          difference between "I have lost my account" and "I get back in tomorrow". Kept vague
          about the exact window on purpose — it escalates for repeats, so naming a figure
          here would be wrong for exactly the accounts most likely to read it twice. */}
      {suspended && (
        <p className="mt-3 text-sm text-muted-foreground">
          Access is paused because the account was used from two networks at the same time.
          It unlocks by itself after a short review period — signing in again sooner will not
          change that, so there is nothing you need to do.
        </p>
      )}
      {/* SAYS WHAT TO DO, NOT WHAT WE RUN ON.
          This used to read "the API may be starting up after being idle", which tells a
          visitor the backend sleeps when unused — that is a hosting tier, a spin-up window
          and a rough traffic level, handed to anyone who sees one slow request. None of it
          helps the person reading it, and all of it helps somebody probing.
          A retry hint is the useful part; where it runs is not. */}
      {/* NEVER ON A SUSPENSION. "Usually temporary, wait a moment and try again" is true of a
          cold backend and false of a suspended account, and telling somebody to retry
          something that cannot succeed is how a dead end gets built. */}
      {hint && !suspended && (
        <p className="mt-3 text-xs text-muted-foreground">
          This is usually temporary. Wait a moment and try again.
        </p>
      )}
      <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
        {/* THE ROUTE OUT IS THE PRIMARY ACTION, and Try again is not offered at all — it
            cannot work, and a button that never works reads as the product being broken
            rather than as the account being paused. */}
        {suspended ? (
          appealable && (
            <Link
              href="/account/appeal"
              className="inline-flex items-center gap-2 rounded-xl bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
            >
              <LifeBuoy className="h-4 w-4" aria-hidden />
              Request a review
            </Link>
          )
        ) : (
          onRetry && (
            <Button variant="secondary" onClick={onRetry} loading={retrying}>
              <RefreshCw className="h-4 w-4" /> Try again
            </Button>
          )
        )}
        {children}
      </div>
    </Card>
  );
}
