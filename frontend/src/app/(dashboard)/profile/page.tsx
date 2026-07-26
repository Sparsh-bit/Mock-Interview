'use client';

import { useUserProfile, useUpdateProfile } from '@/hooks/useData';
import { useAuth } from '@/hooks/useAuth';
import { useState, useEffect } from 'react';
import { Loader2, Save } from 'lucide-react';
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
    <motion.div initial="hidden" animate="visible" variants={staggerContainer(0.08)} className="mx-auto max-w-4xl space-y-8">
      <motion.div variants={fadeUp}>
        <h1 className="text-2xl font-bold tracking-tight">Your Profile</h1>
        <p className="mt-1.5 text-sm text-muted-foreground">
          Manage your personal details and target company settings for personalized AI interviews.
        </p>
      </motion.div>

      <motion.div variants={fadeUp}>
        <Card className="p-8">
          <form onSubmit={handleSubmit} className="space-y-6">
            {/* Avatar & Email */}
            <div className="flex items-center gap-4 border-b border-border/50 pb-6">
              <div className="flex h-16 w-16 items-center justify-center rounded-full border border-primary/30 bg-primary/15 text-xl font-bold text-primary">
                {user?.email?.[0]?.toUpperCase() || 'U'}
              </div>
              <div>
                <h3 className="text-lg font-bold">{formData.full_name || user?.email?.split('@')[0]}</h3>
                <p className="text-xs text-muted-foreground">{user?.email}</p>
              </div>
            </div>

            <div className="grid gap-6 md:grid-cols-2">
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
            </div>

            <div>
              <label htmlFor="bio" className="mb-2 block text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Bio / Background Summary
              </label>
              <textarea
                id="bio"
                rows={3}
                value={formData.bio}
                onChange={(e) => setFormData({ ...formData, bio: e.target.value })}
                className="ease-out-expo w-full resize-none rounded-lg border border-border bg-surface p-4 text-sm transition-all focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/50"
                placeholder="Brief overview of your technical background, skills, and goals…"
              />
            </div>

            <div className="flex justify-end pt-4">
              <Button type="submit" loading={updateProfile.isPending}>
                <Save className="h-4 w-4" />
                Save Profile Changes
              </Button>
            </div>
          </form>
        </Card>
      </motion.div>
    </motion.div>
  );
}
