'use client';

import { motion } from 'framer-motion';
import Link from 'next/link';
import { useEffect, useState } from 'react';
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
import { Lockup } from '@/components/brand/Brandmark';
import ConsentCheckbox from '@/components/legal/ConsentCheckbox';

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
/*
 * THE THREE CONSENT ANSWERS ARE SEPARATE FIELDS, AND NONE OF THEM DEFAULTS TO TRUE.
 *
 * DPDP §6 wants consent by clear affirmative action, and a checkbox that starts ticked is a
 * pre-ticked box in a different costume — the one thing §6 names explicitly as not consent.
 * `literal(true)` rather than `boolean()` so an unticked box fails validation with a message
 * rather than submitting a false the server would have to interpret.
 *
 * SEPARATE RATHER THAN ONE "I AGREE TO EVERYTHING". §5 notice and §6 consent are distinct
 * obligations, and §9 age is a third question entirely; bundling them makes it impossible to
 * show afterwards which one a person actually answered — and the consent ledger records them
 * as three rows for exactly that reason.
 */
const schema = z.object({
  full_name: z.string().min(2, 'Name must be at least 2 characters'),
  email: z.string().email('Enter a valid email address'),
  password: passwordRules,
  confirmPassword: z.string(),
  privacy_notice: z.literal(true, {
    errorMap: () => ({ message: 'Please read what happens to your data before continuing' }),
  }),
  terms: z.literal(true, {
    errorMap: () => ({ message: 'Please accept the terms to continue' }),
  }),
  age_18_plus: z.literal(true, {
    errorMap: () => ({
      message: 'This service measures how you speak and present, which we may not do for under-18s',
    }),
  }),
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
  /*
   * The version of the notice THIS TAB SHOWED, sent with the consent rather than assumed
   * server-side. A tab left open across a notice change would otherwise record agreement to
   * wording the person never saw — which is precisely what the version stamp exists to
   * prevent. `undefined` until the disclosure loads; the server falls back to its own current
   * version, which is correct for a tab that was opened after the change.
   */
  const [noticeVersion, setNoticeVersion] = useState<string | undefined>(undefined);

  useEffect(() => {
    getBrowserApiClient()
      .get<{ notice_version: string }>('/api/v1/legal/disclosure')
      .then((r) => setNoticeVersion(r.data.notice_version))
      .catch(() => {
        /* The form still works; the server stamps its own current version. */
      });
  }, []);

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

    /*
     * Record the consent, AFTER the account exists — a consent row needs a user to belong to.
     *
     * NOT SILENTLY SWALLOWED like the profile call above. A failure here means the account
     * exists with no evidence of consent, which is the state DPDP §6 is about, so it is
     * surfaced and retried from Settings rather than left to look like it worked. The
     * registration itself still succeeds: tearing down a created account because a follow-up
     * call failed would lose them the password they just chose.
     */
    try {
      const api = getBrowserApiClient();
      await api.post('/api/v1/legal/consent/signup', {
        privacy_notice: data.privacy_notice,
        terms: data.terms,
        age_18_plus: data.age_18_plus,
        notice_version: noticeVersion,
      });
    } catch {
      toast.warning(
        'Your account was created, but we could not record your privacy choices. Please confirm them in Settings.'
      );
    }

    setDone(true);
  };

  if (done) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-background px-4 py-10 sm:px-6">
        <motion.div initial="hidden" animate="visible" variants={scalePop} className="w-full max-w-sm text-center">
          {/* p-10 was 80px of the 288px available at 320px, leaving a 208px column that
              broke this three-line sentence into eight lines. Only the phone step is
              tightened; `sm:p-10` keeps the original card from 640px up. */}
          <Card className="border-accent-emerald/20 p-6 sm:p-10">
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

  /*
   * `min-h-dvh` rather than `min-h-screen`: `vh` is the viewport with the browser chrome
   * hidden, so a 100vh box is taller than what a phone actually shows and `items-center` then
   * centres this form below the visible middle — with the keyboard open, the "Create free
   * account" button ends up behind it. `dvh` shrinks with the keyboard so the form re-centres
   * in the part of the screen that is really there. Both are FLOORS, so on the taller content
   * this page has the container simply grows and the page scrolls; neither can clip. Identical
   * to `vh` on desktop.
   */
  return (
    <div className="flex min-h-dvh items-center justify-center bg-background px-4 py-10 sm:px-6 sm:py-12">
      <motion.div
        initial="hidden"
        animate="visible"
        variants={staggerContainer(0.1)}
        className="grid w-full max-w-4xl items-center gap-8 md:grid-cols-2"
      >
        {/* Left on desktop, BELOW THE FORM on a phone — and no longer `hidden`.

            THIS PANEL WAS `hidden md:block`, so every visitor on a phone — which is most of
            them — was shown a bare password form and never told what the free account
            actually gets them. That is not a responsive layout, it is the argument for
            signing up being deleted at the width where it matters most. Reported as "make
            sure that nothing must be hidden specially on all the pages", and this was the
            one place in these pages where content was genuinely gone rather than cramped.

            The reason it was hidden is real, though: on a phone this column would push the
            form itself below the fold, and the form is what the page is for. `order` solves
            that without deleting anything — the form comes first in the single-column stack
            and the perks read as the reassurance underneath it, while `md:order-1` restores
            the designed left-hand position the moment there are two columns to put it in.

            The wordmark inside it stays `md:flex` only. It is not content being hidden: the
            same link is rendered directly above the form below (`md:hidden`), so on a phone
            the logo is on the page exactly once instead of twice. */}
        <motion.div variants={fadeUp} className="order-2 space-y-6 md:order-1">
          <Link href="/" className="hidden items-center gap-2 md:flex">
            <Lockup width={190} priority />
          </Link>
          <div>
            <h2 className="mb-3 text-3xl font-medium tracking-[-0.03em]">
              Your interview practice
              <br />
              <span className="gradient-text">starts right now.</span>
            </h2>
            <p className="text-sm text-muted-foreground">
              No setup, no subscription. Just you, an AI interviewer, and the feedback you need.
            </p>
          </div>
          <ul className="space-y-3">
            {PERKS.map((perk) => (
              // items-start, not items-center: at 320px every one of these perks wraps to
              // three lines, and a vertically centred tick then floats beside the middle
              // line instead of marking the item. min-w-0 lets the text wrap rather than
              // set the row's width.
              <li key={perk} className="flex items-start gap-3 text-sm text-muted-foreground">
                <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-accent-emerald-ink" />
                <span className="min-w-0">{perk}</span>
              </li>
            ))}
          </ul>
        </motion.div>

        {/* Right on desktop, FIRST on a phone — see the ordering note on the panel above. */}
        <motion.div variants={fadeUp} className="order-1 md:order-2">
          <Link href="/" className="mb-6 flex items-center gap-2 md:hidden">
            <Lockup width={190} priority />
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
                    className="pr-12"
                    error={errors.password?.message}
                    {...register('password')}
                  />
                  {/* A 44x44 box rather than a bare 16px glyph, which was a tap target a
                      quarter of the minimum size sitting on top of the input's own text —
                      so a miss moved the caret instead of revealing the password. `pr-12`
                      on the field reserves the space so they cannot overlap.

                      `top-1` rather than the old `top-[22px]`: that magic offset was
                      measured against this field's height at `text-sm`, and the field is
                      now 16px on phones (see floating-label-input.tsx — under 16px iOS
                      zooms the whole page on focus), which moved the glyph off centre. A
                      44px box pinned near the top of a 52-56px field is centred enough at
                      both sizes and does not depend on the font size at all. */}
                  <button
                    type="button"
                    aria-label={showPassword ? 'Hide password' : 'Show password'}
                    className="absolute right-1 top-1 flex h-11 w-11 items-center justify-center rounded-lg text-muted-foreground"
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

              {/*
                * Plain checkboxes, above the button and not behind a "show more". A consent
                * control a person has to go looking for is not consent given by clear
                * affirmative action.
                */}
              <div className="space-y-3 rounded-xl border border-border/60 p-4 text-sm">
                <ConsentCheckbox
                  id="age_18_plus"
                  error={errors.age_18_plus?.message}
                  {...register('age_18_plus')}
                >
                  I am 18 or older.
                </ConsentCheckbox>

                <ConsentCheckbox
                  id="privacy_notice"
                  error={errors.privacy_notice?.message}
                  {...register('privacy_notice')}
                >
                  I have read{' '}
                  <Link href="/privacy" target="_blank" className="font-medium text-primary underline">
                    what happens to my data
                  </Link>
                  , including that my resume and answers are processed by AI providers outside
                  India.
                </ConsentCheckbox>

                <ConsentCheckbox id="terms" error={errors.terms?.message} {...register('terms')}>
                  I accept the terms of use.
                </ConsentCheckbox>
              </div>

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
