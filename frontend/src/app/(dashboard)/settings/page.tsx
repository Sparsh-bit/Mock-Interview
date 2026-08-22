'use client';

import { useAuth } from '@/hooks/useAuth';
import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Bell, Lock, Check } from 'lucide-react';
import { toast } from 'sonner';
import { Card } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';
import { fadeUp, staggerContainer } from '@/lib/motion';
import { PageHeader } from '@/components/ui/page-header';

export const runtime = 'edge';
const NOTIFY_KEY = 'interviewos:emailNotifications';

export default function SettingsPage() {
  const { user, resetPassword } = useAuth();
  const [emailNotifications, setEmailNotifications] = useState(true);
  const [resetSent, setResetSent] = useState(false);
  const [loading, setLoading] = useState(false);

  // Persist the notification preference locally so the choice actually sticks
  // across reloads (rather than resetting every visit).
  useEffect(() => {
    const saved = localStorage.getItem(NOTIFY_KEY);
    if (saved !== null) setEmailNotifications(saved === 'true');
  }, []);

  const toggleEmailNotifications = () => {
    setEmailNotifications((v) => {
      const next = !v;
      localStorage.setItem(NOTIFY_KEY, String(next));
      toast.success(next ? 'Email summaries turned on' : 'Email summaries turned off');
      return next;
    });
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
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
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
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
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
      </div>
    </motion.div>
  );
}
