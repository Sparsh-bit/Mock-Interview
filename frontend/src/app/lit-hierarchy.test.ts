import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * One thing is lit — lit-hierarchy.test.ts
 *
 * The complaint that started the redesign was that every page looked the same, and it did:
 * every block was the same white card at the same elevation, so no page had a subject. `.lit`
 * (globals.css) is the answer — one element per page stands in the light and everything else
 * is on paper. See docs/DESIGN-LANGUAGE §1.
 *
 * THE RULE ONLY WORKS IF IT IS SCARCE. Two lit elements on a page is not "more emphasis", it
 * is none — the eye has nowhere to land and the page is flat again, just brighter. That is the
 * failure mode this file exists to prevent, because it is the one that happens naturally:
 * somebody adds a section, wants it to feel important, and reaches for the class that makes
 * things feel important.
 *
 * Nothing in TypeScript or ESLint can see this. It is a design invariant expressed in class
 * names, so it is checked here.
 */

const PAGES_DIR = join(process.cwd(), 'src/app');

/** Every page.tsx under src/app, found without a glob dependency. */
function pageFiles(): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir)) {
      const full = join(dir, entry);
      if (statSync(full).isDirectory()) walk(full);
      else if (entry === 'page.tsx') out.push(full);
    }
  };
  walk(PAGES_DIR);
  return out;
}

/**
 * Count `.lit` applications in real code.
 *
 * COMMENTS ARE STRIPPED FIRST. This repo comments heavily and on purpose — every incident is
 * written down beside the code that caused it — so a scan that does not strip prose will
 * eventually fire on the paragraph explaining the very rule it is checking. That has already
 * happened three times here; see docs/MISTAKES.md P5.
 *
 * `lit-hover` must not count: it is the hover companion, always applied alongside `lit`, and
 * counting it would report every lit element as two. The token boundary is what does that
 * work — `lit` followed by `-` is a different class.
 */
function litCount(src: string): number {
  const code = src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
  return [...code.matchAll(/(?<=["'\s{`])lit(?=["'\s`])/g)].length;
}

describe('the scanner works before it judges anything', () => {
  it('finds the pages', () => {
    // An empty list would make every assertion below pass having checked nothing — the
    // vacuous-guard shape this repo has been caught by repeatedly.
    expect(pageFiles().length).toBeGreaterThanOrEqual(15);
  });

  it('counts a lit class and ignores lit-hover', () => {
    expect(litCount('<div className="lit lit-hover rounded-2xl" />')).toBe(1);
    expect(litCount('<div className={cn("lit", x)} />')).toBe(1);
    expect(litCount('<div className="lit-hover" />')).toBe(0);
    expect(litCount('<div className="split literal quality" />')).toBe(0);
  });

  it('ignores the class when it only appears in a comment', () => {
    expect(litCount('/* one lit element per page */\n<div className="rounded" />')).toBe(0);
    expect(litCount('// the lit element goes here\n<div />')).toBe(0);
  });

  it('at least one page actually uses it', () => {
    // If the class were renamed in globals.css and nowhere else, every page would fall to
    // zero and the "at most one" assertion below would pass on a product with no hierarchy
    // at all. This is the half that notices.
    const total = pageFiles().reduce((n, f) => n + litCount(readFileSync(f, 'utf8')), 0);
    expect(total).toBeGreaterThanOrEqual(6);
  });
});

/**
 * The escape hatch, and why it is a marker rather than a bigger allowance.
 *
 * SOME PAGES ARE SEVERAL PAGES. The interview route renders three mutually exclusive views
 * from one file — setup, "your plan is ready", and the paywall — each returned from its own
 * early `return`. Each one is a whole screen with its own single subject, so each correctly
 * has a lit element, and no two can ever be on screen together.
 *
 * My first version of this test asserted "at most one per FILE" and failed that page. The
 * assertion was stricter than the property: the rule is one lit element per RENDERED VIEW,
 * and a file is not a view. That is the mistake shape recorded as P5 in docs/MISTAKES.md, so
 * rather than loosening the number — which would let a genuine second lit element in
 * unnoticed — the exception has to be declared.
 *
 * A file with more than one `.lit` must say `@lit-exclusive-views` and explain itself. That
 * keeps the check strict for every ordinary page while making the exception deliberate,
 * greppable and reviewed.
 */
const EXCLUSIVE_MARKER = '@lit-exclusive-views';

describe('no page lights two things at once', () => {
  it.each(pageFiles().map((f) => [f.replace(PAGES_DIR, 'src/app'), f]))(
    '%s',
    (_label, file) => {
      const src = readFileSync(file, 'utf8');
      const n = litCount(src);
      if (n <= 1) return;

      expect(
        src.includes(EXCLUSIVE_MARKER),
        `${n} elements carry .lit and the file does not declare ${EXCLUSIVE_MARKER}.\n\n` +
          'A page with two lit elements has none: the eye has nowhere to land and the page ' +
          'reads flat again, just brighter.\n\n' +
          'If they are genuinely mutually exclusive views (separate early returns, never on ' +
          `screen together), add a comment containing ${EXCLUSIVE_MARKER} saying which views ` +
          'they are. If they are not, the page has two subjects and the fix belongs in the ' +
          'layout, not in the class.',
      ).toBe(true);
    },
  );

  it('the marker is not simply on everything', () => {
    // An escape hatch nobody can see being overused is not an escape hatch, it is the new
    // default. If most pages carry it, the rule has quietly stopped applying.
    const files = pageFiles();
    const marked = files.filter((f) => readFileSync(f, 'utf8').includes(EXCLUSIVE_MARKER));
    expect(marked.length).toBeLessThanOrEqual(Math.ceil(files.length * 0.25));
  });
});

describe('the class it depends on exists', () => {
  it('.lit is defined in globals.css', () => {
    // A test asserting the correct use of a class that no longer exists is a test that
    // passes while every page it governs is unstyled.
    const css = readFileSync(join(process.cwd(), 'src/app/globals.css'), 'utf8');
    expect(css).toMatch(/^\s*\.lit\s*\{/m);
    expect(css).toMatch(/^\s*\.lit-hover\s*\{/m);
  });
});
