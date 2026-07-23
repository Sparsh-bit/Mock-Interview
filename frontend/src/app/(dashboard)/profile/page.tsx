'use client';

import { useUserProfile, useUpdateProfile } from '@/hooks/useData';
import { useAuth } from '@/hooks/useAuth';
import { useState, useEffect } from 'react';
import { Loader2, Save, User, Building, Briefcase, Linkedin, Github, Check } from 'lucide-react';
import { toast } from 'sonner';

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
      onError: (err: any) => {
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
    <div className="max-w-4xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold">Your Profile</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Manage your personal details and target company settings for personalized AI interviews.
        </p>
      </div>

      <div className="glass rounded-2xl border border-border/50 p-8">
        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Avatar & Email */}
          <div className="flex items-center gap-4 pb-6 border-b border-border/50">
            <div className="h-16 w-16 rounded-full bg-primary/20 flex items-center justify-center text-xl font-bold text-primary border border-primary/30">
              {user?.email?.[0]?.toUpperCase() || 'U'}
            </div>
            <div>
              <h3 className="font-bold text-lg">{formData.full_name || user?.email?.split('@')[0]}</h3>
              <p className="text-xs text-muted-foreground">{user?.email}</p>
            </div>
          </div>

          <div className="grid gap-6 md:grid-cols-2">
            <div>
              <label htmlFor="full_name" className="block text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">
                Full Name
              </label>
              <input
                id="full_name"
                type="text"
                value={formData.full_name}
                onChange={(e) => setFormData({ ...formData, full_name: e.target.value })}
                className="w-full rounded-xl border border-border/60 bg-surface px-4 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                placeholder="e.g. Rahul Sharma"
              />
            </div>

            <div>
              <label htmlFor="target_company" className="block text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">
                Target Company
              </label>
              <input
                id="target_company"
                type="text"
                value={formData.target_company}
                onChange={(e) => setFormData({ ...formData, target_company: e.target.value })}
                className="w-full rounded-xl border border-border/60 bg-surface px-4 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                placeholder="e.g. Cognizant, TCS"
              />
            </div>

            <div>
              <label htmlFor="experience_years" className="block text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">
                Years of Experience
              </label>
              <input
                id="experience_years"
                type="number"
                min="0"
                max="50"
                value={formData.experience_years}
                onChange={(e) => setFormData({ ...formData, experience_years: parseInt(e.target.value) || 0 })}
                className="w-full rounded-xl border border-border/60 bg-surface px-4 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </div>

            <div>
              <label htmlFor="linkedin_url" className="block text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">
                LinkedIn Profile URL
              </label>
              <input
                id="linkedin_url"
                type="url"
                value={formData.linkedin_url}
                onChange={(e) => setFormData({ ...formData, linkedin_url: e.target.value })}
                className="w-full rounded-xl border border-border/60 bg-surface px-4 py-2.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                placeholder="https://linkedin.com/in/..."
              />
            </div>
          </div>

          <div>
            <label htmlFor="bio" className="block text-xs font-semibold uppercase tracking-wider text-muted-foreground mb-2">
              Bio / Background Summary
            </label>
            <textarea
              id="bio"
              rows={3}
              value={formData.bio}
              onChange={(e) => setFormData({ ...formData, bio: e.target.value })}
              className="w-full rounded-xl border border-border/60 bg-surface p-4 text-sm resize-none focus:outline-none focus:ring-1 focus:ring-primary"
              placeholder="Brief overview of your technical background, skills, and goals..."
            />
          </div>

          <div className="pt-4 flex justify-end">
            <button
              type="submit"
              disabled={updateProfile.isPending}
              className="inline-flex items-center gap-2 rounded-xl bg-primary px-6 py-3 text-sm font-bold text-primary-foreground hover:bg-primary/90 transition-all disabled:opacity-50 shadow-glow"
            >
              {updateProfile.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              Save Profile Changes
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
