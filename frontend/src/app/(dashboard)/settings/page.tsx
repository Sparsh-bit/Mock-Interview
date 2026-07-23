'use client';

import { useAuth } from '@/hooks/useAuth';
import { useState } from 'react';
import { Bell, Key, Lock, Moon, Shield, Sliders, Check } from 'lucide-react';
import { toast } from 'sonner';

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
    <div className="max-w-4xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold">Account Settings</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Manage your account preferences, security options, and notification settings.
        </p>
      </div>

      <div className="space-y-6">
        {/* Security / Password */}
        <div className="glass rounded-2xl border border-border/50 p-6 space-y-4">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-xl bg-primary/10 flex items-center justify-center text-primary">
              <Lock className="h-5 w-5" />
            </div>
            <div>
              <h3 className="font-bold text-base">Security & Authentication</h3>
              <p className="text-xs text-muted-foreground">Manage your login security and password</p>
            </div>
          </div>

          <div className="pt-4 border-t border-border/40 flex items-center justify-between">
            <div>
              <p className="text-sm font-semibold">Change Password</p>
              <p className="text-xs text-muted-foreground">Receive a secure link to reset your account password</p>
            </div>
            <button
              onClick={handlePasswordReset}
              disabled={loading || resetSent}
              className="inline-flex items-center gap-2 rounded-xl bg-surface border border-border px-4 py-2 text-xs font-bold hover:bg-accent transition-colors disabled:opacity-50"
            >
              {resetSent ? <><Check className="h-3.5 w-3.5 text-emerald-400" /> Link Sent</> : 'Reset Password'}
            </button>
          </div>
        </div>

        {/* Notifications */}
        <div className="glass rounded-2xl border border-border/50 p-6 space-y-4">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-xl bg-blue-500/10 flex items-center justify-center text-blue-400">
              <Bell className="h-5 w-5" />
            </div>
            <div>
              <h3 className="font-bold text-base">Notification Preferences</h3>
              <p className="text-xs text-muted-foreground">Choose when and how we communicate with you</p>
            </div>
          </div>

          <div className="pt-4 border-t border-border/40 flex items-center justify-between">
            <div>
              <p className="text-sm font-semibold">Email Session Summaries</p>
              <p className="text-xs text-muted-foreground">Get performance summaries emailed after interview rounds</p>
            </div>
            <button
              onClick={() => {
                setEmailNotifications((v) => !v);
                toast.success('Notification settings saved');
              }}
              className={`w-12 h-6 rounded-full transition-colors relative p-0.5 ${
                emailNotifications ? 'bg-primary' : 'bg-muted'
              }`}
            >
              <div
                className={`h-5 w-5 rounded-full bg-white transition-transform ${
                  emailNotifications ? 'translate-x-6' : 'translate-x-0'
                }`}
              />
            </button>
          </div>
        </div>

        {/* Environment Info */}
        <div className="glass rounded-2xl border border-border/50 p-6 space-y-2">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-xl bg-emerald-500/10 flex items-center justify-center text-emerald-400">
              <Shield className="h-5 w-5" />
            </div>
            <div>
              <h3 className="font-bold text-base">System Information</h3>
              <p className="text-xs text-muted-foreground">Connected API backend environment</p>
            </div>
          </div>
          <div className="pt-4 border-t border-border/40 text-xs space-y-1 text-muted-foreground">
            <p><strong>Environment:</strong> Production / Local Hybrid</p>
            <p><strong>API Endpoint:</strong> http://localhost:8000</p>
            <p><strong>Account ID:</strong> {user?.id}</p>
          </div>
        </div>
      </div>
    </div>
  );
}
