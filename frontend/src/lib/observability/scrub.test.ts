import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import {
  MAX_STRING_LENGTH,
  REDACTED,
  redactText,
  scrubBreadcrumb,
  scrubEvent,
} from './scrub';

/**
 * What may leave the browser when something breaks.
 *
 * The values below are the four things this app holds that must never reach a
 * third-party error tracker, and each test names which mechanism is supposed to stop
 * it — so a test failure says which layer broke, not just "PII found".
 */

const RESUME =
  'SPARSH GUPTA — sparsh@example.com — +91 98765 43210. B.Tech CSE 2026, ' +
  'built a payments service handling 4M requests/day.';
const ANSWER = 'A HashMap is not thread safe, you should use ConcurrentHashMap instead.';
const JWT = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.QWJjRGVmR2hpSktMbW5PcA';
const SESSION_ID = '3f2504e0-4f89-11d3-9a0c-0305e82c3301';

const blob = (value: unknown) => JSON.stringify(value);

describe('key-based redaction', () => {
  it('redacts PII keys at any depth', () => {
    const event = scrubEvent({
      extra: {
        resumeText: RESUME,
        nested: [{ transcript: 'I think the answer is B' }],
      },
      contexts: { interview: { session_id: SESSION_ID } },
    });

    expect(blob(event)).not.toContain('SPARSH');
    expect(blob(event)).not.toContain('I think the answer is B');
    expect(blob(event)).not.toContain(SESSION_ID);
  });

  it('redacts the field an answer is actually submitted in', () => {
    // `SubmitAnswerRequest.content` — a key name that says nothing about what it
    // holds, which is why `content` is on the list.
    const event = scrubEvent({ extra: { content: ANSWER } });
    expect((event.extra as Record<string, unknown>).content).toBe(REDACTED);
  });

  it('empties the Sentry user block', () => {
    // `id` and `username` are too generic to denylist globally, and the SDK fills
    // this block in itself.
    const event = scrubEvent({ user: { id: SESSION_ID, email: 'a@b.com' } });
    expect(event.user).toEqual({});
  });
});

describe('pattern-based redaction inside strings', () => {
  it('removes tokens and addresses from an exception message', () => {
    // The case no key name can reach: text built by interpolation.
    const message = `rejected Bearer ${JWT} for sparsh@example.com on ${SESSION_ID}`;
    const out = redactText(message);

    expect(out).not.toContain(JWT);
    expect(out).not.toContain('sparsh@example.com');
    expect(out).not.toContain(SESSION_ID);
    expect(out).toContain('rejected');
  });

  it('turns a UUID into a stable one-way handle', () => {
    // Correlation survives; the id does not. Without this, "one user failed 400
    // times" is indistinguishable from "400 users failed once".
    const first = redactText(`session ${SESSION_ID} failed`);
    const second = redactText(`retrying ${SESSION_ID}`);
    const other = redactText('session 00000000-0000-4000-8000-000000000000 x');

    const handle = first.split('session ')[1].split(' ')[0];
    expect(handle).toMatch(/^\[uuid:[0-9a-f]{8}\]$/);
    expect(second).toContain(handle);
    expect(other).not.toContain(handle);
  });

  it('truncates bulk text', () => {
    expect(redactText('x'.repeat(MAX_STRING_LENGTH * 3).concat()).length).toBeLessThan(
      MAX_STRING_LENGTH + 32
    );
  });
});

describe('breadcrumbs', () => {
  it('keeps the shape of a fetch and loses the payload', () => {
    // THE BIGGEST BROWSER LEAK. Sentry records every fetch, and the one this page
    // makes most often carries an answer in its body.
    const crumb = scrubBreadcrumb({
      category: 'fetch',
      type: 'http',
      data: {
        method: 'POST',
        url: `https://api.example.com/api/v1/interview/${SESSION_ID}/answer?token=${JWT}`,
        status_code: 500,
        // Sentry does not send fetch bodies today; asserting it anyway means a
        // future SDK that starts to cannot do it silently.
        body: ANSWER,
      },
    });

    expect(blob(crumb)).not.toContain(JWT);
    expect(blob(crumb)).not.toContain('ConcurrentHashMap');
    expect(blob(crumb)).not.toContain(SESSION_ID);

    const data = crumb.data as Record<string, unknown>;
    expect(data.status_code).toBe(500);
    expect(data.method).toBe('POST');
    // The endpoint stays identifiable — the point is a usable error report.
    expect(data.url).toContain('/api/v1/interview/');
  });

  it('scrubs console breadcrumbs', () => {
    const crumb = scrubBreadcrumb({
      category: 'console',
      level: 'error',
      message: `submit failed for sparsh@example.com session ${SESSION_ID}`,
    });
    expect(blob(crumb)).not.toContain('sparsh@example.com');
    expect(blob(crumb)).not.toContain(SESSION_ID);
  });
});

describe('the scrubber does not disarm the tracker', () => {
  it('never drops an event or a breadcrumb', () => {
    // A scrubber returning null would pass every "PII absent" assertion above while
    // making the tracker silent.
    expect(scrubEvent({ exception: { values: [{ type: 'TypeError' }] } })).not.toBeNull();
    expect(scrubBreadcrumb({ category: 'navigation' })).not.toBeNull();
  });

  it('keeps the exception type and message shape', () => {
    const event = scrubEvent({
      exception: { values: [{ type: 'TypeError', value: 'x.map is not a function' }] },
    });
    const values = (event.exception as { values: { type: string; value: string }[] }).values;
    expect(values[0].type).toBe('TypeError');
    expect(values[0].value).toBe('x.map is not a function');
  });
});

/**
 * Source with comments removed.
 *
 * ASSERTING AGAINST THE RAW FILE DOES NOT WORK HERE, and the repo has already paid
 * for this lesson once — see the note in `src/lib/security-headers.test.ts`. Every
 * rule below is one the source explains in a comment, so "the DSN is never
 * hardcoded" fails on the comment that gives an example DSN, and "replay is not
 * installed" fails on the comment saying replay is not installed.
 *
 * A character scanner rather than a regex, for the reason that file records: a
 * non-greedy block-comment regex mispairs an opening comment with a later `*` `/`
 * inside a string and silently eats real code.
 */
function stripComments(source: string): string {
  let out = '';
  let i = 0;
  while (i < source.length) {
    const two = source.slice(i, i + 2);
    if (two === '//') {
      i = source.indexOf('\n', i);
      if (i < 0) break;
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

describe('wiring', () => {
  const read = (rel: string) => readFileSync(join(process.cwd(), rel), 'utf8');
  const code = (rel: string) => stripComments(read(rel));

  it('never hardcodes a DSN', () => {
    // A DSN identifies the project. It is configuration, not source.
    expect(code('src/lib/observability/sentry.ts')).not.toMatch(/ingest\..*sentry\.io/);
    expect(code('next.config.ts')).not.toMatch(/ingest\..*sentry\.io/);
    // A DSN is always `https://<key>@<host>/<project>`. Catches one written into a
    // default, not just one written into the `dsn:` field.
    expect(code('src/lib/observability/sentry.ts')).not.toMatch(/https:\/\/\w+@/);
  });

  it('does nothing at all without a DSN', () => {
    // A developer's machine and CI both legitimately have none.
    expect(code('src/lib/observability/sentry.ts')).toContain('if (!dsn) return false');
  });

  it('lets the report through the CSP', () => {
    /*
     * THE FAILURE THIS PREVENTS IS INVISIBLE. `connect-src` in next.config.ts is
     * derived from a fixed list of origins. Without the ingest host on it the
     * browser blocks every POST the SDK makes: the page works, nothing the user
     * would report appears, and the dashboard stays empty forever — which reads as
     * "no errors" rather than as "no reporting".
     */
    const config = read('next.config.ts');
    expect(config).toContain('NEXT_PUBLIC_SENTRY_DSN');
    expect(config).toMatch(/origins\.add\(new URL\(process\.env\.NEXT_PUBLIC_SENTRY_DSN\)\.origin\)/);
  });

  it('does not install session replay', () => {
    // Replay records the DOM, and the DOM during an interview is the question and
    // the answer being typed into it. Not installed, so no masking config has to be
    // got right.
    const source = code('src/lib/observability/sentry.ts');
    expect(source).not.toContain('replayIntegration');
    expect(source).not.toContain('browserSessionIntegration');
    expect(source).toContain('defaultIntegrations: false');
    // DOM breadcrumbs record the text of what was clicked, which on this app is a
    // question or an option.
    expect(source).toContain('dom: false');
  });

  it('does not send Sentry-collected PII', () => {
    expect(code('src/lib/observability/sentry.ts')).toContain('sendDefaultPii: false');
  });

  it('reports errors caught by the global boundary', () => {
    // React does not route a boundary-caught error to window.onerror, so without
    // this call the failure that blanks the whole app is the one the tracker never
    // hears about.
    expect(read('src/app/global-error.tsx')).toContain("import('@/lib/observability/sentry')");
  });
});
