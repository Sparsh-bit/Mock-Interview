'use client';

import { useEffect } from 'react';

/**
 * INERTIAL WHEEL SCROLLING FOR THE PUBLIC SITE — components/marketing/useSmoothScroll.ts
 *
 * The landing page is built around a sticky film whose beats are a function of scroll
 * position. A trackpad delivers that position in smooth sub-pixel increments; a mouse wheel
 * delivers it in ~100px jumps. The same film is therefore either a dissolve or a slideshow
 * depending on which device the visitor happens to own, and the slideshow version is the one
 * most people see. Easing the scroll position itself is what makes the two look alike.
 *
 * ── WHY IT EASES THE WINDOW AND NOT A TRANSFORMED WRAPPER ────────────────────────────────
 * The usual implementation of this (and what every smooth-scroll library does by default)
 * fixes the body at 100vh and translates an inner wrapper. That is a much smoother result and
 * it is unusable here, because a `transform` on an ancestor makes it the containing block for
 * every descendant — which silently kills `position: sticky` and every `100vh` stage inside
 * it. The film IS a sticky stage. So this eases `window.scrollTo` instead: slightly less
 * silky, and it keeps sticky positioning, scroll anchoring, the browser's own scrollbar
 * dragging, and `scrollIntoView` all working exactly as they do on any other page.
 *
 * ── WHAT IT DELIBERATELY DOES NOT TOUCH ──────────────────────────────────────────────────
 *  · Touch devices. Native momentum scrolling on iOS and Android is already better than this,
 *    and intercepting it produces the rubber-band fight that makes a site feel broken on a
 *    phone. Gated on `pointer: fine`.
 *  · `prefers-reduced-motion`. Easing the scroll is motion the visitor did not ask for and
 *    cannot stop; this is close to the centre of what that setting is for.
 *  · Anything inside `[data-native-scroll]`. The showcase carousel scrolls horizontally and
 *    the film's own panes scroll internally. Swallowing the wheel there would leave a region
 *    of the page that simply cannot be scrolled, which is worse than a jumpy page.
 *  · Keyboard, scrollbar drags, and `#hash` links, none of which raise a wheel event. Those
 *    still move the page directly; the loop notices the position changed underneath it and
 *    re-syncs rather than yanking back to its own target.
 *
 * ── THE TWO CONSTANTS ────────────────────────────────────────────────────────────────────
 * `EASE = 0.115` is the fraction of the remaining distance covered per frame: at 60fps a
 * 1000px jump is 90% resolved in about 300ms, which is long enough to read as deliberate and
 * short enough that a fast scroll does not feel like it is dragging an anchor. `MULT = 1`
 * keeps one wheel notch worth one wheel notch — multiplying it is how smooth-scroll
 * implementations end up feeling weightless and imprecise.
 */
const EASE = 0.115;
const MULT = 1;
/* The refresh rate `EASE` is expressed against. It is a unit, not an assumption about the
   display — see `tick`, which rescales for whatever the frame actually took. */
const BASE_HZ = 60;
/* A frame longer than this was a stall or a backgrounded tab, not a slow display. Easing
   across the whole gap in one step is a teleport; clamping turns it into a fast catch-up over
   the next few frames, which is what the eye expects after the main thread unblocks. */
const MAX_FRAME_MS = 64;
/* Below this, snap. Chasing the last half-pixel keeps a rAF loop alive forever and shows up
   as a permanently busy main thread in a performance trace. */
const EPSILON = 0.4;

export function useSmoothScroll(enabled = true) {
  useEffect(() => {
    if (!enabled) return;
    if (typeof window === 'undefined') return;

    const fine = window.matchMedia('(pointer: fine)');
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    if (!fine.matches || reduced.matches) return;

    let target = window.scrollY;
    let current = target;
    let frame = 0;
    let running = false;
    /* The last position this loop wrote, so a scroll event can be attributed. */
    let written = -1;

    const maxScroll = () =>
      Math.max(0, document.documentElement.scrollHeight - window.innerHeight);

    /* `behavior: 'instant'` is load-bearing, not a default spelled out.
       `window.scrollTo(0, y)` — the two-argument form — scrolls with behavior `auto`, and
       `auto` means "obey the scrolling element's computed `scroll-behavior`". Both
       `globals.css` (`html { scroll-smooth }`) and `marketing.css` (`html:has(.mk)`) set that
       to `smooth`, so every one of these sixty-a-second calls used to hand the browser a
       fresh ~300ms eased animation, each aborted by the next before it had travelled more
       than a pixel or two. The page crawled far behind the wheel and kept drifting for a
       second after it stopped — this loop easing a target the browser was itself easing
       towards. Passing an explicit behavior overrides the CSS for these writes only, so
       in-page `#hash` links keep their smooth scroll and this loop gets the raw seek it has
       always assumed it was making. */
    const seek = (y: number) => {
      window.scrollTo({ top: y, behavior: 'instant' });
      /* Read back rather than trusting `y`. The browser clamps and snaps to device pixels, so
         what it landed on is the only value the scroll event will report. */
      written = window.scrollY;
    };

    /* WHY THE EASE IS RESCALED BY FRAME TIME.
       `current += delta * EASE` covers a fixed fraction of the remaining distance *per frame*,
       which makes the scroll speed a function of the display's refresh rate: identical wheel
       input resolves in half the time on a 120Hz laptop as on a 60Hz monitor, and drags
       noticeably whenever the frame rate dips under load — which on this page is exactly when
       the film is being scrubbed and six mock-ups are on stage. The film's beats are a
       function of scroll position, so a scroll position that advances per-frame means the
       frames advance at a rate set by the hardware rather than by the wheel.

       Compounding the same per-frame fraction over `dt` worth of 60Hz frames is what makes it
       a rate per unit time instead: `1 - (1 - EASE)^n` is the fraction covered by n frames of
       an exponential ease, and n is simply how many base frames this one lasted. At exactly
       60Hz n is 1 and this is the original expression, unchanged. */
    let last = 0;

    const tick = (now: number) => {
      const dt = last ? Math.min(now - last, MAX_FRAME_MS) : 1000 / BASE_HZ;
      last = now;

      const delta = target - current;
      if (Math.abs(delta) < EPSILON) {
        current = target;
        seek(current);
        running = false;
        return;
      }
      current += delta * (1 - Math.pow(1 - EASE, dt / (1000 / BASE_HZ)));
      seek(current);
      frame = requestAnimationFrame(tick);
    };

    const start = () => {
      if (running) return;
      running = true;
      /* A resumed loop must not measure against the timestamp of whenever it last stopped. */
      last = 0;
      frame = requestAnimationFrame(tick);
    };

    const onWheel = (e: WheelEvent) => {
      /* Zoom, not scroll. Also the gesture a trackpad pinch produces. */
      if (e.ctrlKey || e.metaKey) return;
      /* Line and page deltas exist and are not pixels. Converting them badly is how a
         smooth-scroll ends up moving 3px per notch in Firefox. */
      if (e.deltaMode !== 0) return;

      const t = e.target as Element | null;
      if (t?.closest?.('[data-native-scroll]')) return;

      e.preventDefault();
      target = Math.min(maxScroll(), Math.max(0, target + e.deltaY * MULT));
      start();
    };

    /* Anything that moved the page without the wheel — a hash link, the scrollbar, a
       keyboard PageDown, the film's rail buttons, the browser restoring a position — becomes
       the new truth. Without this the next wheel notch teleports back to wherever the loop
       still believed it was.

       This asks "did I write this?" rather than "am I running?", and the difference is a bug
       rather than a refinement. The old `if (running) return` swallowed every one of those
       inputs that arrived DURING an ease, and the next frame's write then yanked the page
       back — so clicking a rail mark in the second after a wheel notch did nothing at all,
       and neither did dragging the scrollbar. Comparing against the last written position
       tells the loop's own echo apart from somebody else moving the page, at which point it
       can yield to any of them at any time. Yielding is just adopting the new position:
       `delta` collapses to zero and the loop retires on the next frame, leaving a programmatic
       smooth scroll to finish on its own. */
    const onScroll = () => {
      if (window.scrollY === written) return;
      target = window.scrollY;
      current = target;
    };

    const onResize = () => {
      target = Math.min(maxScroll(), target);
    };

    window.addEventListener('wheel', onWheel, { passive: false });
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onResize);

    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener('wheel', onWheel);
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onResize);
    };
  }, [enabled]);
}
