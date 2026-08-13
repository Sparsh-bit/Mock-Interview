import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * The security headers, and what is honestly achievable.
 *
 * Reported: "make sure that the software can never be hacked and also no one can inspect and
 * see that how it is made and how it is working as no key must be exposed in the public", and
 * separately "add some kind of security that no one can reverse enginner it".
 *
 * TWO OF THOSE THREE ARE ACHIEVABLE AND ARE TESTED HERE. The third is not, and pretending
 * otherwise in a test file would be the wrong kind of reassurance:
 *
 *   NO KEY EXPOSED — achievable, and currently true. The only secret-shaped value the browser
 *   receives is the Supabase ANON key, which is designed to be public: it identifies the
 *   project and authorises nothing on its own, because every table is behind Row Level
 *   Security (pinned separately by the backend's test_rls_coverage.py). Service keys, the JWT
 *   secret, AI provider keys and Razorpay's secret are backend-only and never cross the
 *   NEXT_PUBLIC_ boundary. `.env.example` holds placeholders, not real values.
 *
 *   HARDER TO ATTACK — achievable, incrementally, and that is what these headers are.
 *
 *   IMPOSSIBLE TO INSPECT OR REVERSE ENGINEER — not achievable for a web application, and no
 *   configuration changes that. Frontend code runs on the user's machine, so it must be
 *   delivered to the user's machine, so it can be read. Minification and obfuscation raise the
 *   effort; they do not prevent it. What DOES protect the product is architectural and already
 *   holds: the prompts, question banks, scoring, plan builder and billing rules live in the
 *   backend. A competitor reading the entire client bundle learns the layout and the API shape,
 *   not how the interview is generated or graded. Turning off source maps (asserted below) is
 *   the part of this that is real — with maps shipped, the bundle reads as original TypeScript
 *   including comments.
 */

const CONFIG = readFileSync(join(process.cwd(), 'next.config.ts'), 'utf8');

/**
 * Just the CSP directive list, extracted from the source.
 *
 * EXTRACTED RATHER THAN COMMENT-STRIPPED, and the two failed attempts that led here are worth
 * recording because both are easy to repeat:
 *
 *   Asserting against the raw file made the negative checks fail, because the config's own
 *   comment explains why a wildcard connect-src would be wrong — the assertion read the
 *   explanation of the rule as a violation of it.
 *
 *   Stripping comments then broke the positive checks, because a non-greedy block-comment
 *   regex mispairs `/*` with a later `*` + `/` and silently ate the Permissions-Policy line.
 *
 * Taking the array literal is exact: it is comment-free by construction, and it is the thing
 * the assertions are actually about.
 */
const CSP = (() => {
  const start = CONFIG.indexOf("default-src 'self'");
  const end = CONFIG.indexOf('upgrade-insecure-requests', start);
  if (start < 0 || end < 0) throw new Error('CSP directive list not found in next.config.ts');
  return CONFIG.slice(start, end);
})();

describe('response headers', () => {
  it('does not advertise the framework', () => {
    // Names the framework and therefore the CVE list worth trying.
    expect(CONFIG).toMatch(/poweredByHeader:\s*false/);
  });

  it('ships no browser source maps in production', () => {
    // Next's default, set explicitly because a default is the kind of thing that gets flipped
    // on during a debugging session and left on.
    expect(CONFIG).toMatch(/productionBrowserSourceMaps:\s*false/);
  });

  it('sends HSTS', () => {
    // Campus wifi is the network this product runs on; without HSTS the first request of a
    // session is strippable to plain HTTP.
    expect(CONFIG).toMatch(/Strict-Transport-Security/);
    expect(CONFIG).toMatch(/includeSubDomains/);
  });

  it('sends a CSP that restricts where scripts may come from', () => {
    expect(CONFIG).toMatch(/Content-Security-Policy/);
    expect(CSP).toMatch(/default-src 'self'/);
    // The value that survives the 'unsafe-inline' concession: an injected
    // <script src="https://attacker/..."> is still refused, because the host is not allowed.
    expect(CSP).toMatch(/script-src 'self'/);
    // No directive may fall back to a bare wildcard, which would make the whole policy
    // decorative. Scoped to one directive at a time: `img-src ... https://*.supabase.co` is a
    // legitimate host wildcard, whereas `img-src *` is not, and only a per-directive scan can
    // tell those apart.
    for (const directive of CSP.split(';')) {
      expect(directive.trim()).not.toMatch(/-src\s+\*/);
    }
  });

  it('closes the classic CSP bypasses', () => {
    expect(CSP).toMatch(/object-src 'none'/);
    expect(CSP).toMatch(/base-uri 'self'/);
    expect(CSP).toMatch(/frame-ancestors 'none'/);
  });

  it('does not allow connect-src to be a wildcard', () => {
    // A hardcoded origin list would be wrong in production, and the tempting fix is
    // `connect-src *`, which is the same as having no rule at all. It is derived instead.
    expect(CONFIG).toMatch(/connectOrigins\(\)/);
    expect(CSP).not.toMatch(/connect-src \*/);
  });

  it('still permits the things the interview genuinely needs', () => {
    /*
     * A policy that breaks the product is worse than no policy, because it gets reverted
     * wholesale rather than fixed. Three specific allowances, each load-bearing:
     *   blob: in media-src — neural TTS audio plays from an object URL, so without it the
     *          panel is silent.
     *   mediastream: — the presence check reads a camera track.
     *   camera/microphone in Permissions-Policy — an empty allowlist blocks getUserMedia
     *          before any app code runs.
     */
    expect(CSP).toContain("media-src 'self' blob: mediastream:");
    expect(CONFIG).toMatch(/camera=\(self\), microphone/);
    expect(CONFIG).toMatch(/microphone=\(self\), geolocation/);
  });
});

describe('what the browser is allowed to know', () => {
  it('exposes no secret-bearing env var to the client', () => {
    /*
     * The NEXT_PUBLIC_ prefix is the whole boundary: anything carrying it is compiled into the
     * bundle and is public by definition. This asserts that nothing secret has been given that
     * prefix — which is the mistake that actually happens, usually while debugging a 401.
     *
     * SUPABASE_ANON_KEY is the deliberate exception and is safe: it authorises nothing by
     * itself, because access is decided by Row Level Security on every table.
     */
    const SRC = readFileSync(join(process.cwd(), 'src/lib/supabase/client.ts'), 'utf8');
    const publicVars = [
      ...CONFIG.matchAll(/NEXT_PUBLIC_[A-Z_]+/g),
      ...SRC.matchAll(/NEXT_PUBLIC_[A-Z_]+/g),
    ].map((m) => m[0]);
    for (const name of publicVars) {
      expect(name).not.toMatch(/SERVICE|SERVICE_ROLE|SECRET|PRIVATE|PASSWORD/);
    }
  });
});
