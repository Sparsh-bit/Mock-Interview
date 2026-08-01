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
}> = ({ children, className, max = 9, lift = 26, accent, onClick }) => {
  const ref = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();

  const px = useMotionValue(0.5);
  const py = useMotionValue(0.5);
  const [hovered, setHovered] = useState(false);

  // Springs, not raw values: a card that snaps to the cursor feels like a cheap
  // hover effect, one that eases feels like a physical object with weight.
  const spring = { stiffness: 220, damping: 26, mass: 0.6 };
  const rotateY = useSpring(useTransform(px, [0, 1], [-max, max]), spring);
  const rotateX = useSpring(useTransform(py, [0, 1], [max, -max]), spring);
  const z = useSpring(hovered ? lift : 0, spring);

  // Hoisted: a hook cannot live inside the conditional JSX below. React requires
  // the same hooks in the same order every render, and calling useTransform inside
  // `{accent && hovered && …}` would break that the first time the card is hovered.
  const sheen = useTransform(
    [px, py],
    ([x, y]: number[]) =>
      `radial-gradient(38% 38% at ${x * 100}% ${y * 100}%, ${accent ?? '#fff'}2e 0%, transparent 70%)`,
  );

  const onMove = useCallback((e: React.MouseEvent) => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    px.set((e.clientX - r.left) / r.width);
    py.set((e.clientY - r.top) / r.height);
  }, [px, py]);

  const reset = useCallback(() => {
    setHovered(false);
    px.set(0.5);
    py.set(0.5);
  }, [px, py]);

  if (reduced) {
    return (
      <div ref={ref} className={className} onClick={onClick}>
        {children}
      </div>
    );
  }

  return (
    <motion.div
      ref={ref}
      onMouseMove={onMove}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={reset}
      onClick={onClick}
      className={cn('relative [transform-style:preserve-3d]', className)}
      style={{ rotateX, rotateY, translateZ: z }}
    >
      {children}
      {/* Specular sheen that tracks the pointer. This is what sells the surface as
          tilting rather than just rotating — a flat rotation reads as a sprite. */}
      {accent && hovered && (
        <motion.div
          aria-hidden
          className="pointer-events-none absolute inset-0 rounded-[inherit] opacity-60"
          style={{ background: sheen }}
        />
      )}
    </motion.div>
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

/** Number that counts up when it scrolls into view. */
export const CountUp: React.FC<{
  to: number;
  suffix?: string;
  className?: string;
  duration?: number;
}> = ({ to, suffix = '', className, duration = 1.1 }) => {
  const [shown, setShown] = useState(0);
  const reduced = useReducedMotion();
  const started = useRef(false);
  const ref = useRef<HTMLSpanElement>(null);

  React.useEffect(() => {
    if (reduced) {
      setShown(to);
      return;
    }
    const el = ref.current;
    if (!el) return;

    const io = new IntersectionObserver(
      ([entry]) => {
        // Only ever run once: a number that re-counts every time it scrolls back
        // into view is distracting rather than delightful.
        if (!entry.isIntersecting || started.current) return;
        started.current = true;
        const t0 = performance.now();
        const step = (now: number) => {
          const p = Math.min(1, (now - t0) / (duration * 1000));
          // easeOutExpo — fast start, gentle settle.
          setShown(Math.round(to * (p === 1 ? 1 : 1 - Math.pow(2, -10 * p))));
          if (p < 1) requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
      },
      { threshold: 0.4 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [to, duration, reduced]);

  return (
    <span ref={ref} className={cn('tabular-nums', className)}>
      {shown}
      {suffix}
    </span>
  );
};
