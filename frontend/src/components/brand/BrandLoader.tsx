'use client';

import { BRAND_COLORS } from '@/components/brand/Brandmark';
import { cn } from '@/lib/utils';

/**
 * Loading, in the shape of the logo — components/brand/BrandLoader.tsx
 *
 * The mark is a chair with a flame in it, so the wait is a flame that burns: the chair holds
 * perfectly still and the flame rises, brightens and settles. Nothing spins. A spinner is a
 * generic object that says only "something is happening"; this says the same thing in the
 * product's own shape, and it is the one moment where an animated logo is not decoration —
 * during a wait, motion IS the information.
 *
 * WHY THE CHAIR DOES NOT MOVE. Animating the whole mark would read as a loading GIF of a logo.
 * Holding the frame still and moving only what is alive inside it is what makes it look like a
 * fire rather than a graphic being jiggled — and it keeps the silhouette legible throughout,
 * which a scaling or rotating mark does not.
 *
 * PURE CSS, NO JAVASCRIPT. This renders during route transitions and Suspense fallbacks —
 * exactly the moments when the JavaScript for the page has not arrived yet. A loader that
 * needs a hydrated React tree to animate is a loader that sits frozen for precisely as long as
 * it is needed. `steps`-free keyframes on transform and opacity also keep it on the compositor,
 * so it stays smooth on the mid-range Android phones DESIGN-RULES calls out.
 *
 * `prefers-reduced-motion` stops the flicker and leaves the mark sitting at full brightness —
 * still clearly the product, just not moving. The accessible status is on the wrapper, so a
 * screen reader hears the wait announced once rather than reading an animation.
 */
export function BrandLoader({
  label = 'Loading',
  size = 56,
  className,
}: {
  /** Announced to assistive technology, and shown beneath when `showLabel` is set. */
  label?: string;
  size?: number;
  className?: string;
}) {
  return (
    <div
      // `status` rather than `alert`: this is a state, not an interruption. `aria-live`
      // defaults to polite for status, which is right — it should not cut across whatever a
      // screen-reader user is currently hearing.
      role="status"
      aria-live="polite"
      className={cn('flex flex-col items-center gap-3', className)}
    >
      <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        aria-hidden="true"
        focusable="false"
        className="hs-loader"
      >
        <defs>
          <linearGradient
            id="hs-loader-flame"
            x1="12"
            y1="3.6"
            x2="12"
            y2="14.4"
            gradientUnits="userSpaceOnUse"
          >
            <stop offset="0" stopColor={BRAND_COLORS.flameLight} />
            <stop offset="1" stopColor={BRAND_COLORS.flameDeep} />
          </linearGradient>
        </defs>

        {/* The bowl, the seat's legs — the parts that are furniture, and hold still. */}
        <path
          d="M1.8 5.4c.6 7 4.6 11 10.2 11s9.6-4 10.2-11"
          fill="none"
          stroke={BRAND_COLORS.navy}
          strokeWidth="2.4"
          strokeLinecap="round"
        />
        <g stroke={BRAND_COLORS.navy} strokeWidth="2.2" strokeLinecap="round">
          <path d="M7.4 15.4 5.2 21.2" />
          <path d="M12 17v4.2" />
          <path d="M16.6 15.4l2.2 5.8" />
        </g>

        {/* The flame, and the only thing that moves.
            `transform-box: fill-box` with a bottom-centre origin makes it grow from where a
            flame is anchored rather than from the middle of the SVG — without it the whole
            shape drifts as it scales, which reads as a wobble rather than a burn. */}
        <path
          className="hs-flame"
          d="M12 3.6c2 2.6 3.2 4.6 3.2 6.8 0 2.4-1.4 4-3.2 4s-3.2-1.6-3.2-4c0-2.2 1.2-4.2 3.2-6.8Z"
          fill="url(#hs-loader-flame)"
        />
      </svg>

      <span className="sr-only">{label}</span>
    </div>
  );
}

/**
 * The same loader, centred in the space it is given, with the wait named.
 *
 * Naming it matters more than it looks: "Loading" tells somebody the page is working, and
 * "Building your interview" tells them why it is taking a moment — which is the difference
 * between waiting and wondering whether it has broken.
 */
export function BrandLoaderScreen({
  label = 'Loading',
  className,
}: {
  label?: string;
  className?: string;
}) {
  return (
    <div className={cn('flex min-h-[50vh] flex-col items-center justify-center gap-4', className)}>
      <BrandLoader label={label} size={64} />
      <p aria-hidden className="text-sm text-muted-foreground">
        {label}
      </p>
    </div>
  );
}
