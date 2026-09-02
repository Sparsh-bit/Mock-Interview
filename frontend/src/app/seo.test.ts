import { describe, expect, it } from 'vitest';

import robots from './robots';
import sitemap from './sitemap';

/**
 * Crawler directives and the canonical host — app/seo.test.ts
 *
 * WHAT WAS MISSING. The root layout's metadata is thorough — title template, description,
 * keywords, openGraph, twitter, robots — but there was no `robots.txt` and no `sitemap.xml` at
 * all, so nothing told a crawler which paths matter, which are private, or where the sitemap
 * is. Next generates both from these two files; there is no reason to hand-maintain either.
 *
 * THE PART THAT MATTERS MOST IS THE HOST. `metadataBase` reads `NEXT_PUBLIC_APP_URL`, which in
 * production was set to the Cloudflare Pages subdomain rather than the real domain — so every
 * canonical, OG and Twitter URL pointed at `*.pages.dev`. Two hosts serving identical content
 * with no canonical signal is the classic duplicate-content split, and the OG cards named the
 * wrong site. These functions read the same variable, so they inherit the fix rather than
 * needing their own copy of the domain.
 */

const AUTH_ONLY = ['/dashboard', '/welcome', '/settings', '/profile', '/session', '/report', '/admin', '/r/'];

describe('robots.txt', () => {
  it('allows crawling and points at the sitemap', () => {
    const r = robots();
    expect(r.sitemap).toMatch(/\/sitemap\.xml$/);
    const rules = Array.isArray(r.rules) ? r.rules : [r.rules];
    expect(rules[0]?.allow).toBe('/');
  });

  /** robots.rules is a single object or an array of them; normalise once. */
  const disallowedPaths = (): string[] => {
    const { rules } = robots();
    const list = Array.isArray(rules) ? rules : [rules];
    return list.flatMap((r) => {
      const d = r?.disallow;
      return d === undefined ? [] : Array.isArray(d) ? d : [d];
    });
  };

  it('keeps crawlers out of everything behind a login', () => {
    /*
     * Not a security control — middleware already redirects, and these tests do not pretend
     * otherwise. It stops a crawler spending its budget on paths that only ever redirect, and
     * stops a login screen being indexed as thin content under a dozen different URLs.
     */
    const disallow = disallowedPaths();
    for (const path of AUTH_ONLY) {
      expect(disallow.some((d) => path.startsWith(d.replace(/\*$/, '')))).toBe(true);
    }
  });

  it('does not disallow the public pages', () => {
    // THE VACUITY GUARD: a robots.txt that disallowed everything would satisfy the rule above
    // and would delist the entire site.
    const disallow = disallowedPaths();
    for (const keep of ['/', '/pricing', '/privacy', '/terms']) {
      expect(disallow).not.toContain(keep);
    }
  });
});

describe('sitemap.xml', () => {
  it('lists every public page and nothing private', () => {
    const urls = sitemap().map((e) => new URL(e.url).pathname);
    for (const path of ['/', '/pricing', '/demo', '/privacy', '/terms', '/refund', '/grievance']) {
      expect(urls).toContain(path);
    }
    for (const priv of AUTH_ONLY) {
      expect(urls.some((u) => u.startsWith(priv))).toBe(false);
    }
  });

  it('uses absolute URLs on one host', () => {
    // A sitemap of relative paths is invalid, and a sitemap split across two hosts is the
    // duplicate-content problem restated.
    const hosts = new Set(sitemap().map((e) => new URL(e.url).host));
    expect(hosts.size).toBe(1);
  });

  it('ranks the landing page above the legal pages', () => {
    const byPath = new Map(sitemap().map((e) => [new URL(e.url).pathname, e]));
    expect(byPath.get('/')!.priority!).toBeGreaterThan(byPath.get('/privacy')!.priority!);
  });

  it('carries a lastModified so a re-crawl has something to compare', () => {
    for (const entry of sitemap()) expect(entry.lastModified).toBeTruthy();
  });
});
