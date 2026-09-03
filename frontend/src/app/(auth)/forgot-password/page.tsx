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
import { Lockup } from '@/components/brand/Brandmark';

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
    <div className="flex min-h-dvh items-center justify-center bg-background px-4 py-10 sm:px-6">
      {/*
        `min-h-dvh`, AND THE VERTICAL PADDING, ARE BOTH ABOUT THE ON-SCREEN KEYBOARD.

        This was `flex min-h-screen items-center justify-center`. `min-h-screen` is
        `min-height: 100vh`, and on mobile Safari and Chrome `vh` is the viewport measured with
        the browser chrome HIDDEN — a height the user is not currently looking at. So the box is
        taller than the visible area, and `items-center` then centres the form in the box rather
        than in the screen: the card sits lower than it looks like it should, and its bottom edge
        — the submit button — lands under the address bar. It is reachable by scrolling, because
        a floor can only grow, but the user has to discover that.

        With the keyboard open it stops being cosmetic. The visual viewport loses roughly half
        its height and `100vh` does not change, so nothing reflows: the browser scrolls the
        focused field into view and the button below it stays under the keyboard. `100dvh` is the
        DYNAMIC viewport — it shrinks when the keyboard opens, the container shrinks with it, and
        the form re-centres inside the part of the screen the user can actually see. On desktop
        `dvh` and `vh` are identical, so nothing moves there.

        The padding is the other half. Once the content is taller than the container — a short
        landscape phone, or 200% browser zoom — centring stops applying and the content simply
        starts at the top; without `py-*` the heading butts against the very top of the scroll
        area with nothing above it. It is a floor plus padding, so it can never clip: the
        container grows to the content and the page scrolls.
      */}
      <motion.div initial="hidden" animate="visible" variants={scalePop} className="w-full max-w-sm">
        {/* The mark, not the name set in mono. These four screens are where somebody meets
            the product for the first time after clicking a link from somewhere else, and a
            wordmark typed in the same face as the body copy is indistinguishable from a
            heading — it identifies nothing. */}
        <Link
          href="/"
          aria-label="InterviewOS home"
          className="mb-6 block w-fit transition-opacity hover:opacity-70 sm:mb-10"
        >
          <Lockup width={190} priority />
        </Link>

        <div>
          {sent ? (
            <div className="text-center">
              <CheckCircle2 className="mx-auto mb-4 h-12 w-12 text-accent-emerald-ink" />
              <h1 className="mb-2 font-display text-xl font-[520]">Check your email</h1>
              <p className="text-sm text-muted-foreground">
                We sent a password reset link to your email. Click it to choose a new password.
              </p>
            </div>
          ) : (
            <>
              <div className="mb-8 border-b border-border pb-6">
                <h1 className="font-display text-3xl font-[480] tracking-[-0.022em]">Forgot password?</h1>
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
