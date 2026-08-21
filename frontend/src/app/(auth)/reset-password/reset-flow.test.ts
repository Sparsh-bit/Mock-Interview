import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import { newPasswordSchema, passwordRules } from '@/lib/auth/password';

/**
 * Password reset has an END — app/(auth)/reset-password/reset-flow.test.ts
 *
 * IT DID NOT. The journey was:
 *
 *   1. "Forgot password?" sends a reset email.                                  worked
 *   2. The link hits /auth/callback, which exchanges the code for a session.    worked
 *   3. The callback redirected to /settings — its comment says "where they can
 *      complete the password change".
 *   4. /settings had no password field. Its only control was a button that
 *      sends ANOTHER reset email.
 *
 * So the reset link delivered you to a page whose sole action was to send you the same link
 * again. Anyone who forgot their password could never get back into their account. Three
 * pieces each behaved correctly and the journey they formed had no end — and the callback's
 * own comment described a page that had never been built, which is why nothing read as
 * broken.
 *
 * A LAUNCH BLOCKER, and invisible to every other kind of test: nothing throws, no request
 * fails, types and lint are clean, and the only symptom is a user who cannot come back.
 *
 * These are file and source assertions. The real test would drive a browser through the
 * email link, which needs a mail server and a live Supabase project; what this catches is the
 * regression that actually threatens the fix — somebody removing the page, or pointing the
 * redirect back at a page that cannot complete the reset.
 */

const APP = join(process.cwd(), 'src/app');
const PAGE = join(APP, '(auth)/reset-password/page.tsx');

describe('the journey has an end', () => {
  it('a page exists to set the new password', () => {
    expect(existsSync(PAGE)).toBe(true);
  });

  it('that page actually sets a password', () => {
    // The whole point. A page that only reads the session would be the same dead end with
    // better copy.
    expect(readFileSync(PAGE, 'utf8')).toContain('updateUser({ password:');
  });

  it('the reset email points at it, not at a page that cannot finish the job', () => {
    const useAuth = readFileSync(join(process.cwd(), 'src/hooks/useAuth.ts'), 'utf8');
    expect(useAuth).toContain('next=/reset-password');
    // The old destination. /settings can only send another link, so a redirect back to it
    // recreates the loop exactly.
    expect(useAuth).not.toContain('next=/settings');
  });

  it('both entry points share one resetPassword, so they cannot diverge', () => {
    // The forgot-password page and the settings button both call useAuth().resetPassword.
    // If either built its own redirect, fixing one would leave the other looping.
    for (const file of ['src/app/(auth)/forgot-password/page.tsx', 'src/app/(dashboard)/settings/page.tsx']) {
      const src = readFileSync(join(process.cwd(), file), 'utf8');
      expect(src).toContain('resetPassword');
      expect(src).not.toContain('resetPasswordForEmail');
    }
  });

  it('is an edge route like every other page in this app', () => {
    // A missing runtime export has broken this project's Cloudflare build before.
    expect(readFileSync(PAGE, 'utf8')).toMatch(/export const runtime = 'edge'/);
  });
});

describe('a missing session is explained, not submitted into', () => {
  it('the page distinguishes "checking" from "no session"', () => {
    // Landing here without a session means the link expired, was already used, or was opened
    // in a different browser — all common and all indistinguishable to us. Showing a form
    // that cannot submit teaches somebody to doubt their new password rather than the link.
    const src = readFileSync(PAGE, 'utf8');
    expect(src).toContain('getSession');
    expect(src).toMatch(/ready === false/);
    expect(src).toContain('/forgot-password');
  });
});

describe('reset cannot be a route to a weaker password than signup allows', () => {
  /*
   * THE REASON THE RULES LIVE IN ONE MODULE. If reset were laxer than registration, "forgot
   * password" would be a documented bypass of the signup requirements rather than an
   * inconsistency. Two copies of a rule is how that happens.
   */
  it('rejects what registration rejects', () => {
    expect(passwordRules.safeParse('short1A').success).toBe(false);      // under 8
    expect(passwordRules.safeParse('alllowercase1').success).toBe(false); // no capital
    expect(passwordRules.safeParse('NoDigitsHere').success).toBe(false);  // no number
  });

  it('accepts what registration accepts', () => {
    expect(passwordRules.safeParse('Passw0rdd').success).toBe(true);
  });

  it('requires the confirmation to match', () => {
    expect(
      newPasswordSchema.safeParse({ password: 'Passw0rdd', confirmPassword: 'Passw0rdX' }).success,
    ).toBe(false);
    expect(
      newPasswordSchema.safeParse({ password: 'Passw0rdd', confirmPassword: 'Passw0rdd' }).success,
    ).toBe(true);
  });

  it('the register page uses the shared rules rather than its own copy', () => {
    // If register keeps a private schema, the two drift the moment either is tightened.
    const src = readFileSync(join(APP, '(auth)/register/page.tsx'), 'utf8');
    expect(src).toContain("from '@/lib/auth/password'");
  });
});
