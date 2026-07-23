'use client';

import { motion } from 'framer-motion';
import Link from 'next/link';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Code2, Eye, EyeOff, CheckCircle2 } from 'lucide-react';
import { useAuth } from '@/hooks/useAuth';
import { getBrowserApiClient } from '@/lib/api';
import { toast } from 'sonner';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { fadeUp, scalePop, staggerContainer } from '@/lib/motion';

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
      <div className="hero-wash flex min-h-screen items-center justify-center px-4">
        <motion.div initial="hidden" animate="visible" variants={scalePop} className="w-full max-w-sm text-center">
          <Card className="border-emerald-500/20 p-10">
            <CheckCircle2 className="mx-auto mb-4 h-12 w-12 text-emerald-600" />
            <h2 className="mb-2 text-xl font-bold">Check your email</h2>
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
    <div className="hero-wash flex min-h-screen items-center justify-center px-4 py-12">
      <motion.div
        initial="hidden"
        animate="visible"
        variants={staggerContainer(0.1)}
        className="grid w-full max-w-4xl items-center gap-8 md:grid-cols-2"
      >
        {/* Left — perks */}
        <motion.div variants={fadeUp} className="hidden space-y-6 md:block">
          <Link href="/" className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-primary to-accent-violet shadow-glow">
              <Code2 className="h-4 w-4 text-primary-foreground" />
            </div>
            <span className="text-lg font-bold tracking-tight">InterviewOS</span>
          </Link>
          <div>
            <h2 className="mb-3 text-3xl font-bold tracking-tight">
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
                <CheckCircle2 className="h-4 w-4 flex-shrink-0 text-emerald-600" />
                {perk}
              </li>
            ))}
          </ul>
        </motion.div>

        {/* Right — form */}
        <motion.div variants={fadeUp}>
          <Link href="/" className="mb-6 flex items-center gap-2 md:hidden">
            <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-primary to-accent-violet shadow-glow">
              <Code2 className="h-4 w-4 text-primary-foreground" />
            </div>
            <span className="text-lg font-bold tracking-tight">InterviewOS</span>
          </Link>

          <Card className="p-8">
            <div className="mb-6">
              <h1 className="text-2xl font-bold tracking-tight">Create your account</h1>
              <p className="mt-1 text-sm text-muted-foreground">Free forever. No credit card needed.</p>
            </div>

            <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
              <div>
                <label htmlFor="full_name" className="mb-1.5 block text-sm font-medium">Full name</label>
                <Input id="full_name" type="text" autoComplete="name" placeholder="Arjun Sharma" {...register('full_name')} />
                {errors.full_name && <p className="mt-1 text-xs text-destructive">{errors.full_name.message}</p>}
              </div>

              <div>
                <label htmlFor="email" className="mb-1.5 block text-sm font-medium">Email address</label>
                <Input id="email" type="email" autoComplete="email" placeholder="you@example.com" {...register('email')} />
                {errors.email && <p className="mt-1 text-xs text-destructive">{errors.email.message}</p>}
              </div>

              <div>
                <label htmlFor="password" className="mb-1.5 block text-sm font-medium">Password</label>
                <div className="relative">
                  <Input
                    id="password"
                    type={showPassword ? 'text' : 'password'}
                    autoComplete="new-password"
                    placeholder="Minimum 8 characters"
                    className="pr-10"
                    {...register('password')}
                  />
                  <button type="button" className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground" onClick={() => setShowPassword((v) => !v)}>
                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
                {errors.password && <p className="mt-1 text-xs text-destructive">{errors.password.message}</p>}
              </div>

              <div>
                <label htmlFor="confirmPassword" className="mb-1.5 block text-sm font-medium">Confirm password</label>
                <Input
                  id="confirmPassword"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="new-password"
                  placeholder="Repeat your password"
                  {...register('confirmPassword')}
                />
                {errors.confirmPassword && <p className="mt-1 text-xs text-destructive">{errors.confirmPassword.message}</p>}
              </div>

              <Button type="submit" className="w-full" loading={isSubmitting}>
                {isSubmitting ? 'Creating account…' : 'Create free account'}
              </Button>
            </form>

            <p className="mt-6 text-center text-sm text-muted-foreground">
              Already have an account?{' '}
              <Link href="/login" className="font-medium text-primary transition-colors hover:text-primary/80">Sign in</Link>
            </p>
          </Card>
        </motion.div>
      </motion.div>
    </div>
  );
}
