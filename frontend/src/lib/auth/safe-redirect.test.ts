import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import { DEFAULT_REDIRECT, safeRedirect } from './safe-redirect';

/**
 * An open redirect after login — safe-redirect.test.ts
 *
 * The victim arrives on the real domain, sees the real certificate, types their real password
 * into the real form, and is delivered to a copy that asks them to confirm it. Everything they
 * have been taught to check is genuine. That is why this is worth a table of cases rather than
 * one assertion: the bypasses are all in how a BROWSER re-reads a string, not in how it looks.
 */

describe('a destination inside the site is kept', () => {
  it.each([
    '/dashboard',
    '/interview',
    '/report/8b0f5c2e-1f4a-4c9a-9a5e-2f1d3c4b5a60',
    '/pricing#apply-offer',
    '/tracks?company=cognizant',
    '/foo:bar',
  ])('%s', (path) => {
    expect(safeRedirect(path)).toBe(path);
  });

  it('keeps the query and the hash, because that is usually the destination', () => {
    // The middleware sends people back to the page they asked for. Dropping the query would
    // land a candidate on a filtered list with the filter gone.
    expect(safeRedirect('/tracks?company=cognizant&role=java#top')).toBe(
      '/tracks?company=cognizant&role=java#top',
    );
  });
});

describe('a destination outside the site is refused', () => {
  it.each([
    ['an absolute url', 'https://evil.example'],
    ['no scheme, still absolute', '//evil.example'],
    ['protocol relative with a path', '//evil.example/login'],
    ['backslash, which browsers normalise to a slash', '/\\evil.example'],
    ['both slashes flipped', '\\\\evil.example'],
    ['a script url', 'javascript:alert(1)'],
    ['a data url', 'data:text/html,<script>alert(1)</script>'],
    ['leading whitespace, which the browser strips', '  //evil.example'],
    ['an embedded tab, which the browser strips', '/\t/evil.example'],
    ['a newline, which the browser strips', '/\n/evil.example'],
    ['scheme smuggled after a slash', '/https://evil.example'],
    ['no leading slash at all', 'evil.example'],
    ['a bare scheme', 'http:'],
  ])('%s: %j', (_name, value) => {
    expect(safeRedirect(value)).toBe(DEFAULT_REDIRECT);
  });

  it('falls back for anything missing', () => {
    expect(safeRedirect(null)).toBe(DEFAULT_REDIRECT);
    expect(safeRedirect(undefined)).toBe(DEFAULT_REDIRECT);
    expect(safeRedirect('')).toBe(DEFAULT_REDIRECT);
    expect(safeRedirect('   ')).toBe(DEFAULT_REDIRECT);
  });

  it('never returns something that could resolve to another origin', () => {
    // The property, stated once over everything above: whatever comes back either IS the
    // default or begins with exactly one slash. Nothing else can be an authority.
    const hostile = [
      'https://evil.example',
      '//evil.example',
      '/\\evil.example',
      '\\\\evil.example',
      'javascript:alert(1)',
      '  //evil.example',
      '/\t/evil.example',
    ];
    for (const value of hostile) {
      const out = safeRedirect(value);
      expect(out).toBe(DEFAULT_REDIRECT);
      expect(out.startsWith('//')).toBe(false);
      expect(out).not.toMatch(/:\/\//);
    }
  });
});

describe('the login page actually uses it', () => {
  /*
   * A TESTED FUNCTION NOBODY CALLS IS NOT A FIX, and this file was one assertion away from
   * being exactly that. Everything above passes with `safeRedirect` sitting unused and the
   * login page pushing the raw query value — verified by reverting the call site, where all
   * 22 tests stayed green.
   *
   * So the call site is pinned too. Source-level rather than a rendered test because the
   * vitest environment here is `node`: this page mounts next/navigation and react-hook-form
   * and cannot be rendered at all, and the thing worth pinning is not the markup — it is that
   * the value reaching router.push has been through the validator.
   */
  const PAGE = readFileSync(
    join(process.cwd(), 'src/app/(auth)/login/page.tsx'),
    'utf8',
  ).replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');

  it('reads the query parameter through safeRedirect', () => {
    expect(PAGE).toMatch(/safeRedirect\(\s*searchParams\.get\('redirectTo'\)\s*\)/);
  });

  it('never assigns the raw query value to the destination', () => {
    // The exact line that was there before. If it comes back, so does the vulnerability.
    expect(PAGE).not.toMatch(/redirectTo\s*=\s*searchParams\.get\('redirectTo'\)/);
  });

  it('pushes the validated value and nothing else', () => {
    expect(PAGE).toMatch(/router\.push\(redirectTo\)/);
    expect(PAGE).not.toMatch(/router\.push\(\s*searchParams/);
  });
});
