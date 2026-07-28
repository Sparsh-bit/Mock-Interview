'use client';

import { useUserProfile, useUpdateProfile } from '@/hooks/useData';
import { useAuth } from '@/hooks/useAuth';
import { useState, useEffect } from 'react';
import { Image as ImageIcon, Loader2, Save } from 'lucide-react';
import { motion } from 'framer-motion';
import { toast } from 'sonner';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { fadeUp, staggerContainer } from '@/lib/motion';

export const runtime = 'edge';
export default function ProfilePage() {
  const { user } = useAuth();
  const { data: profile, isLoading } = useUserProfile();
  const updateProfile = useUpdateProfile();

  const [formData, setFormData] = useState({
    full_name: '',
    bio: '',
    target_company: '',
    experience_years: 0,
    linkedin_url: '',
    github_url: '',
    avatar_url: '',
  });

  useEffect(() => {
    if (profile) {
      setFormData({
        full_name: profile.full_name || '',
        bio: profile.bio || '',
        target_company: profile.target_company || '',
        experience_years: profile.experience_years || 0,
        linkedin_url: profile.linkedin_url || '',
        github_url: profile.github_url || '',
        avatar_url: profile.avatar_url || '',
      });
    }
  }, [profile]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    updateProfile.mutate(formData, {
      onSuccess: () => {
        toast.success('Profile updated successfully!');
      },
      onError: (err: Error) => {
        toast.error(err.message || 'Failed to update profile.');
      },
    });
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <motion.div initial="hidden" animate="visible" variants={staggerContainer(0.08)} className="mx-auto max-w-6xl space-y-8">
      <motion.div variants={fadeUp}>
        <h1 className="text-2xl font-bold tracking-tight">Your Profile</h1>
        <p className="mt-1.5 text-sm text-muted-foreground">
          Manage your personal details and target company settings for personalized AI interviews.
        </p>
      </motion.div>

      <motion.div variants={fadeUp}>
        <form onSubmit={handleSubmit}>
          {/* Details on the left, picture panel on the right. Stacks on mobile
              with the picture first, so the identity is visible above the fold. */}
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
            {/* ── Left: the details ─────────────────────────────────────── */}
            <Card className="order-2 space-y-6 p-8 lg:order-1">
              <div className="grid gap-6 sm:grid-cols-2">
              <div>
                <label htmlFor="full_name" className="mb-2 block text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  Full Name
                </label>
                <Input
                  id="full_name"
                  type="text"
                  value={formData.full_name}
                  onChange={(e) => setFormData({ ...formData, full_name: e.target.value })}
                  placeholder="e.g. Rahul Sharma"
                />
              </div>

              <div>
                <label htmlFor="target_company" className="mb-2 block text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  Target Company
                </label>
                <Input
                  id="target_company"
                  type="text"
                  value={formData.target_company}
                  onChange={(e) => setFormData({ ...formData, target_company: e.target.value })}
                  placeholder="e.g. Cognizant, TCS"
                />
              </div>

              <div>
                <label htmlFor="experience_years" className="mb-2 block text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  Years of Experience
                </label>
                <Input
                  id="experience_years"
                  type="number"
                  min="0"
                  max="50"
                  value={formData.experience_years}
                  onChange={(e) => setFormData({ ...formData, experience_years: parseInt(e.target.value) || 0 })}
                />
              </div>

              <div>
                <label htmlFor="linkedin_url" className="mb-2 block text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  LinkedIn Profile URL
                </label>
                <Input
                  id="linkedin_url"
                  type="url"
                  value={formData.linkedin_url}
                  onChange={(e) => setFormData({ ...formData, linkedin_url: e.target.value })}
                  placeholder="https://linkedin.com/in/…"
                />
              </div>

              <div className="sm:col-span-2">
                <label htmlFor="github_url" className="mb-2 block text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  GitHub Profile URL
                </label>
                <Input
                  id="github_url"
                  type="url"
                  value={formData.github_url}
                  onChange={(e) => setFormData({ ...formData, github_url: e.target.value })}
                  placeholder="https://github.com/…"
                />
              </div>
              </div>

              <div>
                <label htmlFor="bio" className="mb-2 block text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  Bio / Background Summary
                </label>
                <textarea
                  id="bio"
                  rows={4}
                  value={formData.bio}
                  onChange={(e) => setFormData({ ...formData, bio: e.target.value })}
                  className="ease-out-expo w-full resize-none rounded-lg border border-border bg-surface p-4 text-sm transition-all focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/50"
                  placeholder="Brief overview of your technical background, skills, and goals…"
                />
                <p className="mt-2 text-[11px] text-muted-foreground">
                  The interviewer reads this to tailor its questions to your background.
                </p>
              </div>

              <div className="flex justify-end border-t border-border/50 pt-6">
                <Button type="submit" loading={updateProfile.isPending}>
                  <Save className="h-4 w-4" />
                  Save Profile Changes
                </Button>
              </div>
            </Card>

            {/* ── Right: the picture ────────────────────────────────────── */}
            <Card className="order-1 h-fit p-6 lg:order-2 lg:sticky lg:top-6">
              <div className="flex flex-col items-center text-center">
                <div className="relative flex h-40 w-40 items-center justify-center overflow-hidden rounded-2xl border border-border bg-gradient-to-br from-primary/10 to-accent-violet/10">
                  {formData.avatar_url ? (
                    // eslint-disable-next-line @next/next/no-img-element -- remote
                    // avatar of arbitrary origin; next/image would need every
                    // host allow-listed in next.config.
                    <img
                      src={formData.avatar_url}
                      alt=""
                      className="h-full w-full object-cover"
                      onError={(e) => { e.currentTarget.style.display = 'none'; }}
                    />
                  ) : (
                    <span className="text-5xl font-bold text-primary">
                      {(formData.full_name || user?.email || 'U')[0]?.toUpperCase()}
                    </span>
                  )}
                </div>

                <h3 className="mt-4 w-full truncate text-lg font-bold">
                  {formData.full_name || user?.email?.split('@')[0]}
                </h3>
                <p className="w-full truncate text-xs text-muted-foreground">{user?.email}</p>

                {formData.target_company && (
                  <span className="mt-3 rounded-full border border-primary/30 bg-primary/10 px-3 py-1 text-[11px] font-semibold text-primary">
                    Targeting {formData.target_company}
                  </span>
                )}
              </div>

              <div className="mt-6 border-t border-border/50 pt-5">
                <label htmlFor="avatar_url" className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  <ImageIcon className="h-3.5 w-3.5" /> Picture URL
                </label>
                <Input
                  id="avatar_url"
                  type="url"
                  value={formData.avatar_url}
                  onChange={(e) => setFormData({ ...formData, avatar_url: e.target.value })}
                  placeholder="https://…/photo.jpg"
                />
                <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
                  Paste a link to your photo. Direct file upload isn&apos;t wired up yet.
                </p>
              </div>
            </Card>
          </div>
        </form>
      </motion.div>
    </motion.div>
  );
}
