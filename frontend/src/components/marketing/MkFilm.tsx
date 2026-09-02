'use client';

import { useRef, useState } from 'react';
import { motion, useMotionValueEvent, useReducedMotion, useScroll, useTransform } from 'framer-motion';

import { cn } from '@/lib/utils';

import { ROUNDS } from './content';
import {
  CodingBeat,
  CommunicationBeat,
  GdBeat,
  InterviewBeat,
  QuizBeat,
  ReportBeat,
} from './film-beats';

/**
 * THE FILM — components/marketing/MkFilm.tsx
 *
 * A dark stage that takes the screen over and plays the six rounds, one beat at a time, at
 * whatever speed you turn the wheel.
 *
 * ── IT IS NOT A VIDEO, AND THAT IS THE POINT ─────────────────────────────────────────────
 * The obvious way to show a product doing six things is to record it and embed an MP4. This
 * is DOM, scrubbed by scroll position, and it beats a video on every axis that matters here:
 *
 *   · It weighs nothing. The equivalent 90 seconds of 1080p is 8–15MB before it plays a
 *     frame, on a page whose whole job is to load fast enough to be read.
 *   · It cannot go stale. When the report ring changes from four competencies to five, this
 *     changes with it; a video needs re-rendering, re-uploading and re-encoding, which is why
 *     product videos on landing pages are almost always a year out of date.
 *   · It is crisp at every density and it themes. A screen recording is pixels, and pixels of
 *     an interface look like pixels of an interface next to live type.
 *   · It is readable. The text in it is real text — selectable, searchable, and available to a
 *     screen reader, which a video's on-screen copy never is.
 *   · The visitor controls the clock. Nobody scrubs a landing-page video; everybody scrolls.
 *
 * There IS a real video on this site — the Remotion reel, in `MkReel` — and it sits further
 * down where somebody who has already decided to look can press play. That is the right place
 * for a film you watch. This is a film you drive.
 *
 * ── HOW THE SCRUB WORKS ──────────────────────────────────────────────────────────────────
 * The section is `FILM_VH` tall and holds one `position: sticky` stage a viewport high. So
 * scrolling through the section moves the page while the stage stays put, and the section's
 * own scroll progress — 0 at the top, 1 at the bottom — becomes the film's timeline.
 *
 * That timeline is spent in three parts:
 *
 *   0.00 → 0.07   THE TAKEOVER. The stage arrives as an inset, rounded, shadowed card with
 *                 paper visible around it, and grows to full bleed with square corners. This
 *                 is the only transition on the site that changes what kind of surface you
 *                 are looking at, and it is what makes a dark section a quarter of a page
 *                 long feel deliberate rather than like a theme bug.
 *   0.07 → 0.93   SIX BEATS, one per round, an equal slice each.
 *   0.93 → 1.00   THE RELEASE. The reverse of the takeover, so the page returns to paper the
 *                 same way it left it.
 *
 * ── WHY REACT STATE HOLDS THE BEAT AND MOTION VALUES HOLD EVERYTHING ELSE ────────────────
 * The stage's scale and radius change every frame; putting those in state is sixty React
 * renders a second of a subtree containing six product mock-ups. They are motion values, and
 * framer writes them straight to style without re-rendering anything.
 *
 * The active beat changes exactly five times across the whole section, and it needs to change
 * a `className` so that CSS animations can restart. That is what state is for. The two are
 * split on that line and not on any other.
 *
 * ── REDUCED MOTION GETS A DIFFERENT PAGE, NOT A STILLER ONE ──────────────────────────────
 * Every other animation on this site can be turned off and leave the same page behind. This
 * one cannot: with no motion there is no mechanism to advance the film, and the honest
 * translation of "a stage that reveals six things in turn" is six things, revealed. So under
 * `prefers-reduced-motion` this renders as a plain dark section with all six beats stacked and
 * visible, no sticky, no scrub, no 540vh of scrolling to get past.
 */

/* Six beats at ~78vh of travel each, plus the takeover and release. Shorter than this and a
   mouse wheel skips whole beats; longer and the film outstays the argument. */
const FILM_VH = 540;
const TAKEOVER_END = 0.07;
const RELEASE_START = 0.93;

const BEATS = [
  InterviewBeat,
  GdBeat,
  CodingBeat,
  CommunicationBeat,
  QuizBeat,
  ReportBeat,
] as const;

export function MkFilm() {
  const ref = useRef<HTMLElement | null>(null);
  const reduced = useReducedMotion();
  const [active, setActive] = useState(0);

  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ['start start', 'end end'],
  });

  /* The takeover and release, expressed once as three keyframe arrays that share the same
     four stops. Reading them side by side is how you check the release is actually the
     reverse of the entrance rather than approximately it. */
  const STOPS = [0, TAKEOVER_END, RELEASE_START, 1];
  const scale = useTransform(scrollYProgress, STOPS, [0.9, 1, 1, 0.93]);
  const radius = useTransform(scrollYProgress, STOPS, [26, 0, 0, 22]);
  const shadow = useTransform(scrollYProgress, STOPS, [0.5, 0, 0, 0.4]);
  const boxShadow = useTransform(shadow, (s) => `0 40px 90px -50px rgb(20 16 10 / ${s})`);

  useMotionValueEvent(scrollYProgress, 'change', (p) => {
    const span = RELEASE_START - TAKEOVER_END;
    const local = (p - TAKEOVER_END) / span;
    const next = Math.min(BEATS.length - 1, Math.max(0, Math.floor(local * BEATS.length)));
    setActive((prev) => (prev === next ? prev : next));
  });

  if (reduced) return <FilmStatic />;

  return (
    <section
      id="rounds"
      ref={ref}
      aria-label="The six rounds"
      className="relative bg-[var(--mk-bg)]"
      style={{ height: `${FILM_VH}vh` }}
    >
      <div className="sticky top-0 flex h-[100svh] items-center justify-center overflow-hidden">
        <motion.div
          /* The nav reads this to invert itself. It is on the stage rather than the section
             so the nav flips at the moment the dark surface actually reaches it, not when the
             540vh container's top edge does. */
          data-nav-dark
          style={{ scale, borderRadius: radius, boxShadow }}
          className="relative flex h-full w-full items-center justify-center overflow-hidden bg-[linear-gradient(180deg,var(--mk-dark-top)_0%,var(--mk-dark-bot)_100%)] will-change-transform"
        >
          {/* Grain and vignette. The vignette is doing real work: the beats are cream cards on
              near-black, and without a darkened edge the corners of the stage read as lighter
              than its centre — a flat fill under high-contrast content always does. */}
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 opacity-[0.06]"
            style={{
              backgroundImage:
                "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='120' height='120'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/></filter><rect width='120' height='120' filter='url(%23n)'/></svg>\")",
            }}
          />
          <div
            aria-hidden
            /* THE VIGNETTE, SIZED IN VIEWPORT UNITS. A fixed 150px blur with 36px of spread
               is a quarter of the way into a 390px phone from each edge, which darkened the
               beat card itself rather than the stage around it — the cards read grey and the
               gold label lost most of its brightness. Capping both against `vw` keeps the
               same proportion of the stage darkened at every width. */
            className="pointer-events-none absolute inset-0 z-[4]"
            style={{
              boxShadow: 'inset 0 0 min(150px, 22vw) min(36px, 5vw) rgb(0 0 0 / 0.55)',
            }}
          />

          {BEATS.map((Beat, i) => {
            const round = ROUNDS[i];
            return (
              <div
                key={round.id}
                /* `key` on the inner wrapper is what restarts the CSS animations: React
                   swaps the element when `active` changes, and a fresh element runs its
                   `animation` from frame zero. Toggling a class alone does not — the
                   animation is considered already played. */
                className={cn('mk-beat', i === active && 'on')}
                aria-hidden={i !== active}
              >
                <p className="mk-beat-label">{round.label}</p>
                <div key={i === active ? 'on' : 'off'} className="mk-beat-body">
                  <Beat />
                </div>
              </div>
            );
          })}

          {/* THE RAIL. Six marks down the right edge — where you are in the film and how much
              of it is left. It is also the only way to skip: each is a real button that
              scrolls to that beat's slice of the section, so somebody who wants the report
              does not have to wheel through five rounds to reach it. */}
          <nav
            aria-label="Rounds"
            className="absolute right-4 top-1/2 z-[6] hidden -translate-y-1/2 flex-col gap-3 sm:flex md:right-8"
          >
            {ROUNDS.map((round, i) => (
              <button
                key={round.id}
                type="button"
                aria-label={`${round.n} — ${round.name}`}
                aria-current={i === active || undefined}
                onClick={() => {
                  const el = ref.current;
                  if (!el) return;
                  const span = RELEASE_START - TAKEOVER_END;
                  const at = TAKEOVER_END + span * ((i + 0.35) / BEATS.length);
                  const top = el.offsetTop + (el.offsetHeight - window.innerHeight) * at;
                  window.scrollTo({ top, behavior: 'smooth' });
                }}
                className="group flex items-center gap-2.5"
              >
                <span
                  className={cn(
                    'mk-num text-[10px] tracking-[0.1em] transition-colors duration-300',
                    i === active
                      ? 'text-[var(--mk-gold-glow)]'
                      : 'text-[rgb(183_168_143/0.62)] group-hover:text-[var(--mk-on-dark-muted)]',
                  )}
                >
                  {round.n}
                </span>
                <span
                  className={cn(
                    'block h-[2px] rounded-full transition-all duration-500',
                    i === active
                      ? 'w-7 bg-[var(--mk-gold-glow)]'
                      : 'w-3.5 bg-[rgb(183_168_143/0.45)] group-hover:bg-[rgb(183_168_143/0.6)]',
                  )}
                />
              </button>
            ))}
          </nav>
        </motion.div>
      </div>
    </section>
  );
}

/**
 * THE REDUCED-MOTION CUT. Same six beats, same copy, no stage management — one dark band with
 * the rounds listed down it. Deliberately NOT the sticky version with the transitions
 * removed, which would render one beat and strand the other five behind a scroll that no
 * longer does anything.
 */
function FilmStatic() {
  return (
    <section
      id="rounds"
      data-nav-dark
      aria-label="The six rounds"
      className="mk-on-dark bg-[linear-gradient(180deg,var(--mk-dark-top)_0%,var(--mk-dark-bot)_100%)] py-20"
    >
      <div className="mk-shell">
        <p className="mk-eyebrow">Six rounds, not one</p>
        <ul className="mt-10 divide-y divide-white/10">
          {ROUNDS.map((round) => (
            <li key={round.id} className="grid gap-2 py-6 sm:grid-cols-[3rem_12rem_1fr]">
              <span className="mk-num text-[var(--mk-gold-glow)]">{round.n}</span>
              <span className="font-[family-name:var(--mk-font-display)] text-[1.25rem] text-[var(--mk-on-dark-bright)]">
                {round.name}
              </span>
              <span className="text-[var(--mk-small)] text-[var(--mk-on-dark-muted)]">
                {round.blurb}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
