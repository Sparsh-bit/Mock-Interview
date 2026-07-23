/**
 * Shared Framer Motion presets — the single source of choreography for the
 * whole app. Use these instead of ad-hoc `initial`/`animate`/`transition`
 * props so every page moves with the same physics and timing.
 */
import type { Transition, Variants } from 'framer-motion';

// Apple-leaning eases — a slow-settling "out" curve for entrances, and a
// slight overshoot "spring" curve for playful pops (badges, score reveals).
export const easeOutExpo: Transition['ease'] = [0.16, 1, 0.3, 1];
export const easeSpring: Transition['ease'] = [0.34, 1.56, 0.64, 1];

export const fadeUp: Variants = {
  hidden: { opacity: 0, y: 16 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.6, ease: easeOutExpo },
  },
};

export const fadeIn: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { duration: 0.5, ease: easeOutExpo } },
};

export const scalePop: Variants = {
  hidden: { opacity: 0, scale: 0.92 },
  visible: {
    opacity: 1,
    scale: 1,
    transition: { duration: 0.45, ease: easeSpring },
  },
};

/** Wrap a list container with this, and each child with `fadeUp`/`scalePop`. */
export const staggerContainer = (staggerChildren = 0.08, delayChildren = 0): Variants => ({
  hidden: {},
  visible: {
    transition: { staggerChildren, delayChildren },
  },
});

/** Subtle lift + glow on hover — for cards and clickable panels. */
export const hoverLift = {
  whileHover: { y: -4, transition: { duration: 0.25, ease: easeOutExpo } },
  whileTap: { scale: 0.98 },
};

/** Slightly stronger press feedback for buttons. */
export const buttonTap = {
  whileHover: { scale: 1.02 },
  whileTap: { scale: 0.96 },
  transition: { duration: 0.15, ease: easeOutExpo },
};
