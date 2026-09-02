'use client';

import { useEffect, useRef } from 'react';

/**
 * THE HERO'S GROUND — components/marketing/LineArt.tsx
 *
 * A fan of hairlines that drifts across the top of the page, drawn to canvas.
 *
 * ── WHY THERE IS ANYTHING HERE AT ALL ────────────────────────────────────────────────────
 * A hero of flat cream with type on it is not restrained, it is unfinished — the same
 * diagnosis globals.css records about the palette this product used to have. But the
 * alternatives are worse. A gradient mesh, an aurora, a field of floating orbs: DESIGN-RULES
 * bans all three by name, and it bans them because they are what a page reaches for when it
 * has nothing to say and needs the top of it to look busy anyway.
 *
 * Hairlines are the way out. They are the same mark the rest of this product is built from —
 * the rule under an eyebrow, the ladder bars, the stroke of the brandmark — at a scale where
 * a hundred of them read as light on paper rather than as a hundred lines. Nothing here is a
 * gradient and nothing here glows.
 *
 * ── WHY CANVAS AND NOT SVG ───────────────────────────────────────────────────────────────
 * Sixty animated paths is sixty DOM nodes whose `d` attribute changes every frame. That is
 * sixty style recalculations and a full layer repaint per frame, and it is comfortably enough
 * to drop a mid-range Android below 30fps before any other work on the page has happened.
 * Canvas is one element and one paint. The whole animation is also inside a `pointer-events:
 * none` layer with `aria-hidden`, because it carries no information — by the colour test in
 * DESIGN-RULES, if this were removed nothing would be lost except the look of the page, which
 * is exactly the right amount for a background to be carrying.
 *
 * ── THE FOUR THINGS THAT STOP IT ─────────────────────────────────────────────────────────
 *  · `prefers-reduced-motion` — draws one frame and never starts the loop. The composition is
 *    identical; only the drift is gone.
 *  · Scrolled out of view — an IntersectionObserver cancels the frame. Below the hero this is
 *    a canvas nobody can see burning a core.
 *  · Tab hidden — browsers throttle rAF in background tabs but do not all stop it.
 *  · Unmount — the frame is cancelled and the observer disconnected, so a client-side
 *    navigation away from the landing page does not leave a loop running for the session.
 */

/* Line count is a judgement, not a constant to tune: at 34 the fan reads as individual
   strokes and looks like a wireframe, at 90 it reads as a grey wash. 58 is where it stops
   being lines and starts being light. */
const LINES = 58;
/* Radians per millisecond. Slow enough that the movement is only visible if you stop and look
   for it, which is the point — a background you can watch is a background competing. */
const DRIFT = 0.000045;

export function LineArt({ className }: { className?: string }) {
  const ref = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    let width = 0;
    let height = 0;
    let frame = 0;
    let visible = true;

    const resize = () => {
      /* Cap the device pixel ratio at 2. A 3x phone paints 9x the pixels of a 1x screen for a
         set of 1px lines nobody can resolve at that density anyway, and it is the difference
         between this costing nothing and this costing the frame budget. */
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const rect = canvas.getBoundingClientRect();
      width = rect.width;
      height = rect.height;
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const draw = (t: number) => {
      ctx.clearRect(0, 0, width, height);
      ctx.lineWidth = 1;

      const phase = t * DRIFT;

      for (let i = 0; i < LINES; i++) {
        const k = i / (LINES - 1);

        /* Every line starts off the left edge and leaves off the right, so the fan has no
           visible ends inside the frame — an end is a mark, and a mark asks to be read. */
        const y0 = height * (0.16 + k * 1.05);
        const y1 = height * (-0.25 + k * 0.72);

        /* Two control points, each swinging on its own slow sine with the line's index folded
           into the phase. That offset is what makes the fan breathe rather than slide:
           neighbouring lines are a few degrees apart, so the whole family shears. */
        const c1x = width * (0.24 + 0.06 * Math.sin(phase + k * 2.4));
        const c1y = y0 - height * (0.16 + 0.1 * Math.sin(phase * 1.3 + k * 3.1));
        const c2x = width * (0.68 + 0.07 * Math.cos(phase * 0.9 + k * 1.9));
        const c2y = y1 + height * (0.2 + 0.12 * Math.cos(phase + k * 2.7));

        /* Densest in the middle of the fan and fading at both edges, so the family has a
           centre of gravity instead of a hard boundary. The peak is 0.075 — at 0.12 the lines
           start reading as content and the headline has to fight them. */
        const alpha = 0.02 + 0.055 * Math.sin(Math.PI * k);

        ctx.strokeStyle = `rgba(122, 99, 80, ${alpha})`;
        ctx.beginPath();
        ctx.moveTo(-40, y0);
        ctx.bezierCurveTo(c1x, c1y, c2x, c2y, width + 40, y1);
        ctx.stroke();
      }
    };

    const loop = (t: number) => {
      draw(t);
      frame = requestAnimationFrame(loop);
    };

    resize();

    if (reduced) {
      draw(0);
    } else {
      frame = requestAnimationFrame(loop);
    }

    const onResize = () => {
      resize();
      if (reduced) draw(0);
    };

    const io = new IntersectionObserver(
      ([entry]) => {
        const nowVisible = entry.isIntersecting;
        if (nowVisible === visible) return;
        visible = nowVisible;
        if (reduced) return;
        if (visible) {
          frame = requestAnimationFrame(loop);
        } else {
          cancelAnimationFrame(frame);
          frame = 0;
        }
      },
      { rootMargin: '120px' },
    );
    io.observe(canvas);

    const onVisibility = () => {
      if (reduced) return;
      if (document.hidden) {
        cancelAnimationFrame(frame);
        frame = 0;
      } else if (visible && !frame) {
        frame = requestAnimationFrame(loop);
      }
    };

    window.addEventListener('resize', onResize);
    document.addEventListener('visibilitychange', onVisibility);

    return () => {
      cancelAnimationFrame(frame);
      io.disconnect();
      window.removeEventListener('resize', onResize);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, []);

  return <canvas ref={ref} aria-hidden className={className} />;
}
