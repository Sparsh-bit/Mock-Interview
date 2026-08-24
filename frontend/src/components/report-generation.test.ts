/**
 * Generation is never automatic — report-generation.test.ts
 *
 * REPORTED: "the generate again button is triggering by itself as it is exhausting my api".
 *
 * It was. `useReport` had a `POST /generate` as its queryFn — a BILLED MODEL CALL inside a
 * React Query. React Query decides when a query runs: on mount, and whenever the data is
 * stale. With `staleTime` at a minute, a candidate who opened their report, went to Detailed
 * Analysis and came back paid for another generation. For an unscored report the server
 * regenerates every time, so each of those was a real model call at roughly ₹11.
 *
 * That is also the likeliest reason the daily spend cap was reached, after which every provider
 * refuses and every candidate is told the model was unreachable. One bug, two symptoms, and the
 * expensive one was completely invisible.
 *
 * So the rule these tests hold: READS ARE QUERIES, BILLED WRITES ARE MUTATIONS, and automatic
 * generation happens at most once per visit and never for a report that is already scored.
 *
 * AN UNSCORED PLACEHOLDER IS RETRIED, and that is a deliberate widening of the old rule. It
 * used to be excluded on the reasoning that the candidate should choose to spend; in practice
 * they saw 0/100, read "scoring could not be completed", and left — so the report they had
 * already paid for was never produced. The spend guard is the SERVER (`should_regenerate`),
 * which refuses on a scored report always and on a placeholder once its attempts and cooldown
 * are spent. A refused call makes no model request. A ref cannot be the guard here, because a
 * ref only lasts as long as the page.
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

describe('reading a report never generates one', () => {
  it('useReport is a GET', () => {
    const at = code(HOOKS).indexOf('export function useReport');
    const body = code(HOOKS).slice(at, code(HOOKS).indexOf('export function', at + 10));
    expect(body).toMatch(/api\.get\(/);
    expect(body).not.toMatch(/\/generate/);
  });

  it('a missing report is not an error', () => {
    // It is the state every candidate is in the moment they finish. Throwing here would make
    // the first view of a report an error screen.
    const at = code(HOOKS).indexOf('export function useReport');
    const body = code(HOOKS).slice(at, code(HOOKS).indexOf('export function', at + 10));
    expect(body).toMatch(/404/);
    expect(body).toMatch(/return null/);
  });

  it('generation is a mutation, not a query', () => {
    expect(code(HOOKS)).toMatch(/export function useGenerateReport[\s\S]{0,400}useMutation/);
  });

  it('generation is never retried automatically', () => {
    const at = code(HOOKS).indexOf('export function useGenerateReport');
    const body = code(HOOKS).slice(at, at + 2200);
    expect(body).toMatch(/retry: false/);
  });
});

describe('the page generates at most once, and only when there is nothing', () => {
  it('guards the automatic generation with a ref', () => {
    // Effects re-run. Without the ref a second run while the first is in flight buys two
    // reports for one session.
    expect(code(PAGE)).toMatch(/requested\s*=\s*useRef\(false\)/);
    expect(code(PAGE)).toMatch(/requested\.current\s*=\s*true/);
  });

  it('does not generate when a SCORED report already exists', () => {
    // THE MONEY-CRITICAL ONE. A finished report must be free to re-read, forever. Dropping
    // this condition would buy a fresh report on every page view of every report in the
    // product — the original drain, restored.
    expect(code(PAGE)).toMatch(/if \(report && !unscored\) return;/);
  });

  it('does generate when the stored report is an unscored placeholder', () => {
    // The 0/100 population. `unscored` must be derived from the server's own reason field
    // rather than from a score of zero, because a genuine zero is a real result — a candidate
    // who answered nothing correctly has a scored report and must not be re-billed for it.
    expect(code(PAGE)).toMatch(/unscored\s*=\s*!!report\?\.unscored_reason/);
  });

  it('still cannot fire twice on one visit', () => {
    // The ref is not the spend guard, but it is what stops two concurrent generations for one
    // session while the first is still in flight.
    const stripped = code(PAGE);
    const at = stripped.indexOf('requested = useRef(false)');
    expect(at).toBeGreaterThan(-1);
    const effect = stripped.slice(at, at + 400);
    expect(effect).toMatch(/requested\.current\) return;/);
    expect(effect).toMatch(/requested\.current\s*=\s*true;/);
  });

  it('the retry buttons call the mutation, not a refetch', () => {
    // A refetch used to BE a generation. Now it is a free read, so retry has to be explicit.
    const stripped = code(PAGE);
    expect(stripped).toMatch(/onRetry=\{\(\) => generate\.mutate\(\)\}/);
    expect(stripped).toMatch(/onClick=\{\(\) => generate\.mutate\(\)\}/);
  });
});

describe('an unscored report points at the analysis that does exist', () => {
  it('links to the analysis page from the unscored branch', () => {
    const at = PAGE.indexOf('<UnscoredNotice');
    const branch = PAGE.slice(at, at + 1800);
    expect(branch).toContain('/analysis');
    expect(branch).toMatch(/Detailed Analysis/);
  });

  it('tells them their answers survived', () => {
    const at = PAGE.indexOf('<UnscoredNotice');
    expect(PAGE.slice(at, at + 1800)).toMatch(/answers are all saved/i);
  });
});
