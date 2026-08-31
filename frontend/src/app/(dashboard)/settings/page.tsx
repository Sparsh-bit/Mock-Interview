'use client';

import { useAuth } from '@/hooks/useAuth';
import { useAnalyticsConsent, useSetAnalyticsConsent } from '@/hooks/useAnalyticsConsent';
import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Bell, Lock, Check, BarChart3, FileText } from 'lucide-react';
import Link from 'next/link';
import { toast } from 'sonner';
import { Card } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';
import { fadeUp, staggerContainer } from '@/lib/motion';
import { PageHeader } from '@/components/ui/page-header';

const NOTIFY_KEY = 'interviewos:emailNotifications';

export default function SettingsPage() {
  const { user, resetPassword } = useAuth();
  const [emailNotifications, setEmailNotifications] = useState(true);
  const [resetSent, setResetSent] = useState(false);
  const [loading, setLoading] = useState(false);

  /*
   * THE ANALYTICS CONSENT, READ FROM THE SERVER AND NOT FROM localStorage.
   *
   * Unlike the notification preference two fields up, which is a convenience that may
   * legitimately live in this browser, this is a legal record: §6(4)–(6) makes withdrawal as
   * easy as giving, and a withdrawal that only takes effect on the device it was made on is
   * not a withdrawal. `null` from the query means "never asked", which is not consent, so
   * the switch reads as off.
   */
  const analyticsConsent = useAnalyticsConsent();
  const setAnalyticsConsent = useSetAnalyticsConsent();

  /*
   * Persist the notification preference locally so the choice actually sticks across reloads
   * rather than resetting every visit.
   *
   * WRAPPED, BECAUSE `localStorage` THROWS RATHER THAN RETURNING NULL when a browser is
   * blocking site data — a private window, or the "block cookies" setting people turn on and
   * forget. Unguarded, this threw inside an effect, which React surfaces as a render error:
   * the entire settings page would fail to appear, for a preference that is a convenience.
   * NudgeDeck already wraps its own two calls for exactly this reason and says so; this file
   * was the one that missed the lesson.
   */
  useEffect(() => {
    try {
      const saved = localStorage.getItem(NOTIFY_KEY);
      if (saved !== null) setEmailNotifications(saved === 'true');
    } catch {
      // Blocked site data. The default is "on", which is the safe direction for a preference
      // nobody has expressed — and the page still renders, which is the point.
    }
  }, []);

  const toggleEmailNotifications = () => {
    /*
     * THE WRITE AND THE TOAST MOVED OUT OF THE STATE UPDATER, and this was a real bug rather
     * than a tidy-up.
     *
     * They used to live inside `setEmailNotifications(v => { ... })`. A React state updater
     * must be a PURE function of the previous state: React is allowed to call it more than
     * once for a single update, and with `reactStrictMode: true` in next.config.ts it
     * deliberately does so in development. So every toggle wrote to localStorage twice and
     * fired the toast twice — one tap, two notifications.
     *
     * Computing `next` from the current state here is correct because this is the only writer
     * and it runs from a click, not from a queue of batched updates.
     */
    const next = !emailNotifications;
    setEmailNotifications(next);
    try {
      localStorage.setItem(NOTIFY_KEY, String(next));
    } catch {
      // Blocked site data. The toggle still applies for this visit, which is worth doing —
      // and telling somebody their preference did not save would be more alarming than
      // useful for a setting they can simply set again.
    }
    toast.success(next ? 'Email summaries turned on' : 'Email summaries turned off');
  };


  const handlePasswordReset = async () => {
    if (!user?.email) return;
    setLoading(true);
    try {
      await resetPassword(user.email);
      setResetSent(true);
      toast.success('Password reset link sent to your email!');
    } catch {
      toast.error('Failed to send reset link.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <motion.div initial="hidden" animate="visible" variants={staggerContainer(0.08)} className="mx-auto max-w-4xl space-y-8">
      <motion.div variants={fadeUp}>
        <PageHeader
          eyebrow="Account"
          title="Account Settings"
          description="Manage your account preferences, security options, and notification settings."
        />
      </motion.div>

      <div className="space-y-6">
        {/* Security / Password */}
        <motion.div variants={fadeUp}>
          <Card className="space-y-4 p-6">
            <div className="flex items-center gap-3">
              {/* PROFILE AND SETTINGS ARE DELIBERATELY UNCOLOURED ROUTES — they are the
                  account, not a feature, and there are only six colours to spend (lib/tones).
                  So the section tiles carry the meaning of the SECTION rather than of the
                  page: emerald is "verified / secure", which is what a lock is about. Two
                  identical indigo tiles told the reader these two sections were the same kind
                  of thing, which is the only thing they are not. */}
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent-emerald-soft text-accent-emerald-ink">
                <Lock className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <h3 className="text-base font-semibold">Security & Authentication</h3>
                <p className="text-xs text-muted-foreground">Manage your login security and password</p>
              </div>
            </div>

            {/*
              STACKS BELOW sm, AND THERE WAS NO GAP AT ALL.

              `flex items-center justify-between` with no `gap` and no wrap means the sentence
              on the left and the control on the right are pushed into contact the moment the
              row is narrower than both of them — at 320px this card has 240px and the two
              want about 185px of min-content between them, so the description text ran
              directly into the button with no space. Stacking is the honest fix for a
              label/control pair: full-width rows, readable text, and a button that is a real
              44px tap target rather than a 30px one.
            */}
            <div className="flex flex-col gap-3 border-t border-border/40 pt-4 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
              <div className="min-w-0">
                <p className="text-sm font-semibold">Change Password</p>
                <p className="text-xs text-muted-foreground">Receive a secure link to reset your account password</p>
              </div>
              <button
                onClick={handlePasswordReset}
                disabled={loading || resetSent}
                className="inline-flex min-h-11 shrink-0 items-center justify-center gap-2 rounded-xl border border-border bg-surface px-4 py-2 text-xs font-bold transition-colors hover:bg-secondary disabled:opacity-50"
              >
                {resetSent ? <><Check className="h-3.5 w-3.5 text-accent-emerald-ink" /> Link Sent</> : 'Reset Password'}
              </button>
            </div>
          </Card>
        </motion.div>

        {/* Notifications */}
        <motion.div variants={fadeUp}>
          <Card className="space-y-4 p-6">
            <div className="flex items-center gap-3">
              {/* Amber: notifications are about what reaches you and when — the same
                  "in progress / ongoing" register amber carries elsewhere. */}
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent-amber-soft text-accent-amber-ink">
                <Bell className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <h3 className="text-base font-semibold">Notification Preferences</h3>
                <p className="text-xs text-muted-foreground">Choose when and how we communicate with you</p>
              </div>
            </div>

            {/* Same pair, same fix. The Switch keeps its own size, so it only needs to be
                told not to shrink once the row above it is allowed to wrap. */}
            <div className="flex flex-col gap-3 border-t border-border/40 pt-4 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
              <div className="min-w-0">
                <p className="text-sm font-semibold">Email Session Summaries</p>
                <p className="text-xs text-muted-foreground">Get performance summaries emailed after interview rounds</p>
              </div>
              <div className="shrink-0">
                <Switch checked={emailNotifications} onChange={toggleEmailNotifications} />
              </div>
            </div>
          </Card>
        </motion.div>

        {/* Privacy — the analytics consent */}
        <motion.div variants={fadeUp}>
          <Card className="space-y-4 p-6">
            <div className="flex items-center gap-3">
              {/* Indigo: this is information ABOUT the product's use rather than about the
                  candidate's performance, and indigo is the neutral informational register.
                  Deliberately not emerald — nothing here is "verified" or "secure", and
                  deliberately not amber — nothing here is in progress. */}
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent-indigo-soft text-accent-indigo-ink">
                <BarChart3 className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <h3 className="text-base font-semibold">Privacy</h3>
                <p className="text-xs text-muted-foreground">What we may measure about how you use InterviewOS</p>
              </div>
            </div>

            <div className="flex flex-col gap-3 border-t border-border/40 pt-4 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
              <div className="min-w-0">
                <p className="text-sm font-semibold">Product analytics</p>
                {/* NAMES WHAT IS AND IS NOT SENT. "Help us improve" is the wording this is
                    deliberately not: §6 asks for consent that is specific, and a person
                    cannot give specific consent to a euphemism. */}
                <p className="text-xs text-muted-foreground">
                  Which parts of the product you use — signing up, uploading a resume,
                  starting and finishing interviews, buying. Never your resume, your answers
                  or your scores. Turning this off stops it immediately and clears what is
                  stored in this browser.
                </p>
              </div>
              <div className="shrink-0">
                <Switch
                  checked={analyticsConsent.data === true}
                  onChange={() => {
                    const next = analyticsConsent.data !== true;
                    setAnalyticsConsent.mutate(next, {
                      onSuccess: () =>
                        toast.success(
                          next
                            ? 'Product analytics is on. You can turn it off here at any time.'
                            : 'Product analytics is off. Nothing further will be measured.'
                        ),
                      onError: () =>
                        toast.error('Could not save that. Your choice has not been changed.'),
                    });
                  }}
                />
              </div>
            </div>
          </Card>
        </motion.div>

        {/* THE "SYSTEM INFORMATION" CARD IS GONE, and the API endpoint is why.

            It printed the backend's full host on the settings page of every candidate who ever
            opened it. That one line hands a stranger the host, the platform and — from the URL
            shape — the hosting tier: a starting point for probing, and it tells the reader more
            about the deployment than about their own account. Removed on request, and it should
            never have shipped to a candidate. The URL is deliberately not repeated here.

            The account id and email went with it rather than being kept in a slimmer card. The
            email is already in the header and on the profile page, and a raw UUID is not
            something a candidate can act on — it was there because the card was built for
            debugging and then left on a page users see. A support flow that genuinely needs an
            id should surface it deliberately, not as a by-product of an environment readout.

            `apiEndpoint` was deleted with it rather than left unused: a variable holding that
            value is an invitation to render it again.

            Earlier in this session the same class of leak was removed from the data-error
            component, which disclosed a hosting tier and a spin-up window, and from two
            pricing-page toasts that named the payment provider and admitted the integration was
            unfinished. This was the last one rendering on a user-facing screen. */}
        {/* ── LEGAL, AND WHY IT IS HERE RATHER THAN ONLY IN THE FOOTER ─────────
            The footer is a landing-page thing. Somebody who has already paid lives inside
            the dashboard and does not scroll past a marketing page again — so "how do I get
            my money back" and "who do I complain to" have to be findable from the account
            area, or the pages are orphans for exactly the people most likely to need them.

            UNCOLOURED TILE, deliberately. docs/DESIGN-LANGUAGE.md allows six colours and
            each binds to one meaning; there is no meaning here worth spending one on, and a
            seventh colour would dilute the six that carry information. */}
        <motion.div variants={fadeUp}>
          <Card className="space-y-4 p-6">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-muted text-muted-foreground">
                <FileText className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <h3 className="text-base font-semibold">Policies & complaints</h3>
                <p className="text-xs text-muted-foreground">
                  Terms, refunds, your data, and who to contact when something is wrong
                </p>
              </div>
            </div>

            <nav className="flex flex-wrap gap-x-6 gap-y-2 border-t border-border/40 pt-4 text-sm">
              <Link href="/terms" className="text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">
                Terms of Service
              </Link>
              <Link href="/refund" className="text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">
                Refunds & cancellation
              </Link>
              <Link href="/privacy" className="text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">
                Your data
              </Link>
              <Link href="/grievance" className="text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">
                Complaints & grievances
              </Link>
            </nav>
          </Card>
        </motion.div>
      </div>
    </motion.div>
  );
}
