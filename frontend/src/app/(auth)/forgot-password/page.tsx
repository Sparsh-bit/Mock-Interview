'use client';

import { motion } from 'framer-motion';
import Link from 'next/link';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { CheckCircle2 } from 'lucide-react';
import { useAuth } from '@/hooks/useAuth';
import { toast } from 'sonner';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { scalePop } from '@/lib/motion';

export const runtime = 'edge';
const schema = z.object({
  email: z.string().email('Enter a valid email address'),
});

type FormData = z.infer<typeof schema>;

export default function ForgotPasswordPage() {
  const [sent, setSent] = useState(false);
  const { resetPassword } = useAuth();

  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<FormData>({
    resolver: zodResolver(schema),
  });

  const onSubmit = async (data: FormData) => {
    const { error } = await resetPassword(data.email);

    if (error) {
      toast.error(error.message || 'Could not send reset link. Please try again.');
      return;
    }

    setSent(true);
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-6">
      <motion.div initial="hidden" animate="visible" variants={scalePop} className="w-full max-w-sm">
        <Link
          href="/"
          className="mb-10 block font-mono text-sm font-semibold tracking-tight transition-opacity hover:opacity-70"
        >
          InterviewOS
        </Link>

        <div>
          {sent ? (
            <div className="text-center">
              <CheckCircle2 className="mx-auto mb-4 h-12 w-12 text-accent-emerald-ink" />
              <h1 className="mb-2 text-xl font-semibold">Check your email</h1>
              <p className="text-sm text-muted-foreground">
                We sent a password reset link to your email. Click it to choose a new password.
              </p>
            </div>
          ) : (
            <>
              <div className="mb-8 border-b border-border pb-6">
                <h1 className="text-3xl font-medium tracking-[-0.03em]">Forgot password?</h1>
                <p className="mt-2 text-sm text-muted-foreground">
                  Enter your email and we&apos;ll send you a reset link
                </p>
              </div>

              <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
                <div>
                  <label htmlFor="email" className="mb-1.5 block text-sm font-medium">
                    Email address
                  </label>
                  <Input id="email" type="email" autoComplete="email" placeholder="you@example.com" {...register('email')} />
                  {errors.email && <p className="mt-1 text-xs text-destructive">{errors.email.message}</p>}
                </div>

                <Button type="submit" className="w-full" loading={isSubmitting}>
                  {isSubmitting ? 'Sending link…' : 'Send reset link'}
                </Button>
              </form>
            </>
          )}

          <p className="mt-8 border-t border-border pt-6 text-sm text-muted-foreground">
            Remembered your password?{' '}
            <Link href="/login" className="font-medium text-primary transition-colors hover:text-primary/80">
              Back to sign in
            </Link>
          </p>
        </div>
      </motion.div>
    </div>
  );
}
