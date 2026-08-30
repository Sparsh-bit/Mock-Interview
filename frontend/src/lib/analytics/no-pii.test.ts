import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import { ALLOWED_PROPERTIES, EVENTS, isForbiddenKey } from './events';

/**
 * The vendor's defaults, and the call sites — lib/analytics/no-pii.test.ts
 *
 * WHY SOURCE ASSERTIONS, THE SAME ARGUMENT `lib/legal/consent.test.ts` MAKES. Every rule
 * here is about something being ABSENT — no autocapture, no pageview capture, no session
 * replay, no second place that turns tracking on, no PII in a property bag. An absence
 * renders identically whether it is deliberate or accidental, so it has to be asserted
 * deliberately or it erodes. `autocapture: true` added back later would break nothing that
 * any behavioural test could see; it would simply start shipping the text of every element a
 * candidate clicks, which in this product includes their answers.
 *
 * `core.test.ts` covers the gate's behaviour with a recording sink. This file covers the
 * parts that only exist as configuration and as call-site discipline.
 */

const read = (rel: string) => readFileSync(join(process.cwd(), rel), 'utf8');

/**
 * Source with comments stripped, so a rule's own explanation does not read as a violation of
 * it. Same trap and same character-scanner approach as `lib/legal/consent.test.ts` and
 * `lib/security-headers.test.ts` — a regex over source cannot tell a string from a comment.
 */
function stripComments(source: string): string {
  let out = '';
  let i = 0;
  while (i < source.length) {
    const two = source.slice(i, i + 2);
    if (two === '//') {
      const nl = source.indexOf('\n', i);
      if (nl < 0) break;
      i = nl;
    } else if (two === '/*') {
      const end = source.indexOf('*/', i + 2);
      i = end < 0 ? source.length : end + 2;
    } else if (source[i] === "'" || source[i] === '"' || source[i] === '`') {
      const quote = source[i];
      out += source[i];
      i += 1;
      while (i < source.length && source[i] !== quote) {
        if (source[i] === '\\') {
          out += source.slice(i, i + 2);
          i += 2;
          continue;
        }
        out += source[i];
        i += 1;
      }
      out += quote;
      i += 1;
    } else {
      out += source[i];
      i += 1;
    }
  }
  return out;
}

const POSTHOG = stripComments(read('src/lib/analytics/posthog.ts'));
const GATE = stripComments(read('src/components/analytics/AnalyticsGate.tsx'));
const REGISTER = stripComments(read('src/app/(auth)/register/page.tsx'));

describe('the vendor is configured to collect nothing on its own', () => {
  it.each([
    [
      'autocapture: false',
      'autocapture records the TEXT of clicked elements — question text, panel dialogue, and the file name of an uploaded resume, which is usually the candidate’s own name',
    ],
    [
      'capture_pageview: false',
      'URLs here carry report ids, session ids and question ids — a pageview stream is a list of which reports a named person opened',
    ],
    ['capture_pageleave: false', 'the same URLs, on the way out'],
    ['capture_performance: false', 'web-vitals payloads carry the full URL'],
    ['disable_session_recording: true', 'replay records the resume, the answers and the report'],
    ['disable_surveys: true', 'a survey is free text typed by a candidate'],
    [
      'disable_external_dependency_loading: true',
      'a bundle fetched from the vendor CDN at runtime is a script the CSP was not written against',
    ],
    [
      "person_profiles: 'identified_only'",
      'otherwise a profile exists at the vendor for every visitor, consented or not',
    ],
    [
      "persistence: 'localStorage'",
      'not the default localStorage+cookie — a cookie is sent to the vendor on every request',
    ],
  ])('sets %s', (setting) => {
    expect(POSTHOG).toContain(setting);
  });

  it('strips the vendor’s own URL and IP properties before the payload is built', () => {
    // These are attached automatically to EVERY event regardless of what we pass, so
    // `scrubProperties` cannot reach them. They are the same identifiers that
    // `capture_pageview: false` exists to keep out, arriving by a different door.
    for (const property of ['$current_url', '$referrer', '$referring_domain', '$pathname', '$ip']) {
      expect(POSTHOG).toContain(`delete out.${property}`);
    }
  });

  it('does nothing at all without a configured key', () => {
    expect(POSTHOG).toContain('if (!key || typeof window === \'undefined\') return null;');
  });

  it('clears the stored identifier on withdrawal', () => {
    expect(POSTHOG).toContain('opt_out_capturing()');
    expect(POSTHOG).toContain('reset()');
  });

  it('is loaded with a dynamic import so an unconsented page never downloads it', () => {
    expect(POSTHOG).toContain("import('posthog-js')");
    expect(POSTHOG).not.toMatch(/^import posthog/m);
  });
});

describe('only one thing may turn tracking on', () => {
  it('is the gate, and nothing else calls setConsent', () => {
    // Every other module gets `track`, which is inert until the gate has spoken. A second
    // caller of `setConsent` would be a second place the rule could be got wrong, and the
    // one that matters — a component granting consent because a local flag says so.
    const callers = ['src/hooks', 'src/app', 'src/components', 'src/lib']
      .flatMap((dir) => filesUnder(dir))
      .filter((file) => !file.includes('analytics/core'))
      .filter((file) => !file.endsWith('.test.ts') && !file.endsWith('.test.tsx'))
      .filter((file) => stripComments(read(file)).includes('setConsent('));

    expect(callers.sort()).toEqual(
      [
        'src/app/(auth)/register/page.tsx',
        'src/components/analytics/AnalyticsGate.tsx',
      ].sort()
    );
  });

  it('the gate treats a never-asked consent as a refusal', () => {
    // `null` from the endpoint means the question was never put to this account. Reading it
    // as a grant would track everybody who signed up before the checkbox existed.
    expect(GATE).toContain("granted === true ? 'granted' : 'denied'");
  });

  it('the gate turns everything off when nobody is signed in', () => {
    expect(GATE).toContain("analytics.setConsent('unknown', null)");
  });

  it('signup only tracks when the optional box was actually ticked', () => {
    // The one event that fires before the gate has read the server, so it carries its own
    // check. It must be guarded by the form value, not by anything else.
    expect(REGISTER).toContain('if (data.analytics)');
    const guardIndex = REGISTER.indexOf('if (data.analytics)');
    const trackIndex = REGISTER.indexOf('track(EVENTS.SIGNUP)');
    expect(trackIndex).toBeGreaterThan(guardIndex);
  });

  it('signup records the consent before it sends the event', () => {
    // The ledger row is what makes the tracking lawful, so it may not follow the event.
    expect(REGISTER.indexOf("'/api/v1/legal/consent/signup'")).toBeLessThan(
      REGISTER.indexOf('track(EVENTS.SIGNUP)')
    );
  });

  it('the analytics checkbox has no default and is not required', () => {
    // `defaultChecked` is a pre-ticked box, which §6 names explicitly as not consent.
    // `z.literal(true)` would make an optional consent mandatory, which is also not consent.
    expect(REGISTER).toContain('analytics: z.boolean().default(false)');
    expect(REGISTER).not.toMatch(/id="analytics"[^>]*defaultChecked/);
  });
});

describe('no call site can send personal data', () => {
  it('declares no allowlist entry that is itself forbidden', () => {
    for (const [event, keys] of Object.entries(ALLOWED_PROPERTIES)) {
      for (const key of keys) {
        expect(isForbiddenKey(key), `${event} allows ${key}`).toBe(false);
      }
    }
  });

  it('passes no forbidden key at any track() call in the app', () => {
    // Scans the ACTUAL call sites rather than trusting the runtime scrub, because a dropped
    // property is still a property somebody meant to send — and the scrub is silent, so the
    // author would never find out that the thing they wanted to measure never arrived.
    const offenders: string[] = [];
    for (const dir of ['src/hooks', 'src/app', 'src/components']) {
      for (const file of filesUnder(dir)) {
        if (file.endsWith('.test.ts') || file.endsWith('.test.tsx')) continue;
        const source = stripComments(read(file));
        for (const match of source.matchAll(/track\(EVENTS\.[A-Z_]+,\s*\{([^}]*)\}/g)) {
          for (const key of match[1].matchAll(/([A-Za-z_$][\w$]*)\s*:/g)) {
            if (isForbiddenKey(key[1])) offenders.push(`${file}: ${key[1]}`);
          }
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it('never passes a raw session, report or payment identifier', () => {
    // Not caught by `isForbiddenKey` — an id is not a name — and worth its own rule. These
    // are join keys into a candidate's own records, and handing them to a third party makes
    // an analytics export re-identifiable against our own database.
    const banned = [
      'session_id',
      'report_id',
      'user_id',
      'razorpay_payment_id',
      'razorpay_order_id',
      'payment_id',
      'question_id',
    ];
    const offenders: string[] = [];
    for (const dir of ['src/hooks', 'src/app', 'src/components']) {
      for (const file of filesUnder(dir)) {
        if (file.endsWith('.test.ts') || file.endsWith('.test.tsx')) continue;
        const source = stripComments(read(file));
        for (const match of source.matchAll(/track\(EVENTS\.[A-Z_]+,\s*\{([^}]*)\}/g)) {
          for (const key of banned) {
            if (new RegExp(`\\b${key}\\s*:`).test(match[1])) offenders.push(`${file}: ${key}`);
          }
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it('instruments every event in the catalogue somewhere', () => {
    // The other direction: an event declared and never fired is a funnel step that silently
    // reports zero, which reads as "nobody does this" rather than as "nobody measured it".
    const app = ['src/hooks', 'src/app', 'src/components']
      .flatMap((dir) => filesUnder(dir))
      .filter((file) => !file.endsWith('.test.ts') && !file.endsWith('.test.tsx'))
      .map((file) => read(file))
      .join('\n');

    for (const [constant] of Object.entries(EVENTS)) {
      expect(app, `EVENTS.${constant} is declared but never fired`).toContain(
        `track(EVENTS.${constant}`
      );
    }
  });
});

/** Every `.ts`/`.tsx` under a directory, relative to the frontend root. */
function filesUnder(dir: string): string[] {
  const { readdirSync, statSync } = require('node:fs') as typeof import('node:fs');
  const out: string[] = [];
  const walk = (current: string) => {
    for (const entry of readdirSync(join(process.cwd(), current))) {
      const rel = `${current}/${entry}`;
      if (statSync(join(process.cwd(), rel)).isDirectory()) walk(rel);
      else if (rel.endsWith('.ts') || rel.endsWith('.tsx')) out.push(rel);
    }
  };
  walk(dir);
  return out;
}
