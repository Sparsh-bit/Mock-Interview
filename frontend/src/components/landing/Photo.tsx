'use client';

import Image from 'next/image';
import { useRef } from 'react';
import { motion, useInView, useReducedMotion, useScroll, useTransform } from 'framer-motion';
import { cn } from '@/lib/utils';

/**
 * Photography on the landing page.
 *
 * WHY THERE IS A COMPONENT FOR THIS AT ALL, rather than six `<Image>` tags.
 *
 * Three things have to be true of every photo on the site or the page stops
 * looking designed and starts looking assembled, and none of them survive being
 * re-typed by hand at six call sites:
 *
 *   1. ONE GRADE. Images sourced separately have different white balance,
 *      contrast and saturation. Passing all of them through the same warm grade
 *      is what makes a set read as a set. See `.photo-grade` in globals.css.
 *
 *   2. ONE ENTRANCE. Every photo arrives the same way — a slow scale-down from
 *      1.06 as it enters the viewport, so the image settles rather than pops.
 *      Paired with `WipeUp` on the surrounding text, the whole page has exactly
 *      one motion vocabulary.
 *
 *   3. RESERVED SPACE. Each variant declares its aspect ratio in CSS, so the
 *      box exists before the bytes land and nothing below it jumps. These are
 *      270–350KB photographs; without this the page would reflow visibly as
 *      each one arrives.
 *
 * ART DIRECTION, NOT DECORATION. `focus` and `objectPosition` set the crop. One
 * of the three images has an unusable region in frame — see CROP below — and the
 * crop is how it is kept out of shot. That is a real constraint being handled,
 * not a knob for its own sake.
 */

/* ── The image set ──────────────────────────────────────────────────────────
   Only three of the six supplied images are on the page. The reason is recorded
   here rather than in a commit message, because "why are there six of these in
   copy_images.sh and three on the site" is otherwise unanswerable.

   USED:
     desk     a student working — warm light, oak, plants. Nothing legible in
              frame, so nothing can be misread. The hero.
     arrival  a candidate walking into an office lobby at golden hour. The
              closing image: what the product is actually for.
     report   a printed score sheet on a table, with "74 / 100" ringed in red.
              Cropped to the ring by CROP.reportRing: the full frame is headed
              "MONTHLY PERFORMANCE REVIEW · OCT 2023" — the wrong document and a
              stale date — which the crop puts above the top edge.

   NOT USED:
     rewrite-speech.png    the notebook that dominates the frame is filled with
                           gibberish handwriting at fully legible size.
     target-blueprint.png  contains the literal words "Lorem ipsum dolor sit
                           amet" three times, plus garbled body text throughout.
     rounds-cards.png      flat pastel vector with scattered confetti shapes —
                           precisely the generated-illustration look that
                           DESIGN-RULES.md bans, and the thing that makes a page
                           read as machine-made.

   The three unused files are NOT in public/ — anything under public/ ships to
   the origin whether or not a page requests it, and that was 2.4MB of bytes
   nobody would ever download. `copy_images.sh` at the repo root re-copies all
   six from the source directory if they are wanted again. The two
   blueprint/notebook images would work if reshot with real text; the vector one
   would not, and should be replaced by product artefacts, which is what
   Artefacts.tsx already does.

   ── Format ───────────────────────────────────────────────────────────────
   JPEG at q78, not the source PNG. The three PNGs totalled 2.5MB; as JPEG they
   are 920KB for no visible difference on photographic content, where PNG's
   lossless compression buys nothing. This is done ahead of time rather than
   left to next/image because the app deploys to Cloudflare Pages via
   @cloudflare/next-on-pages, where Next's image optimizer does not run — an
   unoptimised <Image> there serves the original bytes at full size.          */

export const PHOTOS = {
  desk: {
    src: '/img/landing/hero-interview.jpg',
    alt: 'A student working through interview preparation at a desk, laptop open beside a notebook of worked problems.',
  },
  arrival: {
    src: '/img/landing/close-doorway.jpg',
    alt: 'A candidate walking into an office lobby in the morning, folder under one arm.',
  },
  report: {
    src: '/img/landing/finale-numbers.jpg',
    alt: 'A printed evaluation sheet on a table with a final score of 74 out of 100 circled in red pen.',
  },
} as const;

export type PhotoName = keyof typeof PHOTOS;

const RATIOS = {
  square: 'aspect-square',
  portrait: 'aspect-[4/5]',
  landscape: 'aspect-[4/3]',
  wide: 'aspect-[16/9]',
  panorama: 'aspect-[21/9]',
} as const;

const FOCUS = {
  center: 'object-center',
  top: 'object-top',
  bottom: 'object-bottom',
  left: 'object-left',
  right: 'object-right',
} as const;

/**
 * Precise crops, for when a named focus keyword is not enough.
 *
 * `objectPosition` is an escape hatch with exactly one job, and it is worth
 * spelling out because otherwise it looks like an unused knob:
 *
 * The report photograph is a 1:1 source. Dropped into a 16:9 box, object-cover
 * shows a band 56.25% of the source height, and the keyword positions can only
 * slide that band over the 43.75% of overflow. `center` lands on 22%–78%, which
 * includes the sheet's printed header — "MONTHLY PERFORMANCE REVIEW · OCT 2023",
 * the wrong document with a stale date, sitting at 31%. `bottom` clears it but
 * also clips the top of the ringed score.
 *
 * 80% down the overflow puts the band at 35%–91%: header gone, score ring whole,
 * the handwritten note and the coffee still in shot. That number is not a taste
 * call, it is arithmetic, which is why it is written down here.
 */
export const CROP = {
  /** Report sheet, 16:9 — clears the printed header, keeps the ringed score. */
  reportRing: 'center 80%',
} as const;

export function Photo({
  name,
  ratio = 'landscape',
  focus = 'center',
  objectPosition,
  priority = false,
  sizes = '(max-width: 768px) 100vw, 50vw',
  className,
  rounded = 'rounded-xl',
}: {
  name: PhotoName;
  ratio?: keyof typeof RATIOS;
  focus?: keyof typeof FOCUS;
  /** Raw CSS object-position. Overrides `focus`. See CROP. */
  objectPosition?: string;
  priority?: boolean;
  sizes?: string;
  className?: string;
  rounded?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, margin: '-10%' });
  const reduced = useReducedMotion();
  const photo = PHOTOS[name];

  return (
    <div
      ref={ref}
      className={cn(
        'photo-grade relative isolate overflow-hidden border border-border/70 bg-surface',
        RATIOS[ratio],
        rounded,
        className,
      )}
    >
      <motion.div
        className="absolute inset-0"
        initial={reduced ? false : { scale: 1.06 }}
        animate={inView || reduced ? { scale: 1 } : undefined}
        transition={{ duration: 1.4, ease: [0.16, 1, 0.3, 1] }}
      >
        <Image
          src={photo.src}
          alt={photo.alt}
          fill
          priority={priority}
          sizes={sizes}
          className={cn('object-cover', !objectPosition && FOCUS[focus])}
          style={objectPosition ? { objectPosition } : undefined}
        />
      </motion.div>
    </div>
  );
}

/**
 * A photograph that drifts against the scroll.
 *
 * Used once, on the closing image. Parallax everywhere is a 2014 tell; parallax
 * exactly once, on the last thing you see, reads as an ending. The movement is
 * 6% of the container height — below the threshold where it registers as an
 * effect, above the threshold where it does nothing.
 */
export function ParallaxPhoto({
  name,
  ratio = 'wide',
  focus = 'center',
  className,
  sizes = '100vw',
}: {
  name: PhotoName;
  ratio?: keyof typeof RATIOS;
  focus?: keyof typeof FOCUS;
  className?: string;
  sizes?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start end', 'end start'] });
  const y = useTransform(scrollYProgress, [0, 1], ['-6%', '6%']);
  const photo = PHOTOS[name];

  return (
    <div
      ref={ref}
      className={cn(
        'photo-grade relative isolate overflow-hidden border border-border/70 bg-surface',
        RATIOS[ratio],
        className,
      )}
    >
      {/* Oversized so the drift never exposes an edge. */}
      <motion.div
        className="absolute inset-x-0 -inset-y-[8%]"
        style={reduced ? undefined : { y }}
      >
        <Image
          src={photo.src}
          alt={photo.alt}
          fill
          sizes={sizes}
          className={cn('object-cover', FOCUS[focus])}
        />
      </motion.div>
    </div>
  );
}
