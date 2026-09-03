import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * The CSP has to cover what the app actually loads — csp-covers-what-we-load.test.ts
 *
 * WHY THIS EXISTS, AND IT IS NOT HYPOTHETICAL. `security-headers.test.ts` asserts the policy
 * is RESTRICTIVE: no wildcards, the classic bypasses closed, frame-ancestors none. Every one
 * of those assertions passed while the policy was silently breaking three real features,
 * because "is this policy strict" and "does this policy permit the things we load" are
 * different questions and only the first one was being asked.
 *
 * All three were found by reading the source against the header rather than by anybody
 * noticing in a browser, which is the whole problem with a CSP violation: it is a line in a
 * console nobody has open.
 *
 *   TURNSTILE. `challenges.cloudflare.com` was in `frame-src` and `connect-src` and NOT in
 *   `script-src`, so the SDK `<script>` that `components/billing/Turnstile.tsx` injects was
 *   refused. Its own `onerror` handler resolves false and returns, so there is no exception
 *   and no visible error — the widget simply never renders. And `Offer.requires_captcha` is
 *   the control standing between a ₹1 launch offer and a script farming it, while the server
 *   refuses captcha-gated offers when Turnstile is unconfigured. The net effect was that
 *   every offer needing human verification was unbuyable AND the anti-abuse control was not
 *   running.
 *
 *   THE PRESENCE MONITOR. `hooks/usePresenceMonitor.ts` does a runtime
 *   `import(BUNDLE_URL)` of MediaPipe's ESM bundle from `cdn.jsdelivr.net`, fetches its WASM
 *   from the same host, and fetches a model from `storage.googleapis.com`. None of the three
 *   was in any directive. Eye contact and presence are a scored part of a communication
 *   round.
 *
 *   ANALYTICS. `posthog-js` is bundled from npm, so it needs no `script-src` — but it posts
 *   to `eu.i.posthog.com`, which was not in `connect-src`.
 *
 * SO THE FIX IS A REGISTRY, NOT FOUR MORE HOSTS. Every external origin the source refers to
 * has to be declared below with the directive it needs and the reason, and this file checks
 * BOTH directions: that each declared host is actually permitted, and that no host appears
 * in the source without being declared. Adding a third-party script and forgetting the CSP
 * now fails here instead of in a console nobody reads.
 */

const CONFIG = readFileSync(join(process.cwd(), 'next.config.ts'), 'utf8');

/**
 * The CSP directive list, as written in next.config.ts, with adjacent string literals
 * joined.
 *
 * THE JOIN MATTERS. A directive long enough to need wrapping is written as
 * `"script-src 'self' " + "https://a https://b"`, and a naive line-based search then finds
 * the directive on one line and its hosts on another — reporting every wrapped host as
 * missing. Which is a test that fails on formatting, and gets "fixed" by loosening it.
 */
const CSP = (() => {
  const start = CONFIG.indexOf("key: 'Content-Security-Policy'");
  const end = CONFIG.indexOf('].join(', start);
  if (start < 0 || end < 0) throw new Error('CSP directive list not found in next.config.ts');
  return CONFIG.slice(start, end).replace(/["']\s*\+\s*\n\s*["']/g, ' ');
})();

/** The `connectOrigins()` helper, which builds connect-src dynamically. */
const CONNECT_ORIGINS = (() => {
  const start = CONFIG.indexOf('function connectOrigins');
  const end = CONFIG.indexOf('\n}', start);
  if (start < 0) throw new Error('connectOrigins() not found in next.config.ts');
  return CONFIG.slice(start, end);
})();

/**
 * Every external origin the runtime source refers to, and what it needs.
 *
 * `directives` names where the host must appear. `connect` is satisfied either by a literal
 * in the CSP block or by `connectOrigins()`, which assembles that directive at build time.
 */
const EXTERNAL_ORIGINS: Array<{
  host: string;
  directives: Array<'script-src' | 'connect-src' | 'frame-src' | 'img-src'>;
  why: string;
}> = [
  {
    host: 'checkout.razorpay.com',
    directives: ['script-src', 'frame-src'],
    why: 'The payment SDK is a script that opens the card form in an iframe. Both, or the pay button appears to do nothing.',
  },
  {
    host: 'api.razorpay.com',
    directives: ['connect-src', 'frame-src'],
    why: 'The widget calls Razorpay from the page while the card form is open.',
  },
  {
    host: 'challenges.cloudflare.com',
    directives: ['script-src', 'connect-src', 'frame-src'],
    why: 'Turnstile: an injected <script>, the challenge iframe, and the POST of its result. Missing script-src is what made captcha-gated offers unbuyable.',
  },
  {
    host: 'cdn.jsdelivr.net',
    directives: ['script-src', 'connect-src'],
    why: "MediaPipe's ESM bundle is imported at runtime (script-src) and its WASM is fetched (connect-src). See usePresenceMonitor.ts.",
  },
  {
    host: 'storage.googleapis.com',
    directives: ['connect-src'],
    why: 'The face-landmarker model file, fetched by the presence monitor.',
  },
  {
    host: 'eu.i.posthog.com',
    directives: ['connect-src'],
    why: 'Analytics ingest. posthog-js is bundled from npm, so no script-src is needed.',
  },
];

/** Hosts that appear in source but are never loaded from — fixtures, copy, and links. */
const NOT_LOADED = new Set([
  // Test fixtures and doc examples.
  'evil.example',
  'evil.com',
  'attacker',
  'hotseat-login.example',
  'api.example.com',
  // The doc example for `ApiClientConfig.baseUrl`. Renamed from `api.hotseat.app` with the
  // rest of the stale brand; it is a comment, not a fetch.
  'api.interviewos.dev',
  // OUR OWN ORIGIN, in both its old and current form. These appear as the fallback for
  // `metadataBase` / `siteUrl()` — used to build canonical, OpenGraph and sitemap URLs, which
  // are strings in markup and an XML file, not fetches. The browser reaches this host as
  // `'self'`; no directive needs to name it.
  'interviewos.dev',
  'interviewos.net.in',
  // Rendered as <a href> for the reader to click. A link is not a load: no directive
  // governs where a user may navigate, and form-action already covers submissions.
  'www.linkedin.com',
  'www.google.com',
  'twitter.com',
  'wa.me',
  'aws.amazon.com',
]);

function sourceFiles(dir: string, found: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      sourceFiles(full, found);
    } else if (/\.(ts|tsx)$/.test(entry) && !/\.test\.tsx?$/.test(entry)) {
      found.push(full);
    }
  }
  return found;
}

/** Every `https://host` literal in non-test source. */
const HOSTS_IN_SOURCE = (() => {
  const hosts = new Set<string>();
  for (const file of sourceFiles(join(process.cwd(), 'src'))) {
    const text = readFileSync(file, 'utf8');
    for (const match of text.matchAll(/https:\/\/([a-zA-Z0-9._-]+)/g)) {
      hosts.add(match[1]);
    }
  }
  return hosts;
})();

/**
 * One directive's source list.
 *
 * Matched on the QUOTED start of the directive, not on the name appearing anywhere: the
 * policy is heavily commented and several comments name the directive they explain, so a
 * plain `includes('script-src')` finds a comment line and reports every host as missing.
 */
function directive(name: string): string {
  const line = CSP.split('\n').find(
    (l) => l.includes(`"${name} `) || l.includes(`'${name} `),
  );
  return line ?? '';
}

function permits(directive: string, host: string): boolean {
  if (directive === 'connect-src') {
    // connect-src is assembled by connectOrigins(); a host may be listed there instead.
    if (CONNECT_ORIGINS.includes(host)) return true;
    if (/connect-src/.test(CSP) && CSP.includes(host)) return true;
    return false;
  }
  const line = CSP.split('\n').find(
    (l) => l.includes(`"${directive} `) || l.includes(`'${directive} `),
  );
  return Boolean(line && line.includes(host));
}

describe('the CSP permits everything the app actually loads', () => {
  it('found the policy and the connect-src builder', () => {
    // Guards the guard: every assertion below passes trivially against an empty string.
    expect(CSP.length).toBeGreaterThan(200);
    expect(CONNECT_ORIGINS).toContain('origins.add');
    expect(HOSTS_IN_SOURCE.size).toBeGreaterThan(5);
  });

  for (const { host, directives, why } of EXTERNAL_ORIGINS) {
    for (const directive of directives) {
      it(`allows ${host} in ${directive} — ${why}`, () => {
        expect(
          permits(directive, host),
          `${host} is loaded by the app but is not permitted by ${directive}. ${why}`,
        ).toBe(true);
      });
    }
  }

  it('has no external origin in the source that nobody declared', () => {
    const declared = new Set(EXTERNAL_ORIGINS.map((o) => o.host));
    const undeclared = [...HOSTS_IN_SOURCE].filter(
      (host) => !declared.has(host) && !NOT_LOADED.has(host),
    );
    expect(
      undeclared,
      'these hosts appear in the source but are neither declared as loaded (with the CSP ' +
        'directives they need) nor listed as never-loaded. A third-party script added ' +
        'without a CSP entry fails silently in the browser, so it has to fail here.',
    ).toEqual([]);
  });

  it('still refuses a host nobody allowed', () => {
    // The negative. If `permits` returned true for everything the suite above is vacuous.
    expect(permits('script-src', 'cdn.malicious.example')).toBe(false);
    expect(permits('connect-src', 'cdn.malicious.example')).toBe(false);
  });
});

describe('the relaxations are the ones we meant', () => {
  it("keeps 'unsafe-eval' only while WebAssembly needs it", () => {
    /*
     * `unsafe-eval` was in the policy with no stated reason, and SECURITY-REVIEW.md flagged
     * it as possibly removable. It is NOT removable: MediaPipe compiles WebAssembly, and a
     * strict CSP blocks `WebAssembly.compile` without either `unsafe-eval` or the narrower
     * `wasm-unsafe-eval`. Removing it would silently disable presence detection.
     *
     * `wasm-unsafe-eval` is the correct narrowing and is what is asserted, so this policy
     * grants WASM compilation without granting `eval()` on strings.
     */
    const scriptSrc = directive('script-src');
    expect(scriptSrc).toContain("'wasm-unsafe-eval'");
    expect(scriptSrc, "plain 'unsafe-eval' grants eval() on arbitrary strings; wasm-unsafe-eval does not").not.toMatch(
      /'unsafe-eval'/,
    );
  });

  it('documents why img-src is wider than the <Image> allowlist', () => {
    /*
     * SR-2026Q3-02: the profile page renders `<img src={avatar_url}>` with a comment saying
     * avatars come from arbitrary hosts, while img-src allowed exactly three. So the feature
     * and the policy disagreed and every other avatar was silently hidden by the onError
     * handler.
     *
     * Resolved toward the feature rather than against it: an image cannot execute, the
     * avatar is rendered only on the owner's own profile page, and the alternative is
     * refusing a URL a candidate deliberately pasted. `https:` — not `*` — so the image
     * still cannot be fetched over plaintext.
     */
    const imgSrc = directive('img-src');
    expect(imgSrc).toMatch(/\bhttps:/);
    // No BARE wildcard source. A host pattern like `https://*.supabase.co` is a scoped
    // wildcard and is fine; a lone `*` is "any scheme, any host" and is not.
    expect(imgSrc.split(/\s+/)).not.toContain('*');
    expect(CSP).toMatch(/avatar/i);
  });
});
