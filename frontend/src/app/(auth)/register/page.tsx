'use client';

import { motion } from 'framer-motion';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Code2, Eye, EyeOff, Loader2, CheckCircle2 } from 'lucide-react';
import { useAuth } from '@/hooks/useAuth';
import { getBrowserApiClient } from '@/lib/api';
import { toast } from 'sonner';

const schema = z.object({
  full_name: z.string().min(2, 'Name must be at least 2 characters'),
  email: z.string().email('Enter a valid email address'),
  password: z
    .string()
    .min(8, 'Password must be at least 8 characters')
    .regex(/[A-Z]/, 'Include at least one uppercase letter')
    .regex(/[0-9]/, 'Include at least one number'),
  confirmPassword: z.string(),
}).refine((data) => data.password === data.confirmPassword, {
  message: "Passwords don't match",
  path: ['confirmPassword'],
});

type FormData = z.infer<typeof schema>;

const PERKS = [
  'Free Cognizant Java FSE mock interview',
  'Real-time AI evaluation after every answer',
  'Detailed performance report at the end',
  'No credit card required',
];

export default function RegisterPage() {
  const [showPassword, setShowPassword] = useState(false);
  const [done, setDone] = useState(false);
  const router = useRouter();
  const { signUp } = useAuth();

  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<FormData>({
    resolver: zodResolver(schema),
  });

  const onSubmit = async (data: FormData) => {
    const { error } = await signUp(data.email, data.password, { full_name: data.full_name });

    if (error) {
      toast.error(error.message || 'Registration failed. Please try again.');
      return;
    }

    // Sync to application DB
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
      <div className="flex min-h-screen items-center justify-center px-4">
        <motion.div
          className="w-full max-w-sm text-center"
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.3 }}
        >
          <div className="glass rounded-2xl border border-emerald-500/20 p-10">
            <CheckCircle2 className="h-12 w-12 text-emerald-400 mx-auto mb-4" />
            <h2 className="text-xl font-bold mb-2">Check your email</h2>
            <p className="text-sm text-muted-foreground">
              We sent a confirmation link to your email. Click it to activate your account.
            </p>
            <Link
              href="/login"
              className="mt-6 inline-block text-sm text-primary hover:text-primary/80 transition-colors"
            >
              Back to sign in
            </Link>
          </div>
        </motion.div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-12">
      <motion.div
        className="w-full max-w-4xl grid md:grid-cols-2 gap-8 items-center"
        initial={{ opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: 'easeOut' }}
      >
        {/* Left — perks */}
        <div className="hidden md:block space-y-6">
          <Link href="/" className="flex items-center gap-2">
            <div className="h-8 w-8 rounded-lg bg-primary flex items-center justify-center">
              <Code2 className="h-4 w-4 text-primary-foreground" />
            </div>
            <span className="text-lg font-bold">InterviewOS</span>
          </Link>
          <div>
            <h2 className="text-3xl font-bold mb-3">
              Your first free interview
              <br />
              <span className="gradient-text">starts right now.</span>
            </h2>
            <p className="text-muted-foreground text-sm">
              No setup. No payment. Just you, an AI interviewer, and the feedback you need.
            </p>
          </div>
          <ul className="space-y-3">
            {PERKS.map((perk) => (
              <li key={perk} className="flex items-center gap-3 text-sm text-muted-foreground">
                <CheckCircle2 className="h-4 w-4 text-emerald-400 flex-shrink-0" />
                {perk}
              </li>
            ))}
          </ul>
        </div>

        {/* Right — form */}
        <div>
          <Link href="/" className="mb-6 flex items-center gap-2 md:hidden">
            <div className="h-8 w-8 rounded-lg bg-primary flex items-center justify-center">
              <Code2 className="h-4 w-4 text-primary-foreground" />
            </div>
            <span className="text-lg font-bold">InterviewOS</span>
          </Link>

          <div className="glass rounded-2xl border border-border/50 p-8">
            <div className="mb-6">
              <h1 className="text-2xl font-bold">Create your account</h1>
              <p className="text-sm text-muted-foreground mt-1">Free forever. No credit card needed.</p>
            </div>

            <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
              <div>
                <label htmlFor="full_name" className="block text-sm font-medium mb-1.5">Full name</label>
                <input
                  id="full_name"
                  type="text"
                  autoComplete="name"
                  className="w-full rounded-lg border border-border bg-surface px-4 py-2.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary transition-all"
                  placeholder="Arjun Sharma"
                  {...register('full_name')}
                />
                {errors.full_name && <p className="mt-1 text-xs text-destructive">{errors.full_name.message}</p>}
              </div>

              <div>
                <label htmlFor="email" className="block text-sm font-medium mb-1.5">Email address</label>
                <input
                  id="email"
                  type="email"
                  autoComplete="email"
                  className="w-full rounded-lg border border-border bg-surface px-4 py-2.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary transition-all"
                  placeholder="you@example.com"
                  {...register('email')}
                />
                {errors.email && <p className="mt-1 text-xs text-destructive">{errors.email.message}</p>}
              </div>

              <div>
                <label htmlFor="password" className="block text-sm font-medium mb-1.5">Password</label>
                <div className="relative">
                  <input
                    id="password"
                    type={showPassword ? 'text' : 'password'}
                    autoComplete="new-password"
                    className="w-full rounded-lg border border-border bg-surface px-4 py-2.5 pr-10 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary transition-all"
                    placeholder="Minimum 8 characters"
                    {...register('password')}
                  />
                  <button type="button" className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground" onClick={() => setShowPassword(v => !v)}>
                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
                {errors.password && <p className="mt-1 text-xs text-destructive">{errors.password.message}</p>}
              </div>

              <div>
                <label htmlFor="confirmPassword" className="block text-sm font-medium mb-1.5">Confirm password</label>
                <input
                  id="confirmPassword"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="new-password"
                  className="w-full rounded-lg border border-border bg-surface px-4 py-2.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary transition-all"
                  placeholder="Repeat your password"
                  {...register('confirmPassword')}
                />
                {errors.confirmPassword && <p className="mt-1 text-xs text-destructive">{errors.confirmPassword.message}</p>}
              </div>

              <button
                type="submit"
                disabled={isSubmitting}
                className="w-full flex items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-60 transition-all"
              >
                {isSubmitting ? <><Loader2 className="h-4 w-4 animate-spin" />Creating account...</> : 'Create free account'}
              </button>
            </form>

            <p className="mt-6 text-center text-sm text-muted-foreground">
              Already have an account?{' '}
              <Link href="/login" className="text-primary hover:text-primary/80 font-medium transition-colors">Sign in</Link>
            </p>
          </div>
        </div>
      </motion.div>
    </div>
  );
}
