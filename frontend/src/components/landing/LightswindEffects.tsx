'use client';

import { useRef, useEffect, useState, useCallback } from 'react';
import { motion, useScroll, useTransform, useReducedMotion, useInView } from 'framer-motion';
import { cn } from '@/lib/utils';

/**
 * Lightswind-inspired animated components — built from scratch.
 *
 * These are visual effects inspired by Lightswind UI's component library,
 * implemented directly with Framer Motion and CSS. No external dependency.
 * Each component respects `prefers-reduced-motion`.
 */

/* ── Border Beam ─────────────────────────────────────────────────────────────
   An animated gradient beam that traces the border of its container.
   Apply to the artefact Frame cards for a premium luminous edge effect.      */

export function BorderBeam({
  children,
  className,
  duration = 6,
  colorFrom = 'hsl(211, 100%, 50%)',
  colorTo = 'hsl(245, 58%, 62%)',
}: {
  children: React.ReactNode;
  className?: string;
  duration?: number;
  colorFrom?: string;
  colorTo?: string;
}) {
  const reduced = useReducedMotion();

  return (
    <div className={cn('relative overflow-hidden rounded-xl', className)}>
      {!reduced && (
        <div
          className="pointer-events-none absolute inset-0 rounded-xl"
          style={{
            padding: '1px',
            background: `conic-gradient(from var(--beam-angle, 0deg), transparent 60%, ${colorFrom} 78%, ${colorTo} 82%, transparent 98%)`,
            mask: 'linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0)',
            maskComposite: 'xor',
            WebkitMask: 'linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0)',
            WebkitMaskComposite: 'xor',
            animation: `border-beam-spin ${duration}s linear infinite`,
          }}
        />
      )}
      {children}
    </div>
  );
}

/* ── Spotlight Card ──────────────────────────────────────────────────────────
   A surface that follows the cursor with a soft radial spotlight glow.       */

export function SpotlightCard({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const [isHovering, setIsHovering] = useState(false);
  const reduced = useReducedMotion();

  const handleMouseMove = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (!ref.current || reduced) return;
    const rect = ref.current.getBoundingClientRect();
    setPos({ x: e.clientX - rect.left, y: e.clientY - rect.top });
  }, [reduced]);

  return (
    <div
      ref={ref}
      onMouseMove={handleMouseMove}
      onMouseEnter={() => setIsHovering(true)}
      onMouseLeave={() => setIsHovering(false)}
      className={cn('relative overflow-hidden', className)}
    >
      {!reduced && isHovering && (
        <div
          className="pointer-events-none absolute inset-0 z-10 transition-opacity duration-300"
          style={{
            background: `radial-gradient(400px circle at ${pos.x}px ${pos.y}px, hsl(211 100% 50% / 0.08), transparent 60%)`,
            opacity: isHovering ? 1 : 0,
          }}
        />
      )}
      {children}
    </div>
  );
}

/* ── Text Shimmer ────────────────────────────────────────────────────────────
   A shimmer gradient sweep that moves across text when it enters view.       */

export function TextShimmer({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, margin: '-15%' as `${number}%` });
  const reduced = useReducedMotion();

  return (
    <span
      ref={ref}
      className={cn(
        'relative inline-block',
        !reduced && inView && 'animate-text-shimmer',
        className,
      )}
      style={
        !reduced
          ? {
              backgroundImage:
                'linear-gradient(90deg, currentColor 0%, hsl(211 100% 60%) 40%, hsl(245 58% 65%) 50%, currentColor 60%, currentColor 100%)',
              backgroundSize: '250% 100%',
              WebkitBackgroundClip: 'text',
              backgroundClip: 'text',
              WebkitTextFillColor: inView ? 'transparent' : undefined,
              color: inView ? 'transparent' : undefined,
            }
          : undefined
      }
    >
      {children}
    </span>
  );
}

/* ── Animated Counter ────────────────────────────────────────────────────────
   A number that counts up from 0 when it scrolls into view.                  */

export function AnimatedCounter({
  target,
  suffix = '',
  className,
  duration = 1.5,
}: {
  target: number;
  suffix?: string;
  className?: string;
  duration?: number;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, margin: '-10%' as `${number}%` });
  const reduced = useReducedMotion();
  const [count, setCount] = useState(0);

  useEffect(() => {
    if (!inView || reduced) {
      if (reduced) setCount(target);
      return;
    }

    let startTime: number | null = null;
    let raf: number;

    const step = (timestamp: number) => {
      if (!startTime) startTime = timestamp;
      const progress = Math.min((timestamp - startTime) / (duration * 1000), 1);
      // Ease out cubic
      const eased = 1 - Math.pow(1 - progress, 3);
      setCount(Math.floor(eased * target));
      if (progress < 1) {
        raf = requestAnimationFrame(step);
      } else {
        setCount(target);
      }
    };

    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [inView, target, duration, reduced]);

  return (
    <span ref={ref} className={cn('tabular-nums', className)}>
      {count}
      {suffix}
    </span>
  );
}

/* ── Floating Particles ──────────────────────────────────────────────────────
   Subtle floating circles for atmospheric backgrounds. Pure CSS animation.   */

export function FloatingParticles({
  count = 12,
  className,
}: {
  count?: number;
  className?: string;
}) {
  const reduced = useReducedMotion();

  if (reduced) return null;

  const particles = Array.from({ length: count }, (_, i) => {
    const size = 3 + Math.random() * 5;
    const left = Math.random() * 100;
    const delay = Math.random() * 8;
    const duration = 12 + Math.random() * 18;
    const hue = 200 + Math.random() * 60; // Blue to purple range

    return (
      <div
        key={i}
        className="absolute rounded-full opacity-20"
        style={{
          width: size,
          height: size,
          left: `${left}%`,
          top: `${-10 + Math.random() * 110}%`,
          background: `hsl(${hue} 70% 60%)`,
          animation: `float-particle ${duration}s ease-in-out ${delay}s infinite`,
        }}
      />
    );
  });

  return (
    <div className={cn('pointer-events-none absolute inset-0 overflow-hidden', className)}>
      {particles}
    </div>
  );
}

/* ── Scroll Progress ─────────────────────────────────────────────────────────
   A thin progress bar at the top of the viewport showing scroll completion.  */

export function ScrollProgress() {
  const { scrollYProgress } = useScroll();
  const reduced = useReducedMotion();

  if (reduced) return null;

  return (
    <motion.div
      className="fixed left-0 right-0 top-0 z-50 h-[2px] origin-left"
      style={{
        scaleX: scrollYProgress,
        background: 'linear-gradient(90deg, hsl(211 100% 50%), hsl(245 58% 62%))',
      }}
    />
  );
}

/* ── Scroll Image ────────────────────────────────────────────────────────────
   An image wrapper with subtle parallax — the image moves slower than the
   surrounding content, creating depth.                                       */

export function ScrollImage({
  src,
  alt,
  className,
  parallaxAmount = 40,
}: {
  src: string;
  alt: string;
  className?: string;
  parallaxAmount?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ['start end', 'end start'],
  });
  const y = useTransform(scrollYProgress, [0, 1], [parallaxAmount, -parallaxAmount]);
  const reduced = useReducedMotion();

  return (
    <div ref={ref} className={cn('relative overflow-hidden', className)}>
      <motion.div style={reduced ? {} : { y }}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={src}
          alt={alt}
          loading="lazy"
          className="h-full w-full object-cover"
        />
      </motion.div>
    </div>
  );
}
