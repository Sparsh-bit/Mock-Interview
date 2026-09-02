import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import { DEFAULT_REDIRECT, safeRedirect } from './safe-redirect';

/**
 * THE WIZARD BELONGS TO SIGNUP — lib/auth/onboarding-routing.test.ts
 *
 * WHAT WENT WRONG. Both the login fallback (`DEFAULT_REDIRECT`) and the middleware's
 * authenticated-on-an-auth-route rule pointed at `/welcome`, on the reasoning that the wizard
 * forwards to the dashboard by itself for anyone already set up. It does — but only on
 * `target_company && resume`, which is "finished onboarding", not "has an account". So every
 * user who skipped it, or set a target and never uploaded a resume, was handed all four steps
 * again on every login. The skip flag is `localStorage`, so skipping on a laptop did nothing
 * for the same person on a phone.
 *
 * Logging in means typing a password into an account that already exists. There is exactly one
 * place that knows an account is NEW — the signup confirmation link — so that is where the
 * wizard is now reached from, and nowhere else infers it.
 */

const read = (p: string) => readFileSync(join(process.cwd(), 'src', p), 'utf8');
/** Strip comments — this file's own prose explains the bug and must not satisfy a check for it. */
const code = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');

describe('a returning login lands on the dashboard', () => {
  it('the no-destination fallback is not the wizard', () => {
    expect(DEFAULT_REDIRECT).toBe('/dashboard');
  });

  it('the middleware does not send an authenticated visitor to the wizard', () => {
    const src = code(read('middleware.ts'));
    const rule = src.match(/if \(user && isAuthRoute\(pathname\)\) \{([\s\S]*?)\}/);
    expect(rule, 'the auth-route redirect was not found in middleware.ts').toBeTruthy();
    expect(rule![1]).toContain('/dashboard');
    expect(rule![1]).not.toContain('/welcome');
  });
});

describe('a new signup still reaches the wizard', () => {
  /* Guards the other direction: the fix above must not simply delete onboarding. */
  it('signUp points its confirmation link at /welcome', () => {
    const src = code(read('hooks/useAuth.ts'));
    const signUp = src.match(/const signUp = async[\s\S]*?\n  \};/);
    expect(signUp, 'signUp not found in useAuth.ts').toBeTruthy();
    expect(signUp![0]).toMatch(/emailRedirectTo/);
    expect(signUp![0]).toMatch(/next=\/welcome/);
  });

  it('and the wizard is still routable rather than removed', () => {
    expect(code(read('middleware.ts'))).toContain("'/welcome'");
  });
});

describe('the auth callback cannot be pointed off-site', () => {
  /*
   * `${origin}${next}` with `next` straight off the query string. Most payloads are inert once
   * an origin is prefixed, which is why this survived — but `@evil.com` is not.
   */
  it('rejects the userinfo payload that made concatenation exploitable', () => {
    // `<our-origin>` + `@evil.com` parses as userinfo@host, and the browser goes to the host.
    expect(safeRedirect('@evil.com')).toBe(DEFAULT_REDIRECT);
    expect(safeRedirect('@evil.com/path')).toBe(DEFAULT_REDIRECT);
  });

  it('the callback actually routes next through safeRedirect', () => {
    const src = code(read('app/auth/callback/route.ts'));
    expect(src).toMatch(/safeRedirect\(\s*searchParams\.get\('next'\)/);
    // The raw value must not survive to the redirect.
    expect(src).not.toMatch(/const next = searchParams\.get\('next'\)\s*\?\?/);
  });

  it('still defaults a link with no next at all to the reset-password destination', () => {
    expect(safeRedirect('/settings')).toBe('/settings');
    expect(safeRedirect('/reset-password')).toBe('/reset-password');
  });
});
