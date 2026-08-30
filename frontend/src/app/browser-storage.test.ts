import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * Storage that is allowed to fail, and updaters that are not allowed to do things —
 * browser-storage.test.ts
 *
 * TWO BUGS FOUND TOGETHER IN settings/page.tsx, both in six lines of code.
 *
 * `localStorage` THROWS rather than returning null when a browser is blocking site data — a
 * private window, or the "block cookies" setting people turn on and forget about. The read was
 * inside a `useEffect`, and React surfaces a throw there as a render error, so the whole
 * settings page failed to appear because of a convenience preference. NudgeDeck already wrapped
 * its own calls and explained why; this file had simply missed it, which is the shape of thing
 * a guard is for.
 *
 * The write was inside `setEmailNotifications(v => { ... })`, alongside a `toast.success`. A
 * state updater must be a pure function of the previous state — React may call it more than
 * once per update, and `reactStrictMode: true` in next.config.ts makes it do exactly that in
 * development. One tap produced two toasts and two writes.
 */

function sourceFiles(): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir)) {
      const full = join(dir, entry);
      if (statSync(full).isDirectory()) walk(full);
      else if (/\.tsx?$/.test(entry) && !entry.includes('.test.')) out.push(full);
    }
  };
  walk(join(process.cwd(), 'src'));
  return out;
}

/** Source with comments removed — this file's own prose names every pattern it bans. */
function code(file: string): string {
  return readFileSync(file, 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
    .replace(/\/\/.*$/gm, '');
}

describe('the scan sees real code', () => {
  it('finds the app', () => {
    expect(sourceFiles().length).toBeGreaterThan(40);
  });

  it('finds the files that actually use storage', () => {
    // If this hit zero the assertions below would pass having checked nothing.
    const users = sourceFiles().filter((f) => /\blocalStorage\b|\bsessionStorage\b/.test(code(f)));
    expect(users.length).toBeGreaterThanOrEqual(2);
  });
});

describe('browser storage is always allowed to fail', () => {
  it('every localStorage call sits inside a try', () => {
    /*
     * Checked per FUNCTION rather than per file: a file containing one `try` somewhere else
     * would otherwise satisfy a naive "the file has a try" check while an unguarded call sat
     * in a different function — which is precisely the state settings/page.tsx was in.
     */
    const offenders: string[] = [];
    for (const file of sourceFiles()) {
      const src = code(file);
      if (!/\b(localStorage|sessionStorage)\b/.test(src)) continue;

      const lines = src.split('\n');
      lines.forEach((line, i) => {
        if (!/\b(localStorage|sessionStorage)\.(get|set|remove)Item\b/.test(line)) return;
        /*
         * NEAREST PRECEDING `try {` versus nearest preceding `} catch` — not a count within a
         * fixed window. Counting flagged correct code: a twelve-line look-back from a guarded
         * call happened to include the CLOSING `} catch` of an earlier, unrelated try block,
         * so opens and closes balanced and the call looked unguarded. Whichever marker is
         * closer is the one that decides, which is both simpler and right.
         */
        const before = lines.slice(0, i).join('\n');
        const lastTry = before.lastIndexOf('try {');
        const lastCatch = Math.max(before.lastIndexOf('} catch'), before.lastIndexOf('}catch'));
        if (lastTry < 0 || lastCatch > lastTry) {
          offenders.push(`${file.replace(process.cwd() + '/', '')}:${i + 1}  ${line.trim()}`);
        }
      });
    }
    expect(
      offenders,
      'localStorage THROWS when a browser blocks site data. Unguarded inside a render or an ' +
        'effect, that takes the whole page down for the sake of a stored preference:\n' +
        offenders.join('\n'),
    ).toEqual([]);
  });
});

describe('state updaters do not do things', () => {
  it('no setState(prev => ...) body performs a side effect', () => {
    /*
     * React may invoke an updater more than once for a single update, and StrictMode
     * deliberately does. Anything inside it that is not a pure computation of the next state
     * therefore happens twice: a toast fires twice, a write lands twice, an analytics event
     * counts twice.
     *
     * Scoped to the updater's own braces so an effect on the LINE AFTER `setX(...)` — which is
     * the correct place for it — is not reported.
     */
    const SIDE_EFFECTS = /\b(toast\.\w+|localStorage\.\w+|sessionStorage\.\w+|fetch|router\.(push|replace))\s*\(/;
    const offenders: string[] = [];

    for (const file of sourceFiles()) {
      const src = code(file);
      // `setSomething((x) => {` … matched up to its closing `})`.
      /*
       * `setInterval` AND `setTimeout` ARE NOT STATE SETTERS, and `/\bset[A-Z]\w*\(/` matched
       * both — reporting every timer in the app. The property is "a React state updater",
       * which is a `setX` from `useState` called with a function of the previous state; the
       * timer APIs take a callback of no arguments. Excluding them by name is exact, and an
       * assertion that fires on correct code trains you to "fix" things that were already
       * right.
       */
      const TIMERS = /^set(Interval|Timeout|Immediate)$/;
      for (const m of src.matchAll(/\bset([A-Z]\w*)\(\s*\(?\w*\)?\s*=>\s*\{/g)) {
        if (TIMERS.test(`set${m[1]}`)) continue;
        let depth = 1;
        let i = m.index! + m[0].length;
        while (i < src.length && depth > 0) {
          if (src[i] === '{') depth++;
          else if (src[i] === '}') depth--;
          i++;
        }
        const body = src.slice(m.index! + m[0].length, i);
        const hit = body.match(SIDE_EFFECTS);
        if (hit) {
          const line = src.slice(0, m.index).split('\n').length;
          offenders.push(
            `${file.replace(process.cwd() + '/', '')}:${line}  ${hit[0]} inside ${m[0].trim()}`,
          );
        }
      }
    }
    expect(
      offenders,
      'A state updater must be a pure function of the previous state — React calls it more ' +
        'than once, and StrictMode guarantees it in dev, so each of these happens twice per ' +
        'update. Move it to the line after the setState call:\n' + offenders.join('\n'),
    ).toEqual([]);
  });
});
