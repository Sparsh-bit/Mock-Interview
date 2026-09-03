'use client';

import { useEffect, useRef, useState } from 'react';
import { Pause, Play } from 'lucide-react';

import { cn } from '@/lib/utils';

/**
 * THE FILM YOU WATCH — components/marketing/MkReel.tsx
 *
 * There are two films on this page and they are not redundant.
 *
 * `MkFilm` is the scroll-scrubbed one: DOM, weightless, driven by the wheel, and it plays
 * whether you want it to or not because it is the page. This is a real MP4, rendered from
 * Remotion (`promo/src/landing/`), 34 seconds, and it plays because somebody scrolled to it.
 * One is a mechanism for showing the product while a visitor scrolls past; the other is the
 * thing they watch when the scrolling has already convinced them. Putting the video where the
 * scroll-film is would have made the page 4MB heavier before the headline rendered.
 *
 * ── WHY THE SAME SIX BEATS TWICE ─────────────────────────────────────────────────────────
 * Because the film is rendered from the same content, at the same scale, in the same
 * palette — `promo/src/landing/theme.ts` carries the exact hexes from `marketing.css`. A
 * visitor who watched the video and then scrolls the page recognises the artefacts. Two
 * different mock-ups of the same screen would quietly tell them the product has neither.
 *
 * ── AUTOPLAY, AND THE FOUR CONDITIONS ON IT ──────────────────────────────────────────────
 * It autoplays, muted, in a loop — but only when at least half of it is on screen, and it
 * pauses the moment it is not. That is not politeness, it is the difference between a page
 * that costs a laptop 4% battery to scroll past and one that costs nothing. Three things
 * switch it off entirely:
 *
 *   · `prefers-reduced-motion` — a 34-second autoplaying loop is exactly the class of motion
 *     that setting exists to stop.
 *   · `navigator.connection.saveData` — somebody on a metered connection has told the browser
 *     not to spend their money on decoration.
 *   · A browser that refuses the play() promise. Every mobile browser will, under some
 *     settings, and an unhandled rejection there is a console error on every page load.
 *
 * In all three cases the poster frame and a play button remain, and pressing it plays the
 * video — the control is always real, never a decorative overlay on something already
 * playing.
 *
 * ── THERE IS NO SOUND, AND THE PAGE SAYS SO ──────────────────────────────────────────────
 * The film has no audio track at all. A muted autoplaying video normally implies a soundtrack
 * you are missing and prompts a hunt for the unmute button; saying so under the frame costs
 * one line and removes the question. Every claim in the film is on screen as type, which is
 * also what makes it work as a silent loop in the first place.
 */
export function MkReel() {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [playing, setPlaying] = useState(false);
  const [autoAllowed, setAutoAllowed] = useState(true);
  /** Set when the viewer presses pause themselves, so the observer stops overruling them. */
  const pausedByUser = useRef(false);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const saveData = Boolean(
      (navigator as Navigator & { connection?: { saveData?: boolean } }).connection?.saveData,
    );
    if (reduced || saveData) {
      setAutoAllowed(false);
      return;
    }

    /* No observer, no autoplay — and no crash. A throw inside an effect reaches the nearest
       error boundary, so an unguarded constructor turns a missing API into a blank page rather
       than a video that simply waits to be pressed. */
    if (typeof IntersectionObserver === 'undefined') {
      setAutoAllowed(false);
      return;
    }

    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          /* A visitor who pressed pause meant it. Scrolling the film out of view and back
             should not overrule them — autoplay resumes only what autoplay started. */
          if (pausedByUser.current) return;
          /* play() returns a promise that REJECTS when the browser declines — which it does
             on iOS Low Power Mode, on data-saver, and behind some autoplay settings. Left
             unhandled that is an uncaught rejection in the console of every page load. */
          video.play().then(
            () => setPlaying(true),
            () => setAutoAllowed(false),
          );
        } else {
          video.pause();
          setPlaying(false);
        }
      },
      { threshold: 0.5 },
    );

    io.observe(video);
    return () => io.disconnect();
  }, []);

  const toggle = () => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) {
      pausedByUser.current = false;
      video.play().then(
        () => setPlaying(true),
        () => setPlaying(false),
      );
    } else {
      pausedByUser.current = true;
      video.pause();
      setPlaying(false);
    }
  };

  return (
    <section
      data-nav-dark
      aria-label="The InterviewOS film"
      className="mk-on-dark relative overflow-hidden bg-[linear-gradient(180deg,var(--mk-dark-top)_0%,var(--mk-dark-warm)_100%)]"
    >
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.06]"
        style={{
          backgroundImage:
            "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='120' height='120'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/></filter><rect width='120' height='120' filter='url(%23n)'/></svg>\")",
        }}
      />

      <div className="mk-shell relative py-20 sm:py-24">
        <div className="text-center">
          <p className="mk-eyebrow justify-center">Thirty-four seconds</p>
          <h2
            className="mx-auto mt-5 max-w-[18ch] text-balance leading-[1.06]"
            style={{ fontSize: 'var(--mk-h2)' }}
          >
            The whole thing, <span className="mk-turn">start to score.</span>
          </h2>
        </div>

        <figure className="mt-10">
          <div className="group relative mx-auto aspect-video w-full max-w-[900px] overflow-hidden rounded-[var(--mk-r-card)] border border-white/10 shadow-[0_40px_100px_-50px_rgb(0_0_0/0.95)]">
            <video
              ref={videoRef}
              /* `poster` is what stands in for the first frame while the file loads, and it is
                 the frame somebody sees for the whole of a failed load. It is the title card
                 rather than a random frame, so a video that never plays still says what this
                 is. */
              poster="/video/landing-poster.jpg"
              muted
              loop
              playsInline
              /* `metadata`, not `auto`: the file is not fetched until the observer decides it
                 is about to be watched. On a page this long that is the difference between
                 3MB every visitor pays for and 3MB the ones who scroll here pay for. */
              preload="metadata"
              className="h-full w-full object-cover"
              onPlay={() => setPlaying(true)}
              onPause={() => setPlaying(false)}
            >
              {/* Two cuts of one master. The 720p is a third of the bytes and
                  indistinguishable inside a 400px-wide frame, which is what a phone renders
                  this at. `media` on a source is evaluated once at load, which is correct
                  here — nobody resizes a window across the breakpoint mid-film, and the
                  alternative costs a reload. */}
              <source src="/video/landing-1080.mp4" type="video/mp4" media="(min-width: 900px)" />
              <source src="/video/landing-720.mp4" type="video/mp4" />
            </video>

            {/* The control. Always present and always real — visible over the poster before
                anything plays, and fading to a hover-only affordance once it is running, so
                it never sits on top of the film it is controlling. */}
            <button
              type="button"
              onClick={toggle}
              aria-label={playing ? 'Pause the film' : 'Play the film'}
              className={cn(
                'absolute inset-0 grid place-items-center transition-opacity duration-300',
                /*
                 * `playing` ALONE. This also required `autoAllowed`, which is only ever set to
                 * false and never back — so for every reduced-motion visitor, every data-saver
                 * visitor, and anyone whose browser refused the first `play()`, pressing the
                 * button started the film and then left a full-bleed 35% black scrim and a
                 * 64px disc sitting on top of it for the whole 34 seconds. `autoAllowed`
                 * describes whether we may START it unprompted; it says nothing about whether
                 * it is playing now, which is the only thing this overlay should react to.
                 */
                playing
                  ? 'bg-transparent opacity-0 focus-visible:opacity-100 group-hover:opacity-100'
                  : 'bg-[rgb(14_11_8/0.35)] opacity-100',
              )}
            >
              <span className="grid h-16 w-16 place-items-center rounded-full border border-[var(--mk-gold-line)] bg-[rgb(20_16_10/0.55)] text-[var(--mk-gold-glow)] backdrop-blur-sm transition-transform duration-200 group-hover:scale-105">
                {playing ? (
                  <Pause className="h-6 w-6" strokeWidth={1.8} />
                ) : (
                  <Play className="ml-0.5 h-6 w-6" strokeWidth={1.8} />
                )}
              </span>
            </button>
          </div>

          <figcaption className="mx-auto mt-5 max-w-[900px] text-center text-[var(--mk-micro)] text-[var(--mk-on-dark-muted)]">
            No sound — every claim in it is on screen. Rendered from the product&rsquo;s own
            components, so it cannot show a screen the software does not have.
          </figcaption>
        </figure>
      </div>
    </section>
  );
}
