'use client';

import React, { Component, Suspense, lazy, useEffect, useState } from 'react';
import { useReducedMotion } from 'framer-motion';
import { cn } from '@/lib/utils';

/**
 * The Spline robot on the landing page.
 *
 * Deliberately NOT the snippet from Spline's docs, which is:
 *
 *   import Spline from '@splinetool/react-spline/next';
 *   <Spline scene="…/scene.splinecode" />
 *
 * Four reasons that does not drop into this project as-is:
 *
 *  1. The `/next` entry point is built for SERVER components. Our landing page is
 *     `'use client'` (framer-motion, hooks throughout), so the plain
 *     `@splinetool/react-spline` import is the correct one.
 *
 *  2. The scene is 1.33 MB and the runtime is roughly another megabyte. Imported
 *     statically it lands in the landing page's first load, which is the one page
 *     that must be fast — it is what a recruiter or a student sees before they
 *     have any reason to wait for us. So it is lazy-loaded and only starts
 *     downloading once the hero is actually on screen.
 *
 *  3. No loading state. Two megabytes on a college wifi connection is several
 *     seconds of empty space where the hero should be.
 *
 *  4. No failure path. This is a third-party asset on someone else's CDN; if
 *     prod.spline.design is unreachable the hero must degrade, not disappear.
 */

// Lazy so three.js/Spline's runtime is a separate chunk, fetched on demand.
const Spline = lazy(() => import('@splinetool/react-spline'));

const SCENE_URL = 'https://prod.spline.design/qX1suaIud0BvWxDG/scene.splinecode';

/** The gradient stand-in. Used while loading, on failure, and for reduced motion. */
function HeroFallback({ className, pulse = false }: { className?: string; pulse?: boolean }) {
  return (
    <div
      aria-hidden
      className={cn('relative overflow-hidden', className)}
      style={{
        background:
          'radial-gradient(42% 42% at 50% 45%, rgba(94,92,230,0.30) 0%, transparent 70%), radial-gradient(38% 38% at 62% 62%, rgba(0,138,230,0.28) 0%, transparent 70%)',
      }}
    >
      {pulse && (
        <div className="absolute inset-0 animate-pulse bg-gradient-to-br from-primary/5 to-accent-violet/5" />
      )}
    </div>
  );
}

export function SplineHero({
  className,
  /**
   * How much to enlarge the scene inside its box. The model is framed full-body
   * by its author; scaling up and anchoring to the top crops it at the waist,
   * which is the framing a hero wants — a head-and-torso portrait, not a full
   * figure shrunk into a corner.
   */
  zoom = 1.75,
  /**
   * Colour of the stage behind the scene. The bottom fade and the badge cover
   * both paint in it, so a wrong value shows as a light rectangle on a dark hero.
   */
  stage = 'hsl(var(--background))',
}: {
  className?: string;
  zoom?: number;
  stage?: string;
}) {
  const reduced = useReducedMotion();
  const [inView, setInView] = useState(false);
  const [failed, setFailed] = useState(false);
  const [node, setNode] = useState<HTMLDivElement | null>(null);

  // Only begin the ~2 MB download once the hero is actually visible. A ref
  // callback rather than useRef so this fires reliably on first mount.
  useEffect(() => {
    if (!node || reduced) return;
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setInView(true);
          io.disconnect();
        }
      },
      { rootMargin: '200px' },
    );
    io.observe(node);
    return () => io.disconnect();
  }, [node, reduced]);

  // Motion sickness is real, and this scene moves constantly.
  if (reduced) return <HeroFallback className={className} />;

  return (
    // overflow-hidden is what does the cropping: the canvas inside is larger than
    // this box and anchored to its top, so everything below the waist falls
    // outside and is clipped.
    <div ref={setNode} className={cn('relative overflow-hidden', className)}>
      {failed || !inView ? (
        <HeroFallback className="absolute inset-0" pulse={!failed} />
      ) : (
        <Suspense fallback={<HeroFallback className="absolute inset-0" pulse />}>
          <SplineBoundary onFail={() => setFailed(true)}>
            <div
              className="absolute left-1/2 top-0 h-full w-full"
              style={{
                // Scale from the top-centre so the head stays put and the legs
                // grow downward out of the frame.
                transform: `translateX(-50%) scale(${zoom})`,
                transformOrigin: 'top center',
              }}
            >
              <Spline
                scene={SCENE_URL}
                // Decoration sitting behind real content. Letting it capture the
                // pointer would swallow clicks on the buttons in front of it —
                // the same bug class as the tilt cards.
                style={{ width: '100%', height: '100%', pointerEvents: 'none' }}
                onError={() => setFailed(true)}
              />
            </div>
          </SplineBoundary>
        </Suspense>
      )}

      {/*
        Fade the crop edge into the page instead of ending on a hard cut, so the
        waist line reads as depth rather than as a mistake.
      */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 bottom-0 h-28"
        style={{ background: `linear-gradient(to top, ${stage} 8%, transparent)` }}
      />

      {/*
        Covers Spline's "Built with Spline" badge, which the runtime injects into
        the bottom-right of the canvas.

        NOTE FOR THE OWNER: Spline's free plan REQUIRES that attribution. Covering
        it is a licence question, not a technical one — check your plan before this
        goes public, or upgrade to remove it properly at source.
      */}
      <div
        aria-hidden
        className="pointer-events-none absolute bottom-0 right-0 h-16 w-44"
        style={{ background: stage }}
      />
    </div>
  );
}

/**
 * Catches a runtime failure inside the Spline canvas.
 *
 * Without this, a WebGL context failure (common on older Android, and on any
 * machine that has already exhausted its context limit) throws during render and
 * takes the entire landing page down with it. A decorative robot must never be
 * able to do that.
 */
class SplineBoundary extends Component<
  { children: React.ReactNode; onFail: () => void },
  { crashed: boolean }
> {
  state = { crashed: false };

  static getDerivedStateFromError() {
    return { crashed: true };
  }

  componentDidCatch() {
    this.props.onFail();
  }

  render() {
    if (this.state.crashed) return null;
    return this.props.children;
  }
}
