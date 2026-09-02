import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import { fadeIn, fadeUp, scalePop, staggerContainer } from './motion';

/**
 * An animate= that names no variant leaves the page invisible — motion.test.ts
 *
 * THE FAILURE THIS EXISTS FOR, WHICH HAPPENED. The deck review page was written with
 * `initial="hidden" animate="show"`, and the presets in this module call that state
 * `visible`. Framer Motion does not error on an unknown variant name — it simply never
 * leaves `hidden` — so every child of that container stayed at `opacity: 0`.
 *
 * The whole result section of the page rendered into the DOM and was invisible. `tsc`
 * passed, `eslint` passed, and 1,060 unit tests passed, because a string that names
 * nothing is still a string. It was found by opening the page in a browser, which is
 * exactly the kind of check that does not run in CI.
 *
 * So: every variant name used with `initial=` or `animate=` anywhere in the app has to be
 * a key that actually exists in one of the presets below.
 */

const SRC = join(process.cwd(), 'src');

/** The state names the shared presets actually define. */
const KNOWN = new Set([
  ...Object.keys(fadeUp),
  ...Object.keys(fadeIn),
  ...Object.keys(scalePop),
  ...Object.keys(staggerContainer()),
]);

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) out.push(...walk(path));
    else if (/\.tsx$/.test(entry)) out.push(path);
  }
  return out;
}

/** Every `initial="..."` / `animate="..."` / `exit="..."` string literal in the app. */
function variantUsages(): { file: string; prop: string; name: string }[] {
  const found: { file: string; prop: string; name: string }[] = [];
  for (const file of walk(SRC)) {
    const source = readFileSync(file, 'utf8');
    for (const match of source.matchAll(/\b(initial|animate|exit)="([A-Za-z][\w-]*)"/g)) {
      found.push({ file: file.replace(SRC, 'src'), prop: match[1], name: match[2] });
    }
  }
  return found;
}

describe('the presets define the names the app uses', () => {
  it('knows the state names', () => {
    // Guards the assertion below from passing over an empty set.
    expect(KNOWN.has('hidden')).toBe(true);
    expect(KNOWN.has('visible')).toBe(true);
  });

  it('finds variant usages to check', () => {
    // And guards it from passing because the regex stopped matching.
    expect(variantUsages().length).toBeGreaterThan(5);
  });

  it('every animate/initial/exit names a state some preset defines', () => {
    const unknown = variantUsages().filter((u) => !KNOWN.has(u.name));
    expect(
      unknown,
      'these name a variant no preset in lib/motion.ts defines, so the element never '
        + 'leaves its initial state and renders invisibly:\n'
        + unknown.map((u) => `  ${u.file}: ${u.prop}="${u.name}"`).join('\n'),
    ).toEqual([]);
  });
});
