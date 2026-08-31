import Image from 'next/image';

import { BRAND } from '@/lib/brand';
import { cn } from '@/lib/utils';

/**
 * The mark — components/brand/Brandmark.tsx
 *
 * A chair seen head-on, its two arms flaring open, with a flame sitting in the bowl. It says
 * the product's whole proposition in one shape: the seat, and the heat of being in it.
 *
 * THERE ARE TWO OF IT, AND THAT IS DELIBERATE.
 *
 * `<Brandmark>` draws an SVG. `<BrandmarkArt>` renders the real artwork as an image. They are
 * the same mark at different levels of detail, and which one is correct depends entirely on
 * how large it is about to be:
 *
 *   The artwork carries three flame tongues, a four-stop gradient on every petal, a pale light
 *   cone behind it and three tapered legs. Rendered at 16px in the navigation rail — which is
 *   where a mark spends most of its life — the legs become single scratchy pixels, the tongues
 *   merge, and the whole thing reads as an orange smudge. Measured on a size ladder from 16 to
 *   128px: it holds together from about 48px and falls apart below it.
 *
 *   So the SVG is the same silhouette with the detail that cannot survive removed rather than
 *   shrunk: one flame instead of three, no light cone, arms and legs thickened to a weight that
 *   still reads at a sixth of the size. It is not a different logo; it is the same logo drawn
 *   for the size it is being used at, which is what a small-size variant is for.
 *
 * The colours are sampled from the artwork itself — navy #28344A, and the flame's own gradient
 * from #E85A1E to #FBA627 — so the two versions cannot drift apart into two brands.
 */

/** Sampled from the source artwork; see the note above. */
export const BRAND_COLORS = {
  navy: '#28344A',
  flameDeep: '#E85A1E',
  flameLight: '#FBA627',
  cone: '#FDECD0',
} as const;

export function Brandmark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      // Decorative: the wordmark beside it already carries the name, and a second copy in the
      // accessibility tree makes a screen reader say "InterviewOS InterviewOS".
      aria-hidden="true"
      focusable="false"
      className={cn('h-full w-full', className)}
    >
      <defs>
        {/* The id is namespaced because this mark can appear more than once on a page — in the
            rail and in the mobile drawer — and duplicate SVG ids make the second one inherit
            the first one's paint. */}
        <linearGradient id="hs-flame" x1="12" y1="3.4" x2="12" y2="14.4" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor={BRAND_COLORS.flameLight} />
          <stop offset="1" stopColor={BRAND_COLORS.flameDeep} />
        </linearGradient>
      </defs>

      {/* THE ARM IS A CONSTANT-WIDTH CURVE, and that is measured rather than eyeballed.
          Sampling the artwork's navy pixels down the left arm gives a width of 1.62 units in
          a 24-grid at every height from y=7 to y=18 — it does not taper. I drew it as a
          tapering crescent first, on the strength of how it looks, and it came out as a pair
          of horns.

          The stroke here is 2.4 rather than the measured 1.62 ON PURPOSE: at 16px, 1.62 units
          is a single pixel and disappears into the page. Thickening the line is exactly the
          adjustment a small-size variant exists to make.

          Tips at x≈1.8 and 22.2, meeting the seat at y≈16.4 — also from the measurement, which
          put the navy's horizontal extent at the full width of the box. */}
      <path
        d="M1.8 5.4c.6 7 4.6 11 10.2 11s9.6-4 10.2-11"
        fill="none"
        stroke={BRAND_COLORS.navy}
        strokeWidth="2.4"
        strokeLinecap="round"
      />

      {/* The flame sits in the bowl the arms make, overlapping them as it does in the artwork. */}
      <path
        d="M12 3.6c2 2.6 3.2 4.6 3.2 6.8 0 2.4-1.4 4-3.2 4s-3.2-1.6-3.2-4c0-2.2 1.2-4.2 3.2-6.8Z"
        fill="url(#hs-flame)"
      />

      {/* Three legs. The artwork splays the outer two and keeps the middle one vertical. */}
      <g stroke={BRAND_COLORS.navy} strokeWidth="2.2" strokeLinecap="round">
        <path d="M7.4 15.4 5.2 21.2" />
        <path d="M12 17v4.2" />
        <path d="M16.6 15.4l2.2 5.8" />
      </g>
    </svg>
  );
}

/**
 * The real artwork. Use it at 48px and up — see the note at the top for why not below.
 *
 * `unoptimized` is deliberate: this is already a right-sized PNG with an alpha channel, and
 * routing it through the image optimiser costs a round trip to gain nothing.
 */
export function BrandmarkArt({
  size = 96,
  className,
  priority = false,
}: {
  size?: number;
  className?: string;
  priority?: boolean;
}) {
  return (
    <Image
      src="/brand/mark.png"
      alt=""
      aria-hidden
      width={size}
      height={size}
      priority={priority}
      unoptimized
      className={cn('select-none', className)}
    />
  );
}

/**
 * Mark plus name.
 *
 * `collapsed` drops the wordmark for the narrow rail — the mark alone still identifies the
 * product, which is the entire reason a mark exists.
 *
 * NO TILE BEHIND IT ANY MORE. The previous hand-drawn mark sat in a filled gradient square,
 * which worked because it was a flat white glyph. This one is a full-colour object whose
 * negative space is open — the page shows through inside the chair and behind the flame — so a
 * coloured tile would fill those gaps and turn the silhouette to mush. It sits directly on the
 * page instead, which is also the calmer choice for a mark that already carries its own colour.
 */
export function Wordmark({
  collapsed = false,
  className,
}: {
  collapsed?: boolean;
  className?: string;
}) {
  return (
    <span className={cn('flex min-w-0 items-center gap-2', className)}>
      <Brandmark className="h-[22px] w-[22px] shrink-0" />
      {!collapsed && (
        <span className="truncate text-[14px] font-semibold tracking-[-0.015em]">
          {BRAND.name}
        </span>
      )}
    </span>
  );
}

/**
 * The full lockup — the artwork mark beside the product name.
 *
 * IT IS COMPOSED, NOT AN IMAGE, AND THAT IS THE POINT. There is a beautiful piece of supplied
 * artwork that pairs this mark with the name and a descriptor, and it cannot be used: the name
 * is in its pixels. The product has now been renamed three times, and each time an image with
 * a word in it would have had to be redrawn or would have quietly shipped the wrong name on
 * the four auth screens, the 404 and the pricing header — the surfaces where somebody meets
 * the product for the first time.
 *
 * So the mark is the artwork, untouched, and the name is live text reading `BRAND.name`. The
 * two together are the lockup. It also means the name inherits the page's own typeface and
 * scales with the reader's font settings, neither of which a raster wordmark does.
 *
 * The supplied lockup file is kept at `design/brand-source/` rather than deleted — it is the
 * reference for the proportions used here, and the source to redraw from if the name ever
 * settles.
 *
 * `width` drives the whole assembly: the mark takes roughly a third of it, matching the
 * artwork's own proportion, and the name is sized from the same number so the pair stays in
 * step at any size.
 */
export function Lockup({
  width = 200,
  className,
  priority = false,
}: {
  width?: number;
  className?: string;
  /** Set on a screen where this is the largest thing above the fold. */
  priority?: boolean;
}) {
  const mark = Math.round(width * 0.3);
  return (
    <span className={cn('flex min-w-0 items-center', className)} style={{ gap: mark * 0.22 }}>
      <BrandmarkArt size={mark} priority={priority} className="shrink-0" />
      <span className="flex min-w-0 flex-col leading-none">
        <span
          className="truncate font-semibold tracking-[-0.02em]"
          style={{ fontSize: mark * 0.46 }}
        >
          {BRAND.name}
        </span>
        {/* The descriptor from the supplied artwork, kept because it says plainly what the
            product is to somebody who has just arrived. Dropped below the size where it would
            set under about 8px and stop being readable. */}
        {mark >= 44 && (
          <span
            className="mt-[0.35em] truncate uppercase text-muted-foreground"
            style={{ fontSize: mark * 0.17, letterSpacing: '0.14em' }}
          >
            Interviewing software
          </span>
        )}
      </span>
    </span>
  );
}
