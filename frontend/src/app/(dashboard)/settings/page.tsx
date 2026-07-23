'use client';

import { useAuth } from '@/hooks/useAuth';
import { useState } from 'react';
import { motion } from 'framer-motion';
import { Bell, Lock, Shield, Check } from 'lucide-react';
import { toast } from 'sonner';
import { Card } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';
import { fadeUp, staggerContainer } from '@/lib/motion';

export default function SettingsPage() {
  const { user, resetPassword } = useAuth();
  const [emailNotifications, setEmailNotifications] = useState(true);
  const [resetSent, setResetSent] = useState(false);
  const [loading, setLoading] = useState(false);

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
        <h1 className="text-2xl font-bold tracking-tight">Account Settings</h1>
        <p className="mt-1.5 text-sm text-muted-foreground">
          Manage your account preferences, security options, and notification settings.
        </p>
      </motion.div>

      <div className="space-y-6">
        {/* Security / Password */}
        <motion.div variants={fadeUp}>
          <Card className="space-y-4 p-6">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
                <Lock className="h-5 w-5" />
              </div>
              <div>
                <h3 className="text-base font-bold">Security & Authentication</h3>
                <p className="text-xs text-muted-foreground">Manage your login security and password</p>
              </div>
            </div>

            <div className="flex items-center justify-between border-t border-border/40 pt-4">
              <div>
                <p className="text-sm font-semibold">Change Password</p>
                <p className="text-xs text-muted-foreground">Receive a secure link to reset your account password</p>
              </div>
              <button
                onClick={handlePasswordReset}
                disabled={loading || resetSent}
                className="inline-flex items-center gap-2 rounded-xl border border-border bg-surface px-4 py-2 text-xs font-bold transition-colors hover:bg-secondary disabled:opacity-50"
              >
                {resetSent ? <><Check className="h-3.5 w-3.5 text-emerald-400" /> Link Sent</> : 'Reset Password'}
              </button>
            </div>
          </Card>
        </motion.div>

        {/* Notifications */}
        <motion.div variants={fadeUp}>
          <Card className="space-y-4 p-6">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
                <Bell className="h-5 w-5" />
              </div>
              <div>
                <h3 className="text-base font-bold">Notification Preferences</h3>
                <p className="text-xs text-muted-foreground">Choose when and how we communicate with you</p>
              </div>
            </div>

            <div className="flex items-center justify-between border-t border-border/40 pt-4">
              <div>
                <p className="text-sm font-semibold">Email Session Summaries</p>
                <p className="text-xs text-muted-foreground">Get performance summaries emailed after interview rounds</p>
              </div>
              <Switch
                checked={emailNotifications}
                onChange={() => {
                  setEmailNotifications((v) => !v);
                  toast.success('Notification settings saved');
                }}
              />
            </div>
          </Card>
        </motion.div>

        {/* Environment Info */}
        <motion.div variants={fadeUp}>
          <Card className="space-y-2 p-6">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-500/10 text-emerald-400">
                <Shield className="h-5 w-5" />
              </div>
              <div>
                <h3 className="text-base font-bold">System Information</h3>
                <p className="text-xs text-muted-foreground">Connected API backend environment</p>
              </div>
            </div>
            <div className="space-y-1 border-t border-border/40 pt-4 text-xs text-muted-foreground">
              <p><strong>Environment:</strong> Production / Local Hybrid</p>
              <p><strong>API Endpoint:</strong> http://localhost:8000</p>
              <p><strong>Account ID:</strong> {user?.id}</p>
            </div>
          </Card>
        </motion.div>
      </div>
    </motion.div>
  );
}
