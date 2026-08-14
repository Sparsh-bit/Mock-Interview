import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * One account must never see another account's data — components/account-isolation.test.ts
 *
 * REPORTED FROM A REAL SESSION, and it is the most serious bug this app has had: signing in
 * as a second account showed the FIRST account's name, session history, statistics, credit
 * balance and admin navigation. It read as "the two accounts have been merged in the
 * database". Nothing was merged; nothing server-side was wrong at all.
 *
 * TanStack Query caches by query key, and none of the keys carry a user id — `['user-stats']`,
 * `['user-profile']`, `['user-sessions', limit]`, `['billing', 'balance']`, `['is-admin']`.
 * The QueryClient lives for the lifetime of the tab. So signing out and back in as somebody
 * else left every entry in place, and each was served to the new account until it happened to
 * refetch. With `staleTime` at a minute, that is a minute of one person reading another
 * person's data — including whether they are an admin, which changes what the app looks like.
 *
 * THE FIX IS AT THE IDENTITY BOUNDARY, NOT IN THE KEYS. Adding a user id to all twenty keys
 * would work and would be the wrong shape: it puts the burden on every hook forever, the
 * failure mode for forgetting is silent, and forgetting produces exactly this. One rule in
 * one place covers the keys that do not exist yet.
 *
 * These are source assertions. The real test would mount the provider tree, swap the Supabase
 * session and assert the cache emptied — worth building, and weaker than nothing is not the
 * bar here: this catches the specific regression, which is somebody removing the clear during
 * a refactor and every existing test still passing.
 */

const PROVIDERS = readFileSync(
  join(process.cwd(), 'src/components/providers.tsx'),
  'utf8',
);
const SIDEBAR = readFileSync(
  join(process.cwd(), 'src/components/layout/Sidebar.tsx'),
  'utf8',
);

/** Comments stripped, so no assertion can match its own explanation. */
const strip = (s: string) =>
  s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');

const PROVIDERS_CODE = strip(PROVIDERS);
const SIDEBAR_CODE = strip(SIDEBAR);

describe('the query cache is emptied when the account changes', () => {
  it('subscribes to auth state changes', () => {
    expect(PROVIDERS_CODE).toContain('onAuthStateChange');
  });

  it('clears rather than invalidates', () => {
    // `invalidateQueries` marks entries stale but KEEPS them, and a stale entry is still
    // rendered while its refetch is in flight — so the new account would still see the
    // previous one's name and numbers for as long as the network takes. Removing them shows
    // a loading state instead, which is the only honest thing to show somebody whose data
    // has not arrived.
    expect(PROVIDERS_CODE).toMatch(/queryClient\.clear\(\)/);
    expect(PROVIDERS_CODE).not.toMatch(/invalidateQueries[\s\S]{0,80}applyIdentity/);
  });

  it('compares the user id rather than reacting to the event', () => {
    // Supabase fires SIGNED_IN and TOKEN_REFRESHED routinely for the SAME user — on tab
    // focus, on every token refresh. Clearing on those would throw away good data constantly
    // and refetch the whole dashboard for no reason.
    expect(PROVIDERS_CODE).toMatch(/seenUserId/);
    expect(PROVIDERS_CODE).toMatch(/if \(seenUserId\.current === userId\) return;/);
  });

  it('does not clear on the first observation of a tab', () => {
    // Nothing is cached from anybody else yet on a fresh load, so clearing there is a wasted
    // refetch of every query on every page load.
    expect(PROVIDERS_CODE).toMatch(/seenUserId\.current === undefined/);
  });

  it('treats signing out as an identity change too', () => {
    // Signing out must empty the cache as surely as switching accounts: the next person to
    // use the browser is a different identity even if they never sign in.
    expect(PROVIDERS_CODE).toMatch(/session\?\.user\?\.id \?\? null/);
  });
});

describe('admin navigation cannot be shown to a normal account', () => {
  it('the admin probe is keyed by user', () => {
    // Defence in depth on the one key whose staleness changes what the application looks
    // like. A cached `true` shows a normal account the Users, Offers and AI cost pages.
    expect(SIDEBAR_CODE).toMatch(/queryKey: \['is-admin', userId\]/);
  });

  it('it fails closed — anything other than an explicit true is not an admin', () => {
    // A 403 leaves `data` undefined, and so does a request still in flight. Both must render
    // as "not an admin" rather than as "not yet known".
    expect(SIDEBAR_CODE).toMatch(/return data === true;/);
  });

  it('the admin links are a separate list, not mixed into the default nav', () => {
    // If they were in NAV_ITEMS with a flag, the flag is one bad render away from showing
    // them. Keeping them in a list that is concatenated only when isAdmin holds means the
    // default state cannot include them.
    expect(SIDEBAR_CODE).toMatch(/export const ADMIN_NAV_ITEMS/);
    expect(SIDEBAR_CODE).toMatch(/isAdmin\s*\?\s*\[\.\.\.baseItems, \.\.\.ADMIN_NAV_ITEMS\]/);
  });

  it('covers all three admin pages', () => {
    for (const href of ['/admin', '/admin/offers', '/ai-usage']) {
      expect(SIDEBAR_CODE).toContain(href);
    }
  });
});
