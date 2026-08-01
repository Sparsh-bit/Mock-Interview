'use client';

import React, { useCallback, useRef, useState } from 'react';
import { motion, useMotionValue, useSpring, useTransform, useReducedMotion } from 'framer-motion';
import { cn } from '@/lib/utils';

/**
 * Interactive 3D primitives, built on CSS 3D transforms.
 *
 * WHY NOT THREE.JS / WEBGL. A real 3D engine costs ~600KB gzipped before a single
 * card is drawn, renders to a canvas (so the text stops being selectable, stops
 * being readable by a screen reader, and goes soft when the user zooms), and on
 * the mid-range Android phones most of our candidates use it drops frames and
 * eats battery.
 *
 * CSS `perspective` + `transform-style: preserve-3d` is genuine 3D — a real
 * perspective projection with per-element Z depth — composited on the GPU, at
 * essentially zero bundle cost, with the content staying as ordinary DOM. For
 * cards floating in space and tilting toward the pointer, it is not a compromise;
 * it is the better tool. A 3D ENGINE is what you reach for when you need meshes,
 * lighting and a camera you fly through, and a study roadmap needs none of that.
 *
 * Every component here honours `prefers-reduced-motion`: motion sickness is real,
 * and a roadmap that lurches at someone is worse than a flat one.
 */

/** Perspective container. Children with translateZ sit at real depths inside it. */
export const Stage3D: React.FC<{
  children: React.ReactNode;
  className?: string;
  /** Lower = stronger perspective. 1200px is a natural, non-fisheye camera. */
  depth?: number;
}> = ({ children, className, depth = 1200 }) => (
  <div
    className={cn('[transform-style:preserve-3d]', className)}
    style={{ perspective: `${depth}px` }}
  >
    {children}
  </div>
);

/**
 * A card that tilts toward the pointer in 3D.
 *
 * The tilt is inverted on the Y axis so the card leans *toward* the cursor — the
 * opposite feels subtly wrong, like the object is avoiding you.
 */
export const TiltCard: React.FC<{
  children: React.ReactNode;
  className?: string;
  /** Max tilt in degrees. Above ~12 it stops reading as depth and starts as a gimmick. */
  max?: number;
  /** How far the card lifts toward the viewer on hover. */
  lift?: number;
  accent?: string;
  onClick?: () => void;
  /** Accessible label when the whole card is the control. */
  label?: string;
}> = ({ children, className, max = 9, lift = 24, accent, onClick, label }) => {
  const ref = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();

  const px = useMotionValue(0.5);
  const py = useMotionValue(0.5);
  const hover = useMotionValue(0);

  const spring = { stiffness: 220, damping: 26, mass: 0.6 };
  const rotateY = useSpring(useTransform(px, [0, 1], [-max, max]), spring);
  const rotateX = useSpring(useTransform(py, [0, 1], [max, -max]), spring);
  // A motion value, not `useSpring(hovered ? lift : 0)`. Passing a plain number
  // only seeds the initial value — it never updates on re-render, so the lift
  // never actually animated.
  const z = useSpring(useTransform(hover, [0, 1], [0, lift]), spring);

  const sheen = useTransform(
    [px, py],
    ([x, y]: number[]) =>
      `radial-gradient(38% 38% at ${x * 100}% ${y * 100}%, ${accent ?? '#fff'}2e 0%, transparent 70%)`,
  );

  const onMove = useCallback(
    (e: React.MouseEvent) => {
      const el = ref.current;
      if (!el) return;
      // Measured from the OUTER, untransformed element. Reading the rect off the
      // rotating layer made the pointer fraction depend on a box that was itself
      // moving — a feedback loop that amplified the jitter it was caused by.
      const r = el.getBoundingClientRect();
      px.set((e.clientX - r.left) / r.width);
      py.set((e.clientY - r.top) / r.height);
      hover.set(1);
    },
    [px, py, hover],
  );

  const reset = useCallback(() => {
    hover.set(0);
    px.set(0.5);
    py.set(0.5);
  }, [px, py, hover]);

  const interactive = Boolean(onClick);

  return (
    /*
     * TWO LAYERS, DELIBERATELY.
     *
     * The outer element is the hit target and is NEVER transformed. The inner one
     * carries the 3D rotation and is pointer-events:none.
     *
     * Putting the click handler on the rotating element is what made these cards
     * take a dozen attempts to click: as the card tilted toward the cursor its
     * projected edge rotated out from under the pointer, firing mouseleave, which
     * reset the tilt, which brought the edge back, which fired mouseenter — an
     * oscillation that swallowed mousedown/mouseup pairs. A static hit area cannot
     * oscillate, so the click always lands.
     */
    <div
      ref={ref}
      onMouseMove={reduced ? undefined : onMove}
      onMouseLeave={reduced ? undefined : reset}
      onClick={onClick}
      onKeyDown={
        interactive
          ? (e) => {
              // Card-as-button must work from the keyboard too.
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onClick?.();
              }
            }
          : undefined
      }
      role={interactive ? 'button' : undefined}
      tabIndex={interactive ? 0 : undefined}
      aria-label={label}
      className={cn(
        'relative',
        interactive &&
          'cursor-pointer rounded-2xl outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2',
        className,
      )}
      style={{ transformStyle: 'preserve-3d' }}
    >
      {reduced ? (
        children
      ) : (
        <motion.div
          // NOT pointer-events-none. Disabling pointer events here also disabled
          // every checkbox, link and button INSIDE the card — the tilt fix broke
          // the card contents.
          //
          // It is not needed: the oscillation this component used to suffer came
          // from onMouseMove/onMouseLeave living on the rotating element. Those
          // handlers now sit on the static outer div, so the moving layer cannot
          // fire them and cannot oscillate. Children stay fully interactive, and
          // the browser hit-tests them correctly through the 3D transform.
          className="[transform-style:preserve-3d]"
          style={{ rotateX, rotateY, translateZ: z }}
        >
          {children}
          <motion.div
            aria-hidden
            className="pointer-events-none absolute inset-0 rounded-[inherit]"
            style={{ background: sheen, opacity: hover }}
          />
        </motion.div>
      )}
    </div>
  );
};

/**
 * A layer that drifts as the pointer moves across the whole scene.
 *
 * Different `depth` values on sibling layers produce parallax — the thing that
 * makes a flat page read as having actual space in it. Kept subtle; the effect
 * should be felt rather than noticed.
 */
export const ParallaxLayer: React.FC<{
  children: React.ReactNode;
  /** -1 (moves against the pointer, feels far) to 1 (moves with it, feels near). */
  depth?: number;
  className?: string;
}> = ({ children, depth = 0.4, className }) => {
  const reduced = useReducedMotion();
  const x = useMotionValue(0);
  const y = useMotionValue(0);
  const sx = useSpring(x, { stiffness: 120, damping: 30 });
  const sy = useSpring(y, { stiffness: 120, damping: 30 });

  React.useEffect(() => {
    if (reduced) return;
    const onMove = (e: MouseEvent) => {
      x.set((e.clientX / window.innerWidth - 0.5) * 40 * depth);
      y.set((e.clientY / window.innerHeight - 0.5) * 40 * depth);
    };
    window.addEventListener('mousemove', onMove);
    return () => window.removeEventListener('mousemove', onMove);
  }, [x, y, depth, reduced]);

  if (reduced) return <div className={className}>{children}</div>;
  return (
    <motion.div className={className} style={{ x: sx, y: sy }}>
      {children}
    </motion.div>
  );
};

/**
 * Number that counts up when it scrolls into view, and re-counts when it changes.
 *
 * The re-count matters: this shows the roadmap's total hours, which recomputes
 * every time the candidate moves the weeks or hours slider. An earlier version
 * latched a `started` ref on the first animation and never cleared it, so every
 * later value was ignored — the sliders moved and the number sat frozen, making
 * the whole control look broken.
 */
export const CountUp: React.FC<{
  to: number;
  suffix?: string;
  className?: string;
  duration?: number;
}> = ({ to, suffix = '', className, duration = 1.1 }) => {
  const reduced = useReducedMotion();
  const [shown, setShown] = useState(reduced ? to : 0);
  const [visible, setVisible] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);
  // Where the current animation starts from, so a slider change eases from the
  // number already on screen instead of snapping back to zero.
  const fromRef = useRef(0);
  const rafRef = useRef<number | null>(null);

  // Reveal on scroll, once.
  React.useEffect(() => {
    if (reduced) {
      setVisible(true);
      return;
    }
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          io.disconnect();
        }
      },
      { threshold: 0.4 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [reduced]);

  // Animate to the CURRENT target. Re-runs whenever `to` changes.
  React.useEffect(() => {
    if (!visible) return;
    if (reduced) {
      setShown(to);
      return;
    }

    const from = fromRef.current;
    const t0 = performance.now();

    const step = (now: number) => {
      const p = Math.min(1, (now - t0) / (duration * 1000));
      // easeOutExpo — fast start, gentle settle.
      const eased = p === 1 ? 1 : 1 - Math.pow(2, -10 * p);
      setShown(Math.round(from + (to - from) * eased));
      if (p < 1) {
        rafRef.current = requestAnimationFrame(step);
      } else {
        fromRef.current = to;
      }
    };
    rafRef.current = requestAnimationFrame(step);

    return () => {
      // Cancel in-flight frames before starting the next run, or dragging a slider
      // leaves several animations fighting over the same state.
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      fromRef.current = to;
    };
  }, [to, visible, reduced, duration]);

  return (
    <span ref={ref} className={cn('tabular-nums', className)}>
      {shown}
      {suffix}
    </span>
  );
};
