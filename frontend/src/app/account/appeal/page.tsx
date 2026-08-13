'use client';

import { useState } from 'react';
import Link from 'next/link';
import { Loader2, ShieldAlert } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { useAppeal, useBalance } from '@/hooks/useBilling';

export const runtime = 'edge';

/**
 * Requesting a review of a suspended account — app/account/appeal/page.tsx
 *
 * THIS PAGE IS WHY AN AUTOMATED BAN IS DEFENSIBLE. The detector keys on one account being
 * live on two networks at once, which is a real sharing signal and is also what a phone
 * handing off from mobile data to campus wi-fi can look like. It has four dampeners and
 * will still be wrong sometimes, and when it is wrong it will be wrong about somebody who
 * has paid. Without a route back, their only recourse is a support address nobody reads.
 *
 * TOP-LEVEL, NOT UNDER (dashboard). That layout is behind the auth gate that the ban itself
 * blocks, so putting the appeal inside it would produce exactly the loop this page exists
 * to prevent: suspended, therefore cannot reach the page that lets you say so. The two
 * matching exemptions are in `_BAN_EXEMPT_SUFFIXES` in core/security.py.
 */
export default function AppealPage() {
  const { data, isLoading } = useBalance();
  const appeal = useAppeal();
  const [message, setMessage] = useState('');

  const submit = () => {
    if (message.trim().length < 10) {
      toast.error('Please say a little more — at least a sentence.');
      return;
    }
    appeal.mutate(message.trim(), {
      onSuccess: () => toast.success('Review requested. We will get back to you.'),
      onError: () => toast.error('Could not send that. Please try again in a moment.'),
    });
  };

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-hidden />
      </div>
    );
  }

  // Not banned — either it was lifted while they were reading, or they navigated here by
  // hand. Telling them the good news beats showing a form that would do nothing.
  if (data && !data.is_banned) {
    return (
      <div className="mx-auto max-w-lg px-6 py-20 text-center">
        <h1 className="text-lg font-semibold text-foreground">Your account is active</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          There is nothing to appeal. You can carry on where you left off.
        </p>
        <Link href="/dashboard" className="mt-6 inline-block text-sm font-medium text-primary hover:underline">
          Back to dashboard
        </Link>
      </div>
    );
  }

  const alreadySent = !!data?.appeal_submitted;

  return (
    <div className="min-h-screen bg-background paper-grain">
      <div className="mx-auto max-w-lg px-6 py-16">
        <Card variant="elevated" padding="lg" className="space-y-5">
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-full bg-amber-500/10">
              <ShieldAlert className="h-5 w-5 text-amber-500" aria-hidden />
            </span>
            <div>
              <h1 className="text-base font-semibold text-foreground">Account suspended</h1>
              <p className="text-xs text-muted-foreground">
                Signed-in accounts are for one person.
              </p>
            </div>
          </div>

          {/* The actual reason, verbatim from the server. A suspension that will not say
              what triggered it is impossible to argue with, which is the complaint people
              have about every system that does this. */}
          {data?.ban_reason && (
            <p className="rounded-lg border border-border/60 bg-surface px-3.5 py-2.5 text-xs leading-relaxed text-muted-foreground">
              {data.ban_reason}
            </p>
          )}

          {alreadySent ? (
            <div className="space-y-2">
              <p className="text-sm text-foreground">Your request has been received.</p>
              <p className="text-xs text-muted-foreground">
                Someone will look at it and your access will be restored if this was a
                mistake. You do not need to send it again.
              </p>
            </div>
          ) : (
            <>
              <div className="space-y-2">
                <label htmlFor="appeal" className="text-sm font-medium text-foreground">
                  What happened?
                </label>
                {/* Prompts for the two things that actually distinguish a false positive:
                    a network change, and a second device of their own. Somebody who has
                    done nothing wrong often cannot guess what we need to hear. */}
                <p className="text-xs text-muted-foreground">
                  If you switched between mobile data and wi-fi, or use a phone and a laptop
                  together, say so — that is the most common reason this happens by mistake.
                </p>
                <textarea
                  id="appeal"
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  rows={5}
                  maxLength={1000}
                  placeholder="I was on my phone on college wi-fi and switched to mobile data…"
                  className="w-full resize-none rounded-xl border border-border/60 bg-surface-elevated p-3 text-sm leading-relaxed focus:border-primary/40 focus:outline-none"
                />
              </div>

              <Button className="w-full" onClick={submit} disabled={appeal.isPending}>
                {appeal.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  'Request a review'
                )}
              </Button>
            </>
          )}

          <p className="text-[11px] leading-relaxed text-muted-foreground">
            Anything you have bought stays on your account and does not expire while this is
            being reviewed.
          </p>
        </Card>
      </div>
    </div>
  );
}
