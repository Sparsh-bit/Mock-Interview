'use client';

import { useUserProfile, useUpdateProfile } from '@/hooks/useData';
import { useAuth } from '@/hooks/useAuth';
import { useState, useEffect } from 'react';
import { Loader2, Save } from 'lucide-react';
import { motion } from 'framer-motion';
import { toast } from 'sonner';
import { BrandLoader } from '@/components/brand/BrandLoader';
import { Card } from '@/components/ui/card';
import { ResumeUploadCard } from '@/components/resume/ResumeUploadCard';
import FloatingLabelInput from '@/components/lightswind-pro/floating-label-input';
import { Button } from '@/components/ui/button';
import { fadeUp, staggerContainer } from '@/lib/motion';
import { PageHeader } from '@/components/ui/page-header';

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
        <BrandLoader label="Loading your profile" size={56} />
      </div>
    );
  }

  return (
    <motion.div initial="hidden" animate="visible" variants={staggerContainer(0.08)} className="mx-auto max-w-6xl space-y-8">
      <motion.div variants={fadeUp}>
        <PageHeader
          eyebrow="Account"
          title="Your Profile"
          description="Manage your personal details and target company settings for personalized AI interviews."
        />
      </motion.div>

      <motion.div variants={fadeUp}>
        <form onSubmit={handleSubmit}>
          {/* Details on the left, a large picture panel of equal height on the
              right. Stacks on mobile with the picture first, so the identity is
              visible above the fold. */}
          <div className="grid items-stretch gap-6 lg:grid-cols-[1.15fr_1fr]">
            {/* ── Left: the details ─────────────────────────────────────── */}
            {/* THE FORM IS THE PAGE. The identity card beside it is a summary of what the
                form contains, so lighting the form rather than the card puts the light on the
                thing you came here to change. */}
            <Card variant="outline" className="lit order-2 space-y-6 p-5 sm:p-8 lg:order-1">
              <div className="grid gap-6 sm:grid-cols-2">
              <FloatingLabelInput
                  label="Full Name"
                  id="full_name"
                  type="text"
                  value={formData.full_name}
                  onChange={(e) => setFormData({ ...formData, full_name: e.target.value })}
                />

              <FloatingLabelInput
                  label="Target Company"
                  id="target_company"
                  type="text"
                  value={formData.target_company}
                  onChange={(e) => setFormData({ ...formData, target_company: e.target.value })}
                />

              <FloatingLabelInput
                  label="Years of Experience"
                  id="experience_years"
                  type="number"
                  min="0"
                  max="50"
                  value={formData.experience_years}
                  onChange={(e) => setFormData({ ...formData, experience_years: parseInt(e.target.value) || 0 })}
                />

              <FloatingLabelInput
                  label="LinkedIn Profile URL"
                  id="linkedin_url"
                  type="url"
                  value={formData.linkedin_url}
                  onChange={(e) => setFormData({ ...formData, linkedin_url: e.target.value })}
                />

              <div className="sm:col-span-2">
                <FloatingLabelInput
                  label="GitHub Profile URL"
                  id="github_url"
                  type="url"
                  value={formData.github_url}
                  onChange={(e) => setFormData({ ...formData, github_url: e.target.value })}
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
                  className="ease-out-expo w-full resize-none rounded-lg border border-border bg-surface p-4 text-sm transition-[color,background-color,border-color,box-shadow,transform,opacity] focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/50"
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
            <Card className="order-1 flex flex-col p-6 lg:order-2">
              <div className="flex flex-1 flex-col items-center justify-center text-center">
                {/* Large, dominant picture panel — the focal point of this
                    column, matching the reference layout rather than a small
                    avatar chip. */}
                <div className="relative flex aspect-square w-full max-w-[22rem] items-center justify-center overflow-hidden rounded-3xl border border-border bg-gradient-to-br from-primary/10 via-secondary/40 to-accent-violet/10">
                  {formData.avatar_url ? (
                    /* Avatars are user-supplied URLs from arbitrary hosts, and
                       next/image requires every remote host to be allow-listed
                       in next.config — so a plain <img> is correct here. */
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={formData.avatar_url}
                      alt=""
                      className="h-full w-full object-cover"
                      onError={(e) => { e.currentTarget.style.display = 'none'; }}
                    />
                  ) : (
                    /* Default panel artwork, served from /public. Local asset,
                       so next/image would work — but keeping one <img> code path
                       for both cases avoids the two branches drifting apart. */
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src="/profile-illustration.png"
                      alt=""
                      className="h-full w-full object-contain p-6"
                    />
                  )}
                </div>

                {/*
                  WRAPPED, NOT TRUNCATED, and the email is why.

                  Both of these were `w-full truncate`, which is the identity panel of the
                  profile page silently cutting off the two things that identify you. An
                  email is one unbreakable token, so it needs `break-all` rather than
                  `break-words` — `break-words` only breaks BETWEEN words and there are none
                  in "firstname.lastname@somecollege.ac.in", so it would have carried on
                  overflowing. A name can break at spaces, so `break-words` is right there and
                  keeps whole words intact.

                  Truncating an email is not a cosmetic choice here: this is the only place
                  the account's address is shown on this page, and a candidate checking they
                  are signed in as the right person could not read it.
                */}
                <h3 className="mt-6 w-full break-words text-xl font-semibold">
                  {formData.full_name || user?.email?.split('@')[0]}
                </h3>
                <p className="w-full break-all text-xs text-muted-foreground">{user?.email}</p>

                {/* Amber, which means preparation everywhere else in the product — this chip
                    states what the person is working toward. `text-primary` said "primary
                    action", and it is not an action at all. */}
                {formData.target_company && (
                  <span className="mt-3 max-w-full break-words rounded-full border border-accent-amber/30 bg-accent-amber-soft px-3 py-1 text-[11px] font-semibold text-accent-amber-ink">
                    Targeting {formData.target_company}
                  </span>
                )}
              </div>

            </Card>
          </div>
        </form>
      </motion.div>

      {/* Resume — outside the profile form on purpose: uploading is its own
          action that saves immediately, so nesting it inside a form the user has
          to submit separately would imply their file is not stored until they
          press Save. */}
      <motion.div variants={fadeUp}>
        <ResumeUploadCard />
      </motion.div>
    </motion.div>
  );
}
