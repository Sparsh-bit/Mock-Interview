'use client';

import { AlertTriangle, RefreshCw } from 'lucide-react';
import { useEffect } from 'react';
import Link from 'next/link';

import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';

/**
 * What a live interview shows when its page throws.
 *
 * SEPARATE FROM THE DASHBOARD BOUNDARY ON PURPOSE, because the stakes and the right advice
 * are different. On a dashboard page a crash costs a glance at some numbers. Here the
 * candidate is mid-interview, has spent a credit, and their answers are already on the
 * server — so the one thing this screen must not do is imply the session is gone.
 *
 * WHY "TRY AGAIN" IS THE PRIMARY ACTION AND NOT A LINK AWAY. `reset()` re-renders this
 * segment without a full reload, and the session is resumable by id: the answers are
 * persisted per question as they are submitted, not batched at the end. So retrying almost
 * always drops the candidate back into the room where they left off, and reloading the tab
 * would also work but throws away every warm query to get there.
 *
 * WHAT IT DELIBERATELY DOES NOT SAY. Not "your interview has ended", not "your credit has
 * been used" — neither is known here and both would be alarming and probably wrong. And
 * nothing about which component failed or which service was unreachable: a candidate cannot
 * act on that and it describes the deployment to whoever is reading.
 */
export default function InterviewError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error('[interview] the session page failed to render', error);
  }, [error]);

  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <Card className="max-w-md p-6 text-center">
        <div className="mx-auto mb-4 flex h-11 w-11 items-center justify-center rounded-full bg-destructive/10">
          <AlertTriangle className="h-5 w-5 text-destructive" />
        </div>
        <h2 className="text-lg font-semibold">The interview screen hit a problem</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Your answers so far are saved — they are recorded as you submit each one, not at the
          end. Try again to go back into the room.
        </p>
        <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
          <Button onClick={reset}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Back into the interview
          </Button>
          <Link
            href="/report"
            className="rounded-xl border border-border/50 px-4 py-2 text-sm font-medium hover:bg-muted/40"
          >
            See my reports
          </Link>
        </div>
        {error.digest && (
          <p className="mt-4 font-mono text-[11px] text-muted-foreground/70">
            ref {error.digest}
          </p>
        )}
      </Card>
    </div>
  );
}
