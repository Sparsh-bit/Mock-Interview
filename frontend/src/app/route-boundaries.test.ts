import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * Every route group has a loading and an error boundary — app/route-boundaries.test.ts
 *
 * REPORTED FROM PRODUCTION: "sometimes the main deployed software gets freezed and the
 * sidebar options does not respond". Nothing was frozen and no click was lost. This app had
 * NO `loading.tsx` and NO `error.tsx` anywhere in it — not one file — and in the App Router
 * those two absences produce that one symptom from opposite directions.
 *
 * WITHOUT `loading.tsx` there is no Suspense boundary for the segment, so Next holds the
 * current page on screen until the next one's payload arrives from the server and paints
 * nothing in between. Every page in the dashboard group is dynamic and edge-rendered, so
 * every sidebar click is a network round trip; the old page stays fully drawn, and the active
 * pill does not move because it is driven by `usePathname()`, which only changes once the
 * navigation commits. The click therefore has no visible consequence at all. In production
 * this was much worse than in development for a reason outside the frontend: the backend
 * sleeps when idle, so the first navigation after a quiet spell waits on a cold start.
 *
 * WITHOUT `error.tsx` a segment that throws unmounts the tree above it, which includes the
 * sidebar. "The sidebar does not respond" is then literally true — there is no sidebar, and
 * the only way out is a manual reload.
 *
 * WHY THESE ARE FILE-EXISTENCE ASSERTIONS. Because the bug was a missing file, and the
 * framework's behaviour is keyed on the filename. No amount of testing a component catches
 * "the convention file is not there", and nothing else in lint, tsc, vitest or `next build`
 * says a word about it — the build output for this app was completely green while every
 * navigation in it was silent.
 */

const APP = join(process.cwd(), 'src/app');

/** Route groups that own their own full-page shell and can therefore fail independently. */
const GROUPS = ['(dashboard)', '(interview)'] as const;

describe('a slow navigation shows something', () => {
  it('the dashboard group has a loading boundary', () => {
    // The group where this was reported. Fifteen routes hang off it and all of them are
    // server-rendered on demand, so all of them were silent on click.
    expect(existsSync(join(APP, '(dashboard)', 'loading.tsx'))).toBe(true);
  });

  it('the loading fallback mirrors the page shell rather than being a bare spinner', () => {
    // A centred spinner on an empty page reads as "the app has gone away". Blocks where the
    // content will be read as "it is coming", and they stop the layout jumping on arrival.
    const src = readFileSync(join(APP, '(dashboard)', 'loading.tsx'), 'utf8');
    expect(src).toMatch(/animate-pulse/);
    expect(src).toMatch(/aria-busy/);
  });
});

describe('a failed segment does not take the app with it', () => {
  for (const group of GROUPS) {
    it(`${group} has an error boundary`, () => {
      expect(existsSync(join(APP, group, 'error.tsx'))).toBe(true);
    });

    it(`${group}'s boundary is a client component and offers a retry`, () => {
      const src = readFileSync(join(APP, group, 'error.tsx'), 'utf8');
      // `error.tsx` MUST be a client component — it takes `reset`, a function prop, which a
      // server component cannot receive. Without the directive the build fails, so this is
      // really documentation of why the directive is not removable.
      expect(src).toMatch(/^'use client';/);
      // `reset()` re-renders the segment without a full reload. Most failures on these pages
      // are a transient fetch against a backend that sleeps, so the second attempt usually
      // works — and a reload would throw away the router cache and every warm query to
      // achieve the same thing.
      expect(src).toContain('reset');
    });

    it(`${group}'s boundary says nothing about the deployment`, () => {
      // A user cannot act on a component name or an upstream host, and naming either tells
      // whoever is reading how this thing is built. The two things they CAN act on are retry
      // and leave. `digest` is a hash, which is the one safe thing to show.
      const src = readFileSync(join(APP, group, 'error.tsx'), 'utf8');
      for (const leak of ['onrender.com', 'supabase.co', 'Cloudflare', 'Render']) {
        expect(src).not.toContain(leak);
      }
    });
  }

  it('there is a global boundary for the root layout itself', () => {
    // A group boundary lives INSIDE the root layout, so it cannot catch that layout failing.
    // When the root throws there is no shell left, which is why this file supplies its own
    // <html> and <body>.
    const path = join(APP, 'global-error.tsx');
    expect(existsSync(path)).toBe(true);
    const src = readFileSync(path, 'utf8');
    expect(src).toMatch(/<html/);
    expect(src).toMatch(/<body/);
  });

  it('the global boundary imports no component library', () => {
    // Every reason the root layout can fail is a reason the component library or the
    // Tailwind layer might also be unavailable. An error screen that fails for the same
    // cause as the error is not an error screen, so this one uses inline styles and imports
    // nothing from @/components.
    const src = readFileSync(join(APP, 'global-error.tsx'), 'utf8');
    expect(src).not.toMatch(/from '@\/components/);
  });
});

describe('a wrong URL lands somewhere that looks like the product', () => {
  /**
   * WHAT THIS REPLACED: Next.js's built-in 404 — "404: This page could not be found." in the
   * framework's own type, on a white page, with no branding and no link anywhere.
   *
   * On a public product that is what a candidate sees after a mistyped URL or a stale link
   * someone shared, and it reads as a broken deployment rather than as a wrong address. Those
   * are materially different conclusions to reach about something you were about to pay for.
   */
  it('a custom not-found page exists', () => {
    expect(existsSync(join(APP, 'not-found.tsx'))).toBe(true);
  });

  it('it is branded and offers a way out', () => {
    const src = readFileSync(join(APP, 'not-found.tsx'), 'utf8');
    // EITHER brand component satisfies this. The property is "somebody landing here can see
    // whose product it is", not "this page uses the component it happened to use the day the
    // test was written" — asserting the narrower thing failed the moment the page was
    // upgraded from the small `Wordmark` to the full `Lockup`, which made it MORE branded.
    expect(src, 'the 404 renders no brand mark at all').toMatch(/<(Lockup|Wordmark|BrandmarkArt)\b/);
    // TWO routes, not one: the reader is either signed in and mis-navigated, or arrived from
    // outside on a dead link. Offering only one of those strands the other.
    expect(src).toContain('href="/dashboard"');
    expect(src).toContain('href="/"');
  });

  it('it says nothing about the deployment', () => {
    /*
     * Same rule the error boundaries are held to above, and for the same reason: a hostname or
     * an internal path on an error screen is a free map of the infrastructure, handed to
     * whoever typed the wrong URL.
     *
     * COMMENTS STRIPPED FIRST — and this assertion failed on correct code before I did that,
     * because the comment above explaining why traces must not leak contained the very word it
     * was banning. That is the fourth time in this repository a source scan has matched the
     * prose describing the rule rather than the code breaking it (docs/MISTAKES.md P5).
     */
    const src = readFileSync(join(APP, 'not-found.tsx'), 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
      .replace(/\/\/.*$/gm, '')
      .toLowerCase();
    for (const leak of ['onrender.com', 'pages.dev', 'supabase.co', 'localhost', 'stacktrace', '.env']) {
      expect(src, `the 404 page mentions ${leak}`).not.toContain(leak);
    }
  });
});
