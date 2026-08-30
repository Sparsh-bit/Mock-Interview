/**
 * "Being written" is not "failed" — report-batch-polling.test.ts
 *
 * The server can now produce a report through Anthropic's Message Batches API: half price,
 * answered on the provider's schedule instead of inside the request. While that is out it
 * stores a PLACEHOLDER report — 0/100, empty panels, no analysis — and answers
 * `job_status: 'processing'`.
 *
 * ON SCREEN THAT PLACEHOLDER IS INDISTINGUISHABLE FROM THE UNSCORED ONE, AND THEY MEAN
 * OPPOSITE THINGS. Unscored means scoring was attempted and failed; the right response is the
 * retry card, and the candidate pressing it is correct. Processing means the report is on its
 * way; the right response is to wait, and a retry there would spend one of three attempts
 * against a failure that has not happened — while showing "Report Unavailable" for a report
 * that is fine.
 *
 * So the rules this file holds:
 *
 *   1. The preparing state is checked BEFORE the error branch and before the report renders.
 *      Falling through would draw an empty report as though that were the answer.
 *   2. It offers no retry. A button there is an invitation to do the one thing that makes it
 *      worse.
 *   3. Polling is a QUERY. This file's older sibling, report-generation.test.ts, exists
 *      because a billed POST was once put inside a React Query and generated a report on
 *      every focus. The job poll is a cheap read and belongs in a query; nothing about that
 *      may drift back toward the mutation.
 *   4. The poll stops when the job stops. A page left open on a finished — or failed —
 *      report must not tick forever.
 *   5. When the batch lands, the report is asked for exactly ONCE, guarded by its own ref.
 *
 * Source-scanning, like report-generation.test.ts, and for the same reason: these are rules
 * about when effects fire and in what order branches are checked, which is precisely what a
 * rendering test tends to paper over.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

const SRC = join(__dirname, '..');
const HOOKS = readFileSync(join(SRC, 'hooks/useData.ts'), 'utf8');
const PAGE = readFileSync(join(SRC, 'app/(dashboard)/report/[id]/page.tsx'), 'utf8');

/** Source with comments stripped — prose about a rule is not the rule. */
function code(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '');
}

function hook(name: string): string {
  const src = code(HOOKS);
  const at = src.indexOf(`export function ${name}`);
  expect(at, `${name} is missing from useData.ts`).toBeGreaterThan(-1);
  const next = src.indexOf('export ', at + 10);
  return src.slice(at, next === -1 ? undefined : next);
}

describe('polling a batch is a read, and stays one', () => {
  it('useReportJob is a query, not a mutation', () => {
    // The whole reason report-generation.test.ts exists is that a billed POST was once put
    // inside a query. This is the mirror rule: a cheap read on an interval must never become
    // a mutation, and a mutation must never become a poll.
    expect(hook('useReportJob')).toMatch(/useQuery/);
    expect(hook('useReportJob')).not.toMatch(/useMutation/);
  });

  it('it GETs the job endpoint and never the generate one', () => {
    const body = hook('useReportJob');
    expect(body).toMatch(/api\.get\(/);
    expect(body).toMatch(/\/job`/);
    expect(body).not.toMatch(/\/generate/);
  });

  it('it polls only while something is enabled', () => {
    // Without this the query runs on every report page in the product, including the
    // overwhelming majority that were never batched.
    expect(hook('useReportJob')).toMatch(/enabled:/);
  });

  it('the interval stops once the job is no longer processing', () => {
    // A page left open on a completed or failed report must not keep asking. The refetch
    // interval has to return false for any non-processing status, not merely for success —
    // an abandoned job is just as finished as a completed one.
    const body = hook('useReportJob');
    expect(body).toMatch(/refetchInterval/);
    expect(body).toMatch(/!==\s*'processing'\s*\?\s*false/);
  });

  it('it is never retried automatically', () => {
    expect(hook('useReportJob')).toMatch(/retry: false/);
  });
});

describe('a report being written is not a report that failed', () => {
  it('preparing is derived from job_status, not from a zero score', () => {
    // A genuine 0/100 is a real result — a candidate who answered nothing correctly has a
    // scored report. Branching on the score would hide theirs behind a spinner forever.
    expect(code(PAGE)).toMatch(/preparing\s*=\s*report\?\.job_status\s*===\s*'processing'/);
  });

  it('the preparing branch is checked before the error branch', () => {
    // ORDER IS THE RULE. The placeholder underneath is a real 200 with a 0/100 in it, so
    // whichever branch is reached first decides what the candidate sees.
    const src = code(PAGE);
    const preparingAt = src.indexOf('if (preparing)');
    const errorAt = src.indexOf('if (error || !report)');
    expect(preparingAt).toBeGreaterThan(-1);
    expect(errorAt).toBeGreaterThan(-1);
    expect(preparingAt).toBeLessThan(errorAt);
  });

  it('the preparing branch returns rather than falling through to the report', () => {
    const src = code(PAGE);
    const at = src.indexOf('if (preparing)');
    expect(src.slice(at, at + 200)).toMatch(/return \(/);
  });

  it('the preparing state offers no way to generate again', () => {
    // The single action that would make this worse. A batch is already out; generating now
    // buys a second report for the same session and tells the server to stop waiting for the
    // one that is coming.
    const src = code(PAGE);
    const at = src.indexOf('if (preparing)');
    const branch = src.slice(at, src.indexOf('if (error || !report)'));
    expect(branch).not.toMatch(/generate\.mutate/);
    expect(branch).not.toMatch(/Try again/);
  });

  it('it tells the candidate they can leave', () => {
    // A batch takes minutes. "Close this tab and come back" is only safe to say because the
    // server collects the batch inside POST /generate whenever it is next called — nothing
    // depends on this page staying open, and the copy should say so.
    const src = code(PAGE);
    const at = src.indexOf('if (preparing)');
    const branch = src.slice(at, src.indexOf('if (error || !report)'));
    expect(branch).toMatch(/close this tab/i);
  });
});

describe('a finished batch is collected exactly once', () => {
  it('a second ref guards the collection, separate from the first-visit one', () => {
    // Sharing `requested` would mean a batch completing on a page that had already
    // auto-generated never gets collected — the candidate sits on "preparing" until they
    // reload, which is the one thing the copy promises they will not have to do.
    const src = code(PAGE);
    expect(src).toMatch(/collected\s*=\s*useRef\(false\)/);
    expect(src).toMatch(/requested\s*=\s*useRef\(false\)/);
    expect(src).toMatch(/collected\.current\s*=\s*true/);
  });

  it('it does not fire while the job is still processing', () => {
    const src = code(PAGE);
    const at = src.indexOf('collected.current) return');
    expect(at).toBeGreaterThan(-1);
    const effect = src.slice(at, at + 400);
    expect(effect).toMatch(/status === 'processing'/);
  });

  it("it does not fire for a session that never batched", () => {
    // 'none' means the report is produced synchronously as it always was. Generating on it
    // would be a second billed report for one session.
    const src = code(PAGE);
    const at = src.indexOf('collected.current) return');
    expect(src.slice(at, at + 400)).toMatch(/status === 'none'/);
  });

  it('it DOES fire for failed and abandoned, not only for completed', () => {
    // There is no state here where the right answer is to do nothing. The server treats a
    // dead batch as "the cheap route did not work out" and generates synchronously in that
    // same request — so the effect must not special-case success, or a candidate whose batch
    // expired would wait forever for a page that had already given up on their behalf.
    const src = code(PAGE);
    const at = src.indexOf('collected.current) return');
    const effect = src.slice(at, at + 400);
    expect(effect).not.toMatch(/status === 'completed'/);
    expect(effect).toMatch(/generate\.mutate\(\)/);
  });
});
