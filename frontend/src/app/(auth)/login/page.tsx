'use client';

import { motion } from 'framer-motion';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Eye, EyeOff } from 'lucide-react';
import { useAuth } from '@/hooks/useAuth';
import { getBrowserApiClient } from '@/lib/api';
import { safeRedirect } from '@/lib/auth/safe-redirect';
import { toast } from 'sonner';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { scalePop } from '@/lib/motion';

export const runtime = 'edge';
const schema = z.object({
  email: z.string().email('Enter a valid email address'),
  password: z.string().min(8, 'Password must be at least 8 characters'),
});

type FormData = z.infer<typeof schema>;

export default function LoginPage() {
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
        <Link
          href="/"
          className="mb-6 block font-mono text-sm font-semibold tracking-tight transition-opacity hover:opacity-70 sm:mb-10"
        >
          InterviewOS
        </Link>

        <div>
          <div className="mb-8 border-b border-border pb-6">
            <h1 className="text-3xl font-medium tracking-[-0.03em]">Sign in</h1>
            <p className="mt-2 text-sm text-muted-foreground">Resume your interview preparation</p>
          </div>

          <Suspense fallback={<div className="text-sm text-muted-foreground">Loading…</div>}>
            <LoginForm />
          </Suspense>

          <p className="mt-8 border-t border-border pt-6 text-sm text-muted-foreground">
            Don&apos;t have an account?{' '}
            <Link href="/register" className="font-medium text-primary transition-colors hover:text-primary/80">
              Create one free
            </Link>
          </p>
        </div>
      </motion.div>
    </div>
  );
}

function LoginForm() {
  const [showPassword, setShowPassword] = useState(false);
  const router = useRouter();
  const searchParams = useSearchParams();
  // VALIDATED, NOT TRUSTED. This value comes from the query string, and it used to be handed
  // straight to router.push — so `?redirectTo=https://evil.example` bounced the candidate off
  // the site the instant their password was accepted, from a link that is genuinely ours up to
  // the query string. See lib/auth/safe-redirect.ts.
  const redirectTo = safeRedirect(searchParams.get('redirectTo'));
  const { signIn } = useAuth();

  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<FormData>({
    resolver: zodResolver(schema),
  });

  const onSubmit = async (data: FormData) => {
    const { error } = await signIn(data.email, data.password);

    if (error) {
      toast.error(error.message || 'Sign in failed. Check your credentials.');
      return;
    }

    try {
      const api = getBrowserApiClient();
      await api.post('/api/v1/auth/profile', {});
    } catch {
      // Non-fatal
    }

    toast.success('Welcome back!');
    router.push(redirectTo);
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
      <div>
        <label htmlFor="email" className="mb-1.5 block text-sm font-medium">
          Email address
        </label>
        <Input id="email" type="email" autoComplete="email" placeholder="you@example.com" {...register('email')} />
        {errors.email && <p className="mt-1 text-xs text-destructive">{errors.email.message}</p>}
      </div>

      <div>
        {/* flex-wrap + gap: these two sat on one line with no gap and no permission to wrap,
            so at 320px and at every zoom step above 150% the link ran into the label. */}
        <div className="mb-1.5 flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
          <label htmlFor="password" className="text-sm font-medium">Password</label>
          <Link
            href="/forgot-password"
            className="inline-flex min-h-6 items-center text-xs text-primary transition-colors hover:text-primary/80"
          >
            Forgot password?
          </Link>
        </div>
        <div className="relative">
          <Input
            id="password"
            type={showPassword ? 'text' : 'password'}
            autoComplete="current-password"
            placeholder="Enter your password"
            className="pr-12"
            {...register('password')}
          />
          {/* THE TAP TARGET IS THE BUTTON, NOT THE GLYPH. This was a bare 16px icon with no
              padding — a 16x16 target, well under the 44px minimum, sitting directly on top
              of the text the user is trying to read. Half the taps landed in the input and
              just moved the caret, on the one control that tells somebody whether they have
              mistyped the password they cannot see. The box is now 44x44 (`h-11 w-11`) and
              the input reserves `pr-12` for it so the two never overlap.
              `aria-label` because the button has no text: it announced as "button". */}
          <button
            type="button"
            aria-label={showPassword ? 'Hide password' : 'Show password'}
            className="absolute right-1 top-1/2 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:text-foreground"
            onClick={() => setShowPassword((v) => !v)}
          >
            {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        </div>
        {errors.password && <p className="mt-1 text-xs text-destructive">{errors.password.message}</p>}
      </div>

      <Button type="submit" className="w-full" loading={isSubmitting}>
        {isSubmitting ? 'Signing in…' : 'Sign in'}
      </Button>
    </form>
  );
}
