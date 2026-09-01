import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * A scheme-less API URL must not break the build silently — src/lib/api-url-normalisation.test.ts
 *
 * THIS COST THREE DEPLOY CYCLES. `NEXT_PUBLIC_API_URL` and `INTERNAL_API_URL` were set to a bare
 * host — first `mock-interview.railway.internal`, then `mock-interview-production-2530.up.railway.app`
 * — with no `https://`. Both times the build died with:
 *
 *     `destination` does not start with `/`, `http://`, or `https://` for route
 *     {"source":"/api/v1/:path*","destination":"<host>/api/v1/:path*"}
 *     Error: Invalid rewrite found
 *
 * WHICH NAMES THE SYMPTOM AND NOT THE CAUSE. Nothing in that message says "your env var is
 * missing a scheme"; it talks about rewrites, so the natural reading is that the rewrite is
 * wrong rather than the value fed into it.
 *
 * AND THE SECOND FAILURE IS WORSE BECAUSE IT IS SILENT. `connectOrigins()` calls
 * `new URL(value).origin`, which THROWS on a bare host, and the catch deliberately drops it so
 * a malformed env var cannot take the build down. So even once the rewrite was fixed, the API
 * origin would have been missing from `connect-src` and the browser would have blocked every
 * API call — a site that loads perfectly and does nothing, with no build error to explain it.
 *
 * So `apiOrigin()` normalises a bare host to https:// and warns, rather than either accepting
 * something unusable or hard-failing a deploy over a missing eight characters.
 */

const CONFIG = readFileSync(join(process.cwd(), 'next.config.ts'), 'utf8');

/** The normaliser, mirrored here so the behaviour is asserted rather than eyeballed. */
function apiOrigin(value: string | undefined): string | undefined {
  if (!value) return undefined;
  const trimmed = value.trim().replace(/\/+$/, '');
  if (!trimmed) return undefined;
  if (/^https?:\/\//.test(trimmed)) return trimmed;
  if (trimmed.startsWith('/')) return trimmed;
  return `https://${trimmed}`;
}

describe('a scheme-less API URL is repaired, not rejected', () => {
  it('adds https:// to a bare host', () => {
    expect(apiOrigin('mock-interview-production-2530.up.railway.app')).toBe(
      'https://mock-interview-production-2530.up.railway.app',
    );
  });

  it('leaves a proper URL alone', () => {
    // THE VACUITY GUARD: a normaliser that rewrote everything would "pass" the test above
    // and would mangle every correct value.
    expect(apiOrigin('https://api.example.com')).toBe('https://api.example.com');
    expect(apiOrigin('http://localhost:8000')).toBe('http://localhost:8000');
  });

  it('strips a trailing slash, because the rewrite appends its own path', () => {
    // `${backendUrl}/api/v1/:path*` with a trailing slash gives //api/v1/... — which some
    // proxies treat as a different path and others redirect.
    expect(apiOrigin('https://api.example.com/')).toBe('https://api.example.com');
    expect(apiOrigin('api.example.com///')).toBe('https://api.example.com');
  });

  it('leaves a same-origin path alone', () => {
    // A relative destination is valid for a rewrite and must not acquire a host.
    expect(apiOrigin('/api')).toBe('/api');
  });

  it('treats empty and whitespace as unset', () => {
    expect(apiOrigin(undefined)).toBeUndefined();
    expect(apiOrigin('')).toBeUndefined();
    expect(apiOrigin('   ')).toBeUndefined();
  });

  it('produces something new URL() can parse, which is what the CSP needs', () => {
    // The silent half of the bug: connectOrigins() drops anything that throws here.
    for (const raw of ['mock-interview-production-2530.up.railway.app', 'api.example.com/']) {
      const normalised = apiOrigin(raw)!;
      expect(() => new URL(normalised)).not.toThrow();
      expect(new URL(normalised).origin).toBe(normalised);
    }
  });
});

describe('next.config.ts actually uses it', () => {
  it('normalises before building the rewrite destination', () => {
    // A helper nothing calls protects nothing — the exact failure docs/MISTAKES.md records
    // for NudgeDeck.
    expect(CONFIG).toContain('function apiOrigin');
    const rewrites = CONFIG.slice(CONFIG.indexOf('async rewrites()'));
    expect(rewrites).toMatch(/apiOrigin\(/);
  });

  it('normalises before building connect-src', () => {
    const origins = CONFIG.slice(
      CONFIG.indexOf('function connectOrigins'),
      CONFIG.indexOf('async rewrites()'),
    );
    expect(origins).toMatch(/apiOrigin\(/);
  });

  it('says so in the build log rather than fixing it invisibly', () => {
    // Silently repairing configuration is how a typo survives to production. The build
    // continues; the log records what was assumed.
    expect(CONFIG).toMatch(/console\.warn/);
  });
});
