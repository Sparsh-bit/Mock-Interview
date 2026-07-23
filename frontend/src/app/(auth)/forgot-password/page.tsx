'use client';

import { motion } from 'framer-motion';
import Link from 'next/link';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Code2, CheckCircle2 } from 'lucide-react';
import { useAuth } from '@/hooks/useAuth';
import { toast } from 'sonner';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { scalePop } from '@/lib/motion';

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
    <div className="aurora-bg flex min-h-screen items-center justify-center px-4">
      <motion.div initial="hidden" animate="visible" variants={scalePop} className="w-full max-w-sm">
        <Link href="/" className="mb-8 flex items-center justify-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-primary to-accent-violet shadow-glow">
            <Code2 className="h-4 w-4 text-primary-foreground" />
          </div>
          <span className="text-lg font-bold tracking-tight">InterviewOS</span>
        </Link>

        <Card className="p-8">
          {sent ? (
            <div className="text-center">
              <CheckCircle2 className="mx-auto mb-4 h-12 w-12 text-emerald-400" />
              <h1 className="mb-2 text-xl font-bold">Check your email</h1>
              <p className="text-sm text-muted-foreground">
                We sent a password reset link to your email. Click it to choose a new password.
              </p>
            </div>
          ) : (
            <>
              <div className="mb-6">
                <h1 className="text-2xl font-bold tracking-tight">Forgot password?</h1>
                <p className="mt-1 text-sm text-muted-foreground">
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

          <p className="mt-6 text-center text-sm text-muted-foreground">
            Remembered your password?{' '}
            <Link href="/login" className="font-medium text-primary transition-colors hover:text-primary/80">
              Back to sign in
            </Link>
          </p>
        </Card>
      </motion.div>
    </div>
  );
}
