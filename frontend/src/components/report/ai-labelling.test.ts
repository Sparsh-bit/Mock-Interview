import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * Every score says a machine wrote it — ai-labelling.test.ts
 *
 * WHY A SWEEP AND NOT FOUR ASSERTIONS. A report states whether somebody is ready for a job
 * interview, a language model wrote it with no human reading it first, and the candidate may
 * act on it. Labelling three of the four places a score appears is not a partial fix — the
 * unlabelled one is precisely where somebody forms the belief that the number is a
 * measurement.
 *
 * And this product's design language works against the disclaimer: docs/DESIGN-LANGUAGE.md
 * makes the score the LIT ELEMENT on the page, which renders it in the most authoritative
 * typography available. So the notice has to be systematically attached rather than
 * remembered.
 *
 * THE LIST IS DERIVED, NOT WRITTEN. Every page that renders a score is found by scanning the
 * source for the score fields, so a new surface joins the sweep the moment it is written
 * rather than when somebody remembers to add it here. Anything genuinely exempt has to be
 * named below with a reason — the same shape as `test_auth_coverage.py`'s allowlist, and for
 * the same reason: a new unlabelled surface should have to be argued for.
 */

const SRC = join(process.cwd(), 'src');

/** Fields whose presence means a page is showing an AI-produced judgement of a person. */
const SCORE_FIELDS = [
  'overall_score',
  'readiness_level',
  'overall_score_label',
  'dimension_scores',
];

/** Surfaces that show a score and deliberately carry no notice, with the reason. */
const EXEMPT: Record<string, string> = {
  'app/demo/page.tsx':
    'A scripted demo with invented numbers, shown to somebody who has never had a session. ' +
    'It is not an assessment of the viewer, and labelling fake data as an AI assessment of ' +
    'them would be the misleading statement.',
  'components/interview/CodingWorkspace.tsx':
    'Test-case pass/fail from Judge0 actually running the code. That is a measurement, not ' +
    'a model judgement, and calling it AI-generated would be false.',
};

function sourceFiles(dir: string, found: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) sourceFiles(full, found);
    else if (/\.tsx$/.test(entry) && !/\.test\.tsx?$/.test(entry)) found.push(full);
  }
  return found;
}

const SCORE_SURFACES = sourceFiles(SRC)
  .filter((file) => {
    const text = readFileSync(file, 'utf8');
    return SCORE_FIELDS.some((field) => text.includes(field));
  })
  .map((file) => file.slice(SRC.length + 1));

describe('the sweep found the surfaces it is meant to police', () => {
  it('finds a meaningful number of score surfaces', () => {
    // Guards the guard. Every assertion below passes trivially against an empty list.
    expect(SCORE_SURFACES.length).toBeGreaterThanOrEqual(5);
  });

  it('includes the report page, which is the one that matters most', () => {
    expect(SCORE_SURFACES.some((f) => f.includes('report'))).toBe(true);
  });
});

describe('every score surface says the assessment is AI-generated', () => {
  it('no surface renders a score without the notice', () => {
    const unlabelled = SCORE_SURFACES.filter((file) => {
      if (file in EXEMPT) return false;
      const text = readFileSync(join(SRC, file), 'utf8');
      // `<AiAssessmentNotice` — the RENDER, not the identifier. An import left unused, or a
      // comment naming the component, would otherwise satisfy this and the surface would
      // still show an unlabelled score.
      return !/<AiAssessmentNotice[\s/>]/.test(text);
    });

    expect(
      unlabelled,
      'these surfaces render an AI-produced score with nothing saying so. Add ' +
        '<AiAssessmentNotice />, or add the file to EXEMPT above with a reason.',
    ).toEqual([]);
  });

  it('every exemption names a file that still exists and still shows a score', () => {
    // An exemption for a deleted or changed file silently exempts nothing.
    for (const file of Object.keys(EXEMPT)) {
      expect(SCORE_SURFACES, `${file} is exempted but no longer shows a score`).toContain(file);
    }
  });
});

describe('the notice says the right thing', () => {
  const notice = readFileSync(join(SRC, 'components/report/AiAssessmentNotice.tsx'), 'utf8');

  it('names it as AI-generated and not certified', () => {
    expect(notice).toMatch(/AI-generated/);
    expect(notice).toMatch(/not a certified/);
  });

  it('cannot be dismissed', () => {
    /*
     * A disclaimer somebody can turn off is a disclaimer that is absent for exactly the
     * people who have decided they already know what the number means.
     */
    expect(notice).not.toMatch(/dismiss|localStorage|sessionStorage|onClose/i);
  });

  it('agrees with the wording in the Terms', () => {
    // The two must not contradict each other — a candidate may read both.
    const terms = readFileSync(join(SRC, 'lib/legal/policies.ts'), 'utf8');
    expect(terms).toMatch(/not a certified/);
  });
});

describe('the dispute path is reachable from the report', () => {
  it('the report page mounts the dispute control', () => {
    const report = readFileSync(join(SRC, 'app/(dashboard)/report/[id]/page.tsx'), 'utf8');
    expect(report).toContain('DisputeAssessment');
  });

  it('the control posts to the dispute endpoint', () => {
    const dispute = readFileSync(join(SRC, 'components/report/DisputeAssessment.tsx'), 'utf8');
    expect(dispute).toMatch(/\/api\/v1\/reports\/.*\/dispute/);
  });

  it('it does not ask a model to re-mark its own work', () => {
    /*
     * The point of a human appeal is that it is human. A "regenerate" button dressed as an
     * appeal would be the same model, asked the same question, about the same answers.
     */
    const dispute = readFileSync(join(SRC, 'components/report/DisputeAssessment.tsx'), 'utf8');
    expect(dispute).not.toMatch(/regenerate|re-generate|retry.*report/i);
  });

  it('a failed submission does not leave the candidate with nothing', () => {
    const dispute = readFileSync(join(SRC, 'components/report/DisputeAssessment.tsx'), 'utf8');
    // It must name the fallback route rather than only saying "error".
    expect(dispute).toMatch(/grievance/i);
  });
});
