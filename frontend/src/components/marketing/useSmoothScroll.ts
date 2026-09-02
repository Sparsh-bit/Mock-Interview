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

    const maxScroll = () =>
      Math.max(0, document.documentElement.scrollHeight - window.innerHeight);

    const tick = () => {
      const delta = target - current;
      if (Math.abs(delta) < EPSILON) {
        current = target;
        window.scrollTo(0, current);
        running = false;
        return;
      }
      current += delta * EASE;
      window.scrollTo(0, current);
      frame = requestAnimationFrame(tick);
    };

    const start = () => {
      if (running) return;
      running = true;
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
       keyboard PageDown, the browser restoring a position — becomes the new truth. Without
       this the next wheel notch teleports back to wherever the loop still believed it was. */
    const onScroll = () => {
      if (running) return;
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
