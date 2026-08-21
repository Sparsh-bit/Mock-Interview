'use client';

import { AlertTriangle, RefreshCw } from 'lucide-react';
import { useEffect } from 'react';
import Link from 'next/link';

import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';

/**
 * What a dashboard page shows when its render throws.
 *
 * THE OTHER HALF OF THE FREEZE. There was no `error.tsx` anywhere in this app either, and
 * the two absences produce the same symptom from opposite directions. Without a
 * `loading.tsx` a slow navigation looks frozen; without an `error.tsx` a FAILED one is
 * worse than frozen — the error escapes this segment, unmounts the tree above it, and the
 * user is left on a blank page whose only exit is a manual reload. The sidebar is gone at
 * that point, so "the sidebar does not respond" is literally true: there is no sidebar.
 *
 * WHY A ROUTE-GROUP BOUNDARY AND NOT A COMPONENT PER PAGE. Next renders this in place of
 * the failing segment and KEEPS the layout around it, which is the whole point: the sidebar
 * and header survive, so the user can navigate away from a broken page instead of being
 * trapped on it. A try/catch or an in-page error state cannot do that — the layout is above
 * them. And as a group-level file it covers every route in the group, including ones not
 * written yet.
 *
 * `reset()` RE-RENDERS THE SEGMENT WITHOUT A FULL RELOAD. That matters here because most
 * failures on these pages are a transient fetch against a backend that sleeps when idle,
 * so the second attempt usually succeeds — and a reload would throw away the router cache
 * and every warm query in the tab to achieve the same thing.
 *
 * IT SAYS NOTHING ABOUT WHY. `digest` is a hash, not a message, and the real reason is in
 * the server logs where it belongs. Naming a component, a route or an upstream service here
 * tells a visitor about the deployment and tells the user nothing they can act on; the two
 * things they can act on are retry and leave, and both are on screen.
 */
export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // console.error, not console.warn or a toast. This one IS a fault — a page failed to
    // render — which is the case the level exists for, and it is what a candidate can be
    // asked to screenshot. Deliberately not sent anywhere: there is no error reporter wired
    // up in this project, and pretending otherwise by posting to an endpoint that does not
    // exist would swallow the only record that does.
    console.error('[dashboard] a page failed to render', error);
  }, [error]);

  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <Card className="max-w-md p-6 text-center">
        <div className="mx-auto mb-4 flex h-11 w-11 items-center justify-center rounded-full bg-destructive/10">
          <AlertTriangle className="h-5 w-5 text-destructive" />
        </div>
        <h2 className="text-lg font-semibold">This page didn&apos;t load</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Something went wrong while building it. This is usually temporary — try again, or
          go back to your dashboard.
        </p>
        <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
          <Button onClick={reset}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Try again
          </Button>
          <Link
            href="/dashboard"
            className="rounded-xl border border-border/50 px-4 py-2 text-sm font-medium hover:bg-muted/40"
          >
            Back to dashboard
          </Link>
        </div>
        {/* The digest is the only thing that connects this screen to a line in the server
            logs. Shown small rather than hidden, because "send me the code on the screen" is
            a far better support conversation than "describe what happened". */}
        {error.digest && (
          <p className="mt-4 font-mono text-[11px] text-muted-foreground/70">
            ref {error.digest}
          </p>
        )}
      </Card>
    </div>
  );
}
