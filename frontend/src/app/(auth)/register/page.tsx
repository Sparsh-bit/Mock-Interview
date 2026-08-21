'use client';

import { motion } from 'framer-motion';
import Link from 'next/link';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { passwordRules } from '@/lib/auth/password';
import { Eye, EyeOff, CheckCircle2 } from 'lucide-react';
import { useAuth } from '@/hooks/useAuth';
import { getBrowserApiClient } from '@/lib/api';
import { toast } from 'sonner';
import { Card } from '@/components/ui/card';
import FloatingLabelInput from '@/components/lightswind-pro/floating-label-input';
import PasswordStrength from '@/components/lightswind-pro/password-strength';
import { Button } from '@/components/ui/button';
import { fadeUp, scalePop, staggerContainer } from '@/lib/motion';

export const runtime = 'edge';
/*
 * The password rules come from lib/auth/password.ts rather than living here.
 *
 * They used to be written out in this file, which was fine while this was the only form that
 * set a password. It stopped being fine when the reset-completion form was added: two copies
 * of a rule drift, and the drift here has a direction that matters. If reset were laxer than
 * registration, "forgot password" would be a documented route to a weaker password than this
 * form accepts — a bypass rather than an inconsistency. One definition, imported by both.
 */
const schema = z.object({
  full_name: z.string().min(2, 'Name must be at least 2 characters'),
  email: z.string().email('Enter a valid email address'),
  password: passwordRules,
  confirmPassword: z.string(),
}).refine((data) => data.password === data.confirmPassword, {
  message: "Passwords don't match",
  path: ['confirmPassword'],
});

type FormData = z.infer<typeof schema>;

const PERKS = [
  'Cognizant Java FSE mock interview, grounded in real past questions',
  'Voice-first rounds with live cross-questions',
  'Detailed performance report at the end',
  'Coding round with a real compiler',
];

export default function RegisterPage() {
  const [showPassword, setShowPassword] = useState(false);
  const [done, setDone] = useState(false);
  const { signUp } = useAuth();

  const { register, handleSubmit, watch, formState: { errors, isSubmitting } } = useForm<FormData>({
    resolver: zodResolver(schema),
  });
  // Watched so the strength meter updates as they type. Scoped to this one field rather than
  // watch() with no argument, which re-renders the whole form on every keystroke of every input.
  const passwordValue = watch('password');

  const onSubmit = async (data: FormData) => {
    const { error } = await signUp(data.email, data.password, { full_name: data.full_name });

    if (error) {
      toast.error(error.message || 'Registration failed. Please try again.');
      return;
    }

    try {
      const api = getBrowserApiClient();
      await api.post('/api/v1/auth/profile', { full_name: data.full_name });
    } catch {
      // Non-fatal
    }

    setDone(true);
  };

  if (done) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background px-6">
        <motion.div initial="hidden" animate="visible" variants={scalePop} className="w-full max-w-sm text-center">
          <Card className="border-accent-emerald/20 p-10">
            <CheckCircle2 className="mx-auto mb-4 h-12 w-12 text-accent-emerald-ink" />
            <h2 className="mb-2 text-xl font-semibold">Check your email</h2>
            <p className="text-sm text-muted-foreground">
              We sent a confirmation link to your email. Click it to activate your account.
            </p>
            <Link href="/login" className="mt-6 inline-block text-sm text-primary transition-colors hover:text-primary/80">
              Back to sign in
            </Link>
          </Card>
        </motion.div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-6 py-12">
      <motion.div
        initial="hidden"
        animate="visible"
        variants={staggerContainer(0.1)}
        className="grid w-full max-w-4xl items-center gap-8 md:grid-cols-2"
      >
        {/* Left — perks */}
        <motion.div variants={fadeUp} className="hidden space-y-6 md:block">
          <Link href="/" className="flex items-center gap-2">
            <span className="font-mono text-sm font-semibold tracking-tight">InterviewOS</span>
          </Link>
          <div>
            <h2 className="mb-3 text-3xl font-medium tracking-[-0.03em]">
              Your first free interview
              <br />
              <span className="gradient-text">starts right now.</span>
            </h2>
            <p className="text-sm text-muted-foreground">
              No setup. No payment. Just you, an AI interviewer, and the feedback you need.
            </p>
          </div>
          <ul className="space-y-3">
            {PERKS.map((perk) => (
              <li key={perk} className="flex items-center gap-3 text-sm text-muted-foreground">
                <CheckCircle2 className="h-4 w-4 flex-shrink-0 text-accent-emerald-ink" />
                {perk}
              </li>
            ))}
          </ul>
        </motion.div>

        {/* Right — form */}
        <motion.div variants={fadeUp}>
          <Link href="/" className="mb-6 flex items-center gap-2 md:hidden">
            <span className="font-mono text-sm font-semibold tracking-tight">InterviewOS</span>
          </Link>

          <div>
            <div className="mb-6">
              <h1 className="text-3xl font-medium tracking-[-0.03em]">Create your account</h1>
              <p className="mt-1 text-sm text-muted-foreground">Set up your interview profile in under a minute.</p>
            </div>

            <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
              {/* Floating labels rather than placeholders. A placeholder vanishes the moment
                  you type, so anyone interrupted mid-signup returns to filled boxes with no
                  idea what each wanted — which on the form that creates the account is a real
                  defect, not a style preference. */}
              <FloatingLabelInput
                label="Full name"
                id="full_name"
                type="text"
                autoComplete="name"
                error={errors.full_name?.message}
                {...register('full_name')}
              />

              <FloatingLabelInput
                label="Email address"
                id="email"
                type="email"
                autoComplete="email"
                error={errors.email?.message}
                {...register('email')}
              />

              <div>
                <div className="relative">
                  <FloatingLabelInput
                    label="Password"
                    id="password"
                    type={showPassword ? 'text' : 'password'}
                    autoComplete="new-password"
                    className="pr-10"
                    error={errors.password?.message}
                    {...register('password')}
                  />
                  <button
                    type="button"
                    aria-label={showPassword ? 'Hide password' : 'Show password'}
                    className="absolute right-3 top-[22px] text-muted-foreground"
                    onClick={() => setShowPassword((v) => !v)}
                  >
                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
                {/* Advisory only — it never blocks submission. Length is weighted far above
                    punctuation because that is where the entropy actually is, and an obvious
                    sequence caps the score however long it is. */}
                <PasswordStrength password={passwordValue ?? ''} />
              </div>

              <FloatingLabelInput
                label="Confirm password"
                id="confirmPassword"
                type={showPassword ? 'text' : 'password'}
                autoComplete="new-password"
                error={errors.confirmPassword?.message}
                {...register('confirmPassword')}
              />

              <Button type="submit" className="w-full" loading={isSubmitting}>
                {isSubmitting ? 'Creating account…' : 'Create free account'}
              </Button>
            </form>

            <p className="mt-6 text-center text-sm text-muted-foreground">
              Already have an account?{' '}
              <Link href="/login" className="font-medium text-primary transition-colors hover:text-primary/80">Sign in</Link>
            </p>
          </div>
        </motion.div>
      </motion.div>
    </div>
  );
}
