/**
 * Nothing is unreachable at any screen size — src/responsive-invariants.test.ts
 *
 * REPORTED, twice, about different pages: "the website responsive ness is also very bad as on
 * the mobile the side pannel is not showing and also in the zoomed screens the submit andswer
 * button in the interview is also been hidden", then "do it not only for mobile for all kinds
 * of screens resizing make sure that nothing must be hidden specially on all the pages".
 *
 * WHY THIS FILE IS ONE SWEEP RATHER THAN A TEST PER PAGE. Every individual instance of this bug
 * was fixed in the page it was noticed in, and the class kept coming back somewhere else — the
 * interview page got `dvh` and `min-h-0`, and the GD page then shipped `sm:h-[calc(100vh-8rem)]`
 * which reintroduces the identical defect at every width above 640px. A per-page test cannot
 * catch that, because the next occurrence is by definition in a page nobody wrote a test for.
 * So this walks EVERY source file and checks the small number of patterns that actually make
 * content unreachable.
 *
 * THESE ARE NOT STYLE RULES. Each one below corresponds to a way a candidate loses something
 * they cannot get back: a submit button under the browser chrome, a table clipped off the right
 * edge of a shell that cannot scroll, an action row hidden at 200% zoom. Cosmetic responsive
 * issues are deliberately NOT checked here — a guard that fires on things that do not matter
 * gets muted, and then it is not guarding anything.
 *
 * HOW TO ADD AN EXCEPTION. Put the path in the rule's allowlist WITH A REASON, in the same
 * shape as the ones already there. An allowlist entry is a claim that the pattern is safe in
 * that file, which is sometimes true — `min-h-screen` cannot clip, an inline style on an error
 * boundary has no Tailwind available. Do not add an entry to make a red test go green without
 * being able to write down why the content is still reachable.
 */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

import { describe, expect, it } from 'vitest';

const SRC = join(__dirname);

/** Every source file we own, as (repo-relative path, contents). Tests excluded. */
function sourceFiles(): Array<{ path: string; code: string }> {
  const out: Array<{ path: string; code: string }> = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir)) {
      if (entry === 'node_modules' || entry.startsWith('.')) continue;
      const full = join(dir, entry);
      if (statSync(full).isDirectory()) {
        walk(full);
        continue;
      }
      if (!/\.(tsx|ts|css)$/.test(entry)) continue;
      // A test asserting on source text necessarily QUOTES the patterns this file forbids.
      if (/\.test\.(ts|tsx)$/.test(entry)) continue;
      out.push({ path: relative(SRC, full), code: readFileSync(full, 'utf8') });
    }
  };
  walk(SRC);
  return out;
}

const FILES = sourceFiles();

/** Strip comments, so prose ABOUT a pattern is never mistaken for the pattern. */
function withoutComments(code: string): string {
  return code
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '');
}

it('finds the source tree at all', () => {
  // A walker that silently returns nothing would make every test below pass vacuously, which
  // is the one failure mode of a sweep like this that nobody would ever notice.
  expect(FILES.length).toBeGreaterThan(50);
  expect(FILES.some((f) => f.path.includes('layout.tsx'))).toBe(true);
});

describe('viewport units: a ceiling measured in vh can hide things', () => {
  /**
   * `vh` IS THE HEIGHT WITH THE BROWSER CHROME HIDDEN, so on mobile Safari and Chrome a 100vh
   * box is permanently taller than what the phone actually shows. When such a box is also the
   * only scroller — or sits inside an `overflow-hidden` shell — its last 60-100px live under
   * the address bar forever, and that is wherever the page's final action happens to be. `dvh`
   * tracks the real viewport and equals `vh` on desktop, so there is no trade-off.
   *
   * ONLY CEILINGS ARE CHECKED, AND THE DISTINCTION IS THE WHOLE VALUE OF THIS RULE.
   *
   *   `h-[100vh]`, `max-h-[22vh]`, `height:`     — a CEILING. Content beyond it is clipped or
   *                                                pushed out of reach. This is the bug.
   *   `min-h-[60vh]`, `min-height: 100vh`        — a FLOOR. It reserves space and nothing else;
   *                                                content taller than it simply grows past it.
   *                                                It cannot hide anything, ever.
   *
   * The floors in this codebase are all on centred empty-states and error cards
   * (app/(dashboard)/error.tsx, prepare/page.tsx, report/[id]/page.tsx, globals.css) where they
   * are exactly the right tool. Flagging them would mean asking somebody to change five safe
   * lines to reach the one dangerous one — and a guard that mostly cries wolf gets switched
   * off, at which point it protects nothing. So it stays narrow on purpose.
   *
   * The rule covers RESPONSIVE VARIANTS, because the actual regression was
   * `h-[calc(100dvh-7rem)] sm:h-[calc(100vh-8rem)]` in the GD round — correct at the base and
   * wrong at every width above 640px, which is most of them.
   */
  const ALLOWED = new Map<string, string>([
    [
      'app/global-error.tsx',
      // Renders outside the app shell with no Tailwind and no theme, as a plain inline style
      // object. It is `minHeight` — a floor — so it is doubly safe.
      'inline style on the root error boundary; minHeight is a floor and cannot clip',
    ],
  ]);

  it('no vh ceiling anywhere it could clip or displace content', () => {
    const offenders: string[] = [];
    for (const { path, code } of FILES) {
      if (ALLOWED.has(path)) continue;
      withoutComments(code)
        .split('\n')
        .forEach((line, i) => {
          for (const m of line.matchAll(/(?<![dsl])\b[\w-]*?(\d+)vh\b/g)) {
            // Find the Tailwind utility (or CSS property) this length belongs to.
            const before = line.slice(0, m.index ?? 0);
            const utility = /([\w:-]*?)(?:\[[^\]]*)?$/.exec(before)?.[1] ?? '';
            const isFloor = /min-h(?:eight)?-?$|min-height:\s*$/.test(utility.replace(/.*:/, '')) ||
              /min-h-\[?$/.test(utility) ||
              /min-height:\s*$/.test(before);
            if (isFloor) continue;
            offenders.push(`${path}:${i + 1} (${line.trim().slice(0, 60)})`);
          }
        });
    }
    expect(
      offenders,
      'use dvh for any height CEILING: vh is the viewport with the browser chrome hidden, so ' +
        'the bottom of the box — usually where the page action is — sits under the address bar ' +
        'unreachably. (Floors like min-h-[60vh] are fine and are not checked.)',
    ).toEqual([]);
  });
});

describe('wide content scrolls itself and never widens the page', () => {
  /**
   * A dense data table legitimately needs a min-width — collapsing a money table into cards
   * makes it unreadable. What it must NOT do is widen the page: the correct treatment is a
   * `min-w-[...]` table inside an `overflow-x-auto` wrapper, so the table scrolls within its
   * own box and the page body never scrolls horizontally.
   *
   * This matters more than it looks: the admin and AI-usage tables already had exactly the
   * right markup, and it did nothing, because the shell's content column was missing `min-w-0`
   * — an `overflow-x-auto` container only engages once its own width is constrained. So this
   * rule pins the half that is expressed in the page, and the shell test below pins the half
   * that makes it work.
   */
  it('every min-w-[...] table sits inside an overflow-x wrapper', () => {
    const offenders: string[] = [];
    for (const { path, code } of FILES) {
      const lines = withoutComments(code).split('\n');
      lines.forEach((line, i) => {
        if (!/<table[^>]*min-w-\[/.test(line)) return;
        // The wrapper is normally the immediately preceding element; allow a few lines of
        // attributes between them.
        const above = lines.slice(Math.max(0, i - 4), i).join('\n');
        if (!/overflow-x-auto|overflow-auto|overflow-x-scroll/.test(above)) {
          offenders.push(`${path}:${i + 1}`);
        }
      });
    }
    expect(
      offenders,
      'a min-width table must scroll inside an overflow-x-auto wrapper, or it widens the page',
    ).toEqual([]);
  });

  it('no fixed minimum width wider than the narrowest phone', () => {
    // 320px is the narrowest viewport still in real use. Anything with a hard floor above it
    // forces the whole page to scroll sideways, which no amount of wrapping downstream fixes.
    // Tables are exempt: they are the case the rule above covers properly.
    const offenders: string[] = [];
    for (const { path, code } of FILES) {
      const lines = withoutComments(code).split('\n');
      lines.forEach((line, i) => {
        if (/<table/.test(line)) return;
        for (const m of line.matchAll(/min-w-\[(\d+)px\]/g)) {
          if (Number(m[1]) > 320) offenders.push(`${path}:${i + 1} (${m[0]})`);
        }
      });
    }
    expect(offenders, 'a min-width above 320px forces horizontal page scroll on real phones')
      .toEqual([]);
  });
});

describe('the app shell can never clip what it contains', () => {
  /**
   * The dashboard shell is a fixed-height `overflow-hidden` row: sidebar beside a content
   * column, with <main> as the only scroller. That is the right pattern, and it has one
   * mandatory detail — the content column must be allowed to SHRINK.
   *
   * A flex item defaults to `min-width: auto`, i.e. "at least as wide as my content", so
   * without `min-w-0` any wide descendant on any dashboard page pushes the column past the
   * viewport. Because the shell is `overflow-hidden`, that overflow is clipped rather than
   * scrollable: content leaves the right edge with no scrollbar and no gesture that reaches it.
   * One missing class, every page affected.
   */
  it('the dashboard content column may shrink below its content width', () => {
    const shell = FILES.find((f) => f.path === 'app/(dashboard)/layout.tsx');
    expect(shell, 'the dashboard shell moved; this guard needs repointing').toBeDefined();
    const body = withoutComments(shell!.code);

    // The column that holds the header and <main>, beside the sidebar.
    const column = body.match(/className="flex flex-1 flex-col[^"]*"/);
    expect(column, 'the shell content column is not recognisable any more').toBeTruthy();
    expect(
      column![0],
      'the content column needs min-w-0: without it a wide table pushes it past the ' +
        'overflow-hidden shell and is clipped with no way to scroll to it',
    ).toContain('min-w-0');
  });

  it('a fixed-height shell still uses a dynamic viewport unit', () => {
    const shell = FILES.find((f) => f.path === 'app/(dashboard)/layout.tsx')!;
    const body = withoutComments(shell.code);
    expect(body).toMatch(/h-\[100dvh\]/);
  });
});
