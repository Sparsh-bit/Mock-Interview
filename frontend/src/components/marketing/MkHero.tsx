'use client';

import Link from 'next/link';
import { ArrowRight, ChevronDown, Play } from 'lucide-react';

import { COMPANY_COUNT, RECRUITERS, TRACK_COUNT } from './content';
import { LineArt } from './LineArt';

/**
 * THE HERO — components/marketing/MkHero.tsx
 *
 * ── THE HEADLINE ─────────────────────────────────────────────────────────────────────────
 * "Practise the real thing, before the real thing." It is the line the previous landing page
 * closed on, moved to the top, because it was always the best sentence on the page and it was
 * sitting where only people who had already decided would read it.
 *
 * The second clause is set in Fraunces italic and in gold. That is the site's one recurring
 * typographic move and it is used the same way every time: the italic marks the turn in the
 * sentence — the point where the line stops describing and starts arguing. Roman, italic,
 * full stop. If a heading has no turn in it, it gets no italic.
 *
 * ── WHY THE HERO IS CENTRED WHEN NOTHING ELSE ON THE PAGE IS ─────────────────────────────
 * DESIGN-RULES bans "everything centred", and every section below this one is asymmetric with
 * no two sharing a grid. The hero is the deliberate exception. It has no second column to
 * balance against — the product shot that would normally sit on the right is the film,
 * immediately below, at full width and forty times the size. Centring one element and then
 * never centring anything again reads as a decision; centring the hero because there was
 * nothing to put beside it is the thing the rule is about, and it is not what is happening
 * here.
 *
 * ── WHY THERE IS NO PRODUCT SCREENSHOT ABOVE THE FOLD ────────────────────────────────────
 * The next full viewport is a dark stage that takes the screen over and plays the product for
 * ninety seconds. Putting a still of the same product 300px above it spends the reveal before
 * it happens. The hero's job is to make you scroll once.
 */
export function MkHero() {
  return (
    <section className="mk-grain relative isolate overflow-hidden">
      {/* The fan sits behind everything and is clipped by this section, so it never runs into
          the band below. `inset-0` on an `isolate` parent rather than `fixed`, so it scrolls
          away with the hero instead of following the page down. */}
      <LineArt className="absolute inset-0 -z-10 h-full w-full" />

      {/* Two very low radial washes — amber high-left, gold low-right — at 6% and 5%. The
          same device globals.css calls `.hero-wash`, at the same restraint: enough that the
          top of the page is not the identical flat field as the body, far short of a
          gradient. */}
      <div
        aria-hidden
        className="absolute inset-0 -z-10"
        style={{
          background:
            'radial-gradient(72% 48% at 16% 0%, rgb(200 146 58 / 0.09), transparent 68%), radial-gradient(58% 44% at 88% 8%, rgb(160 120 70 / 0.06), transparent 70%)',
        }}
      />

      <div className="mk-shell flex min-h-[100svh] flex-col">
        <div className="flex flex-1 flex-col items-center justify-center pb-14 pt-32 text-center sm:pt-36">
          <h1
            className="max-w-[16ch] text-balance font-[family-name:var(--mk-font-display)] font-[480] leading-[0.98] tracking-[-0.03em] text-[var(--mk-ink)]"
            style={{ fontSize: 'var(--mk-display)' }}
          >
            Practise the real thing,{' '}
            <span className="mk-turn">before the real thing.</span>
          </h1>

          <p
            className="mt-7 max-w-[52ch] text-pretty leading-[1.6] text-[var(--mk-body)]"
            style={{ fontSize: 'var(--mk-lead)' }}
          >
            A mock interview that pushes back. It cross-questions a thin answer, reads your
            resume, measures how you actually speak — and scores you out of a hundred.
          </p>

          <div className="mt-9 flex flex-col items-center gap-3 sm:flex-row">
            <Link href="/register" className="mk-btn mk-btn-primary w-full sm:w-auto">
              Start a mock interview
              <ArrowRight className="mk-arrow h-4 w-4" strokeWidth={2.2} />
            </Link>
            <Link href="/demo" className="mk-btn mk-btn-ghost w-full sm:w-auto">
              <Play className="h-[15px] w-[15px]" strokeWidth={2.2} />
              See a sample report
            </Link>
          </div>

          <p className="mk-num mt-5 text-[var(--mk-micro)] text-[var(--mk-muted)]">
            Free to start · no card
          </p>
        </div>

        {/* The scroll cue. It exists because the section directly below is 540vh of sticky
            stage: on a phone the hero fills the screen exactly, and without a cue a visitor
            has no way to know that the page has not simply ended. */}
        <div className="flex justify-center pb-6">
          <a
            href="#rounds"
            aria-label="Skip to what it does"
            className="mk-scroll-cue grid h-10 w-10 place-items-center rounded-full border border-[var(--mk-border)] bg-[var(--mk-surface)] text-[var(--mk-body)] shadow-[var(--mk-shadow-card)] transition-colors hover:text-[var(--mk-ink)]"
          >
            <ChevronDown className="h-4 w-4" strokeWidth={2} />
          </a>
        </div>
      </div>

      <HeroMarquee />
    </section>
  );
}

/**
 * THE TRACK MARQUEE.
 *
 * The reference this page answers to runs a live job-count ticker here — a number that moves
 * because their database moves. Ours does not move, so it does not pretend to: no "updated
 * daily", no counter animating up from zero. It states 24 tracks across 12 recruiters and
 * then names all twelve, which is a smaller claim and a checkable one.
 *
 * The list is rendered twice and the track is translated by exactly -50%, which is the whole
 * trick to a seamless marquee: at the end of the cycle the second copy is pixel-identical to
 * where the first started, so the loop point is invisible. It is `aria-hidden` on the second
 * copy only — a screen reader should hear the twelve companies once, not twice.
 */
function HeroMarquee() {
  const items = [...RECRUITERS];

  return (
    <div className="border-t border-[var(--mk-border)] bg-[rgb(244_239_231/0.6)] py-5 backdrop-blur-sm">
      <p className="mk-shell mb-4 text-center text-[var(--mk-micro)] text-[var(--mk-muted)]">
        <span className="mk-num font-semibold text-[var(--mk-ink)]">{TRACK_COUNT}</span>{' '}
        interview tracks across{' '}
        <span className="mk-num font-semibold text-[var(--mk-ink)]">{COMPANY_COUNT}</span>{' '}
        campus recruiters
      </p>

      {/* NOT `data-native-scroll`. That attribute tells the page's inertial wheel loop to keep
          its hands off a region because the region scrolls itself — the showcase rail, which
          is a real `overflow-x-auto` scroller. This marquee is `overflow: hidden` and moves by
          CSS animation; there is nothing here to scroll. Marking it meant the wheel was handed
          straight to the browser over a full-width band directly under the hero, so the page
          jumped natively there and eased everywhere else — two different scroll physics, in
          the first band most visitors put the pointer over. */}
      <div className="mk-marquee">
        <div className="mk-marquee-track">
          {[0, 1].map((copy) => (
            <ul
              key={copy}
              aria-hidden={copy === 1 || undefined}
              className="mk-marquee-row"
            >
              {items.map((r) => (
                <li key={`${copy}-${r.name}`} className="flex shrink-0 items-baseline gap-2">
                  <span className="text-[0.9375rem] font-medium text-[var(--mk-ink)]">
                    {r.name}
                  </span>
                  <span className="mk-num text-[var(--mk-micro)] text-[var(--mk-muted)]">
                    {r.tracks} {r.tracks === 1 ? 'track' : 'tracks'}
                  </span>
                </li>
              ))}
            </ul>
          ))}
        </div>
      </div>
    </div>
  );
}
