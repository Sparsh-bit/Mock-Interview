'use client';

import { motion } from 'framer-motion';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { CheckCircle2, Loader2, Lock } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { newPasswordSchema, type NewPasswordForm } from '@/lib/auth/password';
import { createClient } from '@/lib/supabase/client';
import { scalePop } from '@/lib/motion';

export const runtime = 'edge';

/**
 * Where a password reset is actually COMPLETED.
 *
 * THIS PAGE DID NOT EXIST, AND THAT MADE PASSWORD RESET A DEAD END. The flow was:
 *
 *   1. "Forgot password?" sends a reset email — worked.
 *   2. The link hits /auth/callback, which exchanges the code for a recovery session —
 *      worked, and its comment says it sends the user "to the settings page, where they can
 *      complete the password change".
 *   3. /settings had no password field. Its only control was a button that sends ANOTHER
 *      reset email.
 *
 * So the reset link delivered you to a page whose sole action was to send you the same link
 * again. Nobody who forgot their password could get back into their account, ever. Three
 * pieces each behaved correctly and the journey they formed had no end — and the comment in
 * the callback describes a page that was never built, which is why nothing looked wrong.
 *
 * WHY A DEDICATED ROUTE RATHER THAN A FIELD ON /settings. The recovery session is a
 * short-lived, single-purpose credential: Supabase grants it so one password can be set. A
 * form that only appears on a settings page conflates "I am changing my password while logged
 * in" with "I am recovering an account I cannot get into", and those want different copy,
 * different navigation, and different behaviour when there is no session. This route is the
 * end of the recovery journey and reads like it.
 *
 * IT REQUIRES A SESSION AND SAYS SO. Landing here without one means the link expired, was
 * already used, or was opened in a different browser than it was requested from — all common,
 * and all indistinguishable to us. So the page does not show a form it cannot submit; it
 * explains and offers a fresh link. A form that fails on submit teaches somebody to doubt
 * their new password rather than the expired link.
 */
export default function ResetPasswordPage() {
  const router = useRouter();
  const supabase = createClient();
  const [ready, setReady] = useState<boolean | null>(null);
  const [done, setDone] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<NewPasswordForm>({ resolver: zodResolver(newPasswordSchema) });

  useEffect(() => {
    let cancelled = false;
    /*
     * ASKED ONCE, ON MOUNT, AND NOT DERIVED FROM THE URL.
     *
     * The recovery code has already been exchanged by /auth/callback by the time anyone
     * arrives here, so the evidence that the link was good is the SESSION, not a query
     * parameter. Reading the URL would also be wrong for the case that matters — a link
     * opened twice — because the parameters are still there on the second visit while the
     * session is not.
     */
    void supabase.auth.getSession().then(({ data }) => {
      if (!cancelled) setReady(!!data.session);
    });
    return () => {
      cancelled = true;
    };
  }, [supabase]);

  const onSubmit = async (form: NewPasswordForm) => {
    const { error } = await supabase.auth.updateUser({ password: form.password });
    if (error) {
      // The server's own message, because it distinguishes the cases a user can act on —
      // "New password should be different from the old password", an expired session — far
      // better than a generic string can.
      toast.error(error.message || 'Could not set your new password. Request a fresh link.');
      return;
    }
    setDone(true);
    // Straight into the app. They are already authenticated by the recovery session, so
    // sending them to /login to type the password they just chose is a pointless extra step.
    setTimeout(() => router.push('/dashboard'), 1200);
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
        <Link
          href="/"
          className="mb-6 block font-mono text-sm font-semibold tracking-tight transition-opacity hover:opacity-70 sm:mb-10"
        >
          InterviewOS
        </Link>

        {ready === null && (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Checking your link…
          </p>
        )}

        {ready === false && (
          <div>
            <h1 className="text-3xl font-medium tracking-[-0.03em]">This link has expired</h1>
            <p className="mt-2 text-sm text-muted-foreground">
              Reset links can only be used once, and they expire. Request a new one and open it
              in the same browser.
            </p>
            <Link
              href="/forgot-password"
              className="mt-6 inline-flex min-h-11 items-center rounded-xl bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground"
            >
              Send a new link
            </Link>
          </div>
        )}

        {ready === true &&
          (done ? (
            <div className="text-center">
              <CheckCircle2 className="mx-auto mb-4 h-12 w-12 text-accent-emerald-ink" />
              <h1 className="mb-2 text-xl font-semibold">Password updated</h1>
              <p className="text-sm text-muted-foreground">Taking you to your dashboard…</p>
            </div>
          ) : (
            <>
              <div className="mb-8 border-b border-border pb-6">
                <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
                  <Lock className="h-5 w-5" />
                </div>
                <h1 className="text-3xl font-medium tracking-[-0.03em]">Choose a new password</h1>
                <p className="mt-2 text-sm text-muted-foreground">
                  At least 8 characters, with one capital letter and one number.
                </p>
              </div>

              <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
                <div>
                  <Input
                    type="password"
                    autoComplete="new-password"
                    placeholder="New password"
                    {...register('password')}
                  />
                  {errors.password && (
                    <p className="mt-1.5 text-xs text-destructive">{errors.password.message}</p>
                  )}
                </div>
                <div>
                  <Input
                    type="password"
                    autoComplete="new-password"
                    placeholder="Confirm new password"
                    {...register('confirmPassword')}
                  />
                  {errors.confirmPassword && (
                    <p className="mt-1.5 text-xs text-destructive">
                      {errors.confirmPassword.message}
                    </p>
                  )}
                </div>
                <Button type="submit" className="w-full" disabled={isSubmitting}>
                  {isSubmitting ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Saving…
                    </>
                  ) : (
                    'Set new password'
                  )}
                </Button>
              </form>
            </>
          ))}
      </motion.div>
    </div>
  );
}
