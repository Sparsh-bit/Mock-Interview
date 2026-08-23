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
 * So the rule these tests hold: READS ARE QUERIES, BILLED WRITES ARE MUTATIONS, and the only
 * automatic generation left is the first one for a report that does not exist at all.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

const SRC = join(__dirname, '..');
const HOOKS = readFileSync(join(SRC, 'hooks/useData.ts'), 'utf8');
const PAGE = readFileSync(join(SRC, 'app/(dashboard)/report/[id]/page.tsx'), 'utf8');
const NOTICE = readFileSync(join(SRC, 'components/ReportReadyNotice.tsx'), 'utf8');

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

  it('does not generate when a report already exists', () => {
    // An unscored report EXISTS. There is something on screen and a button to press, and
    // pressing it is the candidate's decision to make with their own money.
    expect(code(PAGE)).toMatch(/if \(isLoading \|\| error \|\| report \|\| requested\.current\) return;/);
  });

  it('the retry buttons call the mutation, not a refetch', () => {
    // A refetch used to BE a generation. Now it is a free read, so retry has to be explicit.
    const stripped = code(PAGE);
    expect(stripped).toMatch(/onRetry=\{\(\) => generate\.mutate\(\)\}/);
    expect(stripped).toMatch(/onClick=\{\(\) => generate\.mutate\(\)\}/);
  });
});

describe('the dashboard notice tells them without spending anything', () => {
  it('is a link and calls nothing', () => {
    const stripped = code(NOTICE);
    expect(stripped).toMatch(/<Link/);
    expect(stripped).not.toMatch(/mutate\(|\/generate|useGenerateReport/);
  });

  it('targets exactly the candidates whose scoring failed but whose answers exist', () => {
    const stripped = code(NOTICE);
    expect(stripped).toMatch(/status === 'completed'/);
    // Answers exist, so the analysis page has something to show — without this the card would
    // point somebody at an empty page.
    expect(stripped).toMatch(/questions_asked > 0/);
    // Null means no report row; 0 means the unscored placeholder. Both are "not scored yet".
    expect(stripped).toMatch(/overall_score === null/);
    expect(stripped).toMatch(/overall_score === 0/);
  });

  it('renders nothing for everybody else', () => {
    expect(code(NOTICE)).toMatch(/if \(!pending\) return null;/);
  });

  it('says the answers are saved, which is the thing they are worried about', () => {
    expect(NOTICE).toMatch(/saved/i);
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
