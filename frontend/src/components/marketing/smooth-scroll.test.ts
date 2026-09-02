import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * THE WHEEL LOOP DOES NOT DOUBLE-EASE — components/marketing/smooth-scroll.test.ts
 *
 * WHY THIS EXISTS. `useSmoothScroll` eases the window's scroll position itself, writing a new
 * position on every animation frame. `globals.css` and `marketing.css` both set
 * `scroll-behavior: smooth` on `html`. Those two facts are individually reasonable and
 * together they broke the landing page:
 *
 *   `window.scrollTo(0, y)` — the two-argument form — scrolls with behavior `auto`, and `auto`
 *   means "use the scrolling element's computed `scroll-behavior`". So each of the loop's
 *   sixty writes a second asked the browser to start its OWN ~300ms eased animation, and the
 *   next frame aborted it a pixel or two in. The page crawled a long way behind the wheel and
 *   carried on drifting after the wheel stopped.
 *
 * Neither half looks wrong on its own, which is exactly why this needs pinning: the next
 * person to add a `scroll-smooth` somewhere, or to "simplify" the options object back to the
 * two-argument call, reintroduces it and the symptom shows up as vague scroll lag rather than
 * as a stack trace.
 *
 * These read source text rather than driving a browser because jsdom does not implement
 * scrolling at all — `window.scrollTo` there is a no-op that cannot express the bug. The
 * real check is Playwright's, and this is the cheap guard that runs on every commit.
 */

const HOOK = readFileSync(join(process.cwd(), 'src/components/marketing/useSmoothScroll.ts'), 'utf8');
const GLOBALS = readFileSync(join(process.cwd(), 'src/app/globals.css'), 'utf8');
const MARKETING = readFileSync(join(process.cwd(), 'src/app/marketing.css'), 'utf8');

/** Strip block comments, so prose about the bug never satisfies a test about the bug. */
const code = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, '');

describe('the inertial wheel loop', () => {
  it('never uses the positional scrollTo(x, y) form, which inherits CSS smooth behavior', () => {
    expect(code(HOOK)).not.toMatch(/scrollTo\s*\(\s*[^{]/);
  });

  it('names an explicit non-smooth behavior on every scroll it writes', () => {
    const calls = [...code(HOOK).matchAll(/scrollTo\s*\(\s*\{([^}]*)\}/g)];
    expect(calls.length).toBeGreaterThan(0);
    for (const [, opts] of calls) {
      expect(opts).toMatch(/behavior:\s*'instant'/);
    }
  });

  it('still yields the wheel to regions that scroll themselves', () => {
    // Swallowing the wheel over the marquee or the showcase rail leaves them unscrollable.
    expect(code(HOOK)).toMatch(/\[data-native-scroll\]/);
  });

  it('yields to other scrollers by attributing the scroll, not by a running flag', () => {
    /* `if (running) return` swallowed the scrollbar, PageDown and the film's rail buttons for
       the whole length of an ease. The loop must instead compare against what it last wrote. */
    // Scoped to onScroll: `start()` guards on `running` for a different and correct reason
    // — it stops a second rAF loop being spawned alongside the first.
    const onScroll = code(HOOK).match(/const onScroll = \(\) => \{([\s\S]*?)\n    \};/);
    expect(onScroll, 'onScroll not found in useSmoothScroll.ts').toBeTruthy();
    expect(onScroll![1]).not.toMatch(/\brunning\b/);
    expect(onScroll![1]).toMatch(/window\.scrollY === written/);
  });
});

describe('the ease advances per second, not per frame', () => {
  /* The film's beats are a function of scroll position, so if scroll position advances by a
     fixed fraction PER FRAME then the film advances at a rate set by the display, not by the
     wheel: the same flick plays it twice as fast on a 120Hz laptop as on a 60Hz monitor, and
     visibly drags whenever the frame rate dips — which on this page is precisely while the
     film is on stage and six mock-ups are mounted. */

  it('compounds the per-frame fraction over the frame duration', () => {
    const src = code(HOOK);
    expect(src).not.toMatch(/current \+= delta \* EASE\s*;/);
    expect(src).toMatch(/Math\.pow\(1 - EASE/);
  });

  it('clamps a stalled frame instead of easing across the whole gap', () => {
    expect(code(HOOK)).toMatch(/Math\.min\(now - last, MAX_FRAME_MS\)/);
  });

  it('resets its clock when the loop restarts, not carrying a stale timestamp', () => {
    const start = code(HOOK).match(/const start = \(\) => \{([\s\S]*?)\n    \};/);
    expect(start, 'start() not found').toBeTruthy();
    expect(start![1]).toMatch(/last = 0/);
  });

  it('is genuinely refresh-rate invariant — the technique, checked numerically', () => {
    /* Verifies the identity the hook relies on rather than the hook's copy of it: n frames of
       an exponential ease cover `1 - (1 - e)^n` of the distance, so rescaling the exponent by
       real elapsed time makes total travel depend on time alone. */
    const EASE = Number(code(HOOK).match(/const EASE = ([\d.]+)/)![1]);
    expect(EASE).toBeGreaterThan(0);
    expect(EASE).toBeLessThan(1);

    const step = (dtMs: number) => 1 - Math.pow(1 - EASE, dtMs / (1000 / 60));
    /* Steps to exactly `overMs`, with a partial final frame — otherwise 144Hz simulates only
       97.2ms of the 100 and the comparison measures the leftover, not the property. */
    const travel = (hz: number, overMs: number) => {
      const dt = 1000 / hz;
      let remaining = 1;
      for (let t = 0; t < overMs; ) {
        const d = Math.min(dt, overMs - t);
        remaining -= remaining * step(d);
        t += d;
      }
      return 1 - remaining;
    };

    // 100ms of easing covers the same ground at 60, 120 and 144Hz.
    const at60 = travel(60, 100);
    expect(travel(120, 100)).toBeCloseTo(at60, 10);
    expect(travel(144, 100)).toBeCloseTo(at60, 10);
    expect(travel(30, 100)).toBeCloseTo(at60, 10);

    // And the old per-frame form did not — this is the bug being pinned, not a truism.
    const naive = (hz: number, overMs: number) =>
      1 - Math.pow(1 - EASE, Math.floor(overMs / (1000 / hz)));
    expect(Math.abs(naive(120, 100) - naive(60, 100))).toBeGreaterThan(0.15);

    // At exactly 60Hz the rescaling is a no-op, so the tuned feel is unchanged.
    expect(step(1000 / 60)).toBeCloseTo(EASE, 12);
  });
});

describe('the data-native-scroll opt-out', () => {
  /* The attribute means "this region scrolls itself, keep the wheel loop off it". Put it on
     something that does not scroll and the opposite happens: the loop steps aside, the region
     has nothing to scroll, so the browser scrolls the PAGE natively — a band with different
     physics from the rest of the document. It was on the hero marquee, which is
     `overflow: hidden` and animates by CSS, sitting full-width directly under the fold. */
  const files = readdirSync(join(process.cwd(), 'src/components/marketing'))
    .filter((f) => f.endsWith('.tsx'));

  const SCROLLS = /overflow-(x-|y-)?(auto|scroll)/;

  it('is only on elements that are themselves scrollers', () => {
    const offenders: string[] = [];
    for (const f of files) {
      const src = code(readFileSync(join(process.cwd(), 'src/components/marketing', f), 'utf8'));
      // The opening tag the attribute sits in, back to its `<`.
      for (const m of src.matchAll(/<[a-zA-Z][^<>]*?\bdata-native-scroll\b[^<>]*?>/g)) {
        if (!SCROLLS.test(m[0])) offenders.push(`${f}: ${m[0].replace(/\s+/g, ' ').slice(0, 90)}`);
      }
    }
    expect(offenders, 'data-native-scroll on a non-scrolling element').toEqual([]);
  });

  it('is still on the one region that does scroll itself', () => {
    // Guard against the above being satisfied by deleting every use of the attribute.
    const showcase = readFileSync(join(process.cwd(), 'src/components/marketing/MkShowcase.tsx'), 'utf8');
    expect(code(showcase)).toMatch(/data-native-scroll/);
  });
});

describe('a full-screen overlay must contain its own scroller', () => {
  /* An overlay that is `fixed inset-0` while `body` is locked is the only thing on screen that
     can scroll. If it has no scroll container, tall content is simply unreachable — and with
     `justify-center` it is unreachable at BOTH ends, which on the landing page's menu meant
     the "Start free" button. `components/layout/MobileNav.tsx` is the signed-in equivalent and
     has always had `flex-1 overflow-y-auto`; this pins the public copy to the same shape. */
  const NAV = readFileSync(join(process.cwd(), 'src/components/marketing/MkNav.tsx'), 'utf8');

  it('the mobile sheet scrolls', () => {
    const src = code(NAV);
    const sheet = src.match(/<nav[^>]*>/g)?.filter((t) => /flex-1/.test(t)) ?? [];
    expect(sheet.length, 'the flex-1 sheet nav was not found').toBeGreaterThan(0);
    for (const tag of sheet) expect(tag).toMatch(/overflow-y-auto/);
  });

  it('does not centre unsafely over a scroller', () => {
    /* Plain `justify-center` on a scroll container pushes overflow past the start edge, where
       no scrollbar can reach it. `safe center` degrades to flex-start instead. */
    const src = code(NAV);
    for (const tag of src.match(/<nav[^>]*>/g) ?? []) {
      if (!/overflow-y-auto/.test(tag)) continue;
      expect(tag).not.toMatch(/\bjustify-center\b/);
    }
  });

  it('and the wheel loop lets it scroll', () => {
    // A new scroller on this page is useless if the inertial loop swallows the wheel over it.
    const src = code(NAV);
    for (const tag of src.match(/<nav[^>]*>/g) ?? []) {
      if (!/overflow-y-auto/.test(tag)) continue;
      expect(tag).toMatch(/data-native-scroll/);
    }
  });
});

describe('scroll-behavior: smooth', () => {
  /* `html` is not a descendant of `.mk`, so marketing.css's blanket `.mk *` reduced-motion
     reset cannot reach it. Each rule that sets it on `html` has to carry its own guard. */
  const guarded = (raw: string) => {
    const css = code(raw);
    for (const m of css.matchAll(/scroll-behavior:\s*smooth/g)) {
      const before = css.slice(0, m.index);
      const opened = [...before.matchAll(/@media\s*\(prefers-reduced-motion:\s*no-preference\)/g)];
      expect(
        opened.length,
        'a bare `scroll-behavior: smooth` on html is motion the visitor cannot switch off',
      ).toBeGreaterThan(0);
    }
  };

  it('is gated on prefers-reduced-motion in globals.css', () => guarded(GLOBALS));
  it('is gated on prefers-reduced-motion in marketing.css', () => guarded(MARKETING));

  it('is not re-applied through the scroll-smooth utility class', () => {
    // `@apply scroll-smooth` is the ungated spelling that caused this; it reads as a token.
    expect(code(GLOBALS)).not.toMatch(/@apply[^;]*\bscroll-smooth\b/);
    expect(code(MARKETING)).not.toMatch(/@apply[^;]*\bscroll-smooth\b/);
  });
});
