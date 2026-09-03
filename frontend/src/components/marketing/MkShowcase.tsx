'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';

import {
  CodeArtefact,
  InterviewArtefact,
  PlanArtefact,
  ReportArtefact,
} from '@/components/landing/Artefacts';
import { cn } from '@/lib/utils';

/**
 * SEE IT IN ACTION — components/marketing/MkShowcase.tsx
 *
 * A horizontal rail of product surfaces, each in its own window frame, with the same caption
 * treatment a gallery would give a plate.
 *
 * ── WHY THESE ARE LIVE COMPONENTS AND NOT SCREENSHOTS ────────────────────────────────────
 * The reference this page answers to puts four PNGs here, which is the ordinary choice, and
 * it has the ordinary costs: four images to re-shoot every time a surface changes, four
 * images that are pixels at 1x on a 3x screen, four images whose text no reader can reach,
 * and about 400KB. These four are the artefacts the previous landing page already built —
 * real DOM, real type, and they cannot fall out of date without the code falling out of date
 * with them.
 *
 * ── THE RAIL IS A NATIVE SCROLLER ────────────────────────────────────────────────────────
 * `overflow-x: auto` with `scroll-snap`, not a transform-driven carousel. That means it works
 * with a trackpad swipe, a shift-wheel, a touch drag, the keyboard, and a screen reader's own
 * navigation, all without a line of code — and the arrow buttons are a convenience on top
 * rather than the only way in. It is marked `data-native-scroll` so the page's inertial wheel
 * handler leaves it alone; without that, a wheel over the rail would scroll the page and the
 * rail would be dead to the one input most desktop visitors try first.
 */

const SHOTS = [
  {
    id: 'interview',
    caption: 'The interview, mid-cross-question',
    sub: 'A thin answer gets a follow-up, not a score.',
    Node: InterviewArtefact,
  },
  {
    id: 'report',
    caption: 'The report',
    sub: 'One score, four competencies, every topic ranked.',
    Node: ReportArtefact,
  },
  {
    id: 'code',
    caption: 'The coding round',
    sub: 'Compiled, judged on approach, and flagged if it reads as AI-written.',
    Node: CodeArtefact,
  },
  {
    id: 'plan',
    caption: 'The target-company plan',
    sub: 'Weighted by what that recruiter actually tests.',
    Node: PlanArtefact,
  },
] as const;

export function MkShowcase() {
  const railRef = useRef<HTMLDivElement | null>(null);
  const [atStart, setAtStart] = useState(true);
  const [atEnd, setAtEnd] = useState(false);

  const sync = useCallback(() => {
    const el = railRef.current;
    if (!el) return;
    /*
     * `< 8` was measured against a rail that starts at scrollLeft 0. It does not: `snap-x
     * snap-mandatory` plus `scroll-padding-inline` parks the rail on its first snap point,
     * which sits one spacer-width in. So "at the start" was never true, the Previous arrow
     * rendered enabled at the leftmost position, and clicking it did nothing.
     *
     * Comparing against the first card's own offset makes the test independent of how wide the
     * spacer happens to be at this viewport.
     */
    const first = el.querySelector('figure') as HTMLElement | null;
    setAtStart(el.scrollLeft <= (first ? first.offsetLeft - el.offsetLeft : 0) + 8);
    /* The 8px slack matters: sub-pixel layout means `scrollLeft + clientWidth` frequently
       lands a fraction short of `scrollWidth` at the true end, and without it the right arrow
       never disables on the last card. */
    setAtEnd(el.scrollLeft + el.clientWidth >= el.scrollWidth - 8);
  }, []);

  useEffect(() => {
    sync();
    const el = railRef.current;
    if (!el) return;
    el.addEventListener('scroll', sync, { passive: true });
    window.addEventListener('resize', sync);
    return () => {
      el.removeEventListener('scroll', sync);
      window.removeEventListener('resize', sync);
    };
  }, [sync]);

  const nudge = (dir: -1 | 1) => {
    const el = railRef.current;
    if (!el) return;
    /*
     * Scroll by a CARD, measured from a card — not by a hard-coded number of pixels, because
     * the cards are fluid and a fixed step lands mid-card at most viewport widths.
     *
     * THIS READ `firstElementChild`, WHICH IS THE LEADING SPACER, NOT A CARD. The spacer is
     * ~188px at 1440 and a card is 560, so the step came out at 212px against a 584px gap
     * between snap points — and because the rail is `snap-mandatory`, the browser then snapped
     * back to the card it started on. The Next button could not leave the first card at all,
     * however many times you pressed it.
     */
    const card = el.querySelector('figure');
    const step = card ? card.getBoundingClientRect().width + 24 : el.clientWidth * 0.8;
    el.scrollBy({ left: dir * step, behavior: 'smooth' });
  };

  return (
    <section className="mk-section overflow-hidden">
      <div className="mk-shell">
        <div className="flex flex-wrap items-end justify-between gap-6">
          <div>
            <p className="mk-eyebrow">See it in action</p>
            <h2 className="mt-5 max-w-[16ch] text-balance leading-[1.06]" style={{ fontSize: 'var(--mk-h2)' }}>
              The screens you&rsquo;ll actually be looking at.
            </h2>
          </div>

          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => nudge(-1)}
              disabled={atStart}
              aria-label="Previous"
              className="mk-shotnav"
            >
              <ChevronLeft className="h-[18px] w-[18px]" strokeWidth={2} />
            </button>
            <button
              type="button"
              onClick={() => nudge(1)}
              disabled={atEnd}
              aria-label="Next"
              className="mk-shotnav"
            >
              <ChevronRight className="h-[18px] w-[18px]" strokeWidth={2} />
            </button>
          </div>
        </div>
      </div>

      {/* The rail bleeds past the shell on both sides so a card is always half-visible at the
          right edge. A rail that ends flush with the text column reads as a finished row of
          four; one that runs off the page reads as a rail, and people scroll rails. */}
      <div
        ref={railRef}
        data-native-scroll
        className="mk-rail mt-10 flex snap-x snap-mandatory gap-6 overflow-x-auto pb-4"
      >
        {/* Leading and trailing spacers keep the first card aligned to the text column and let
            the last one scroll fully clear of the edge. Padding on the scroller itself does
            not do this — the trailing padding is ignored by every engine's scroll extent. */}
        <span aria-hidden className="mk-rail-pad shrink-0" />
        {SHOTS.map(({ id, caption, sub, Node }) => (
          <figure
            key={id}
            className={cn(
              'mk-card w-[min(560px,82vw)] shrink-0 snap-start overflow-hidden p-5',
            )}
          >
            <div className="min-h-[240px]">
              <Node />
            </div>
            <figcaption className="mt-5 border-t border-[var(--mk-border)] pt-4">
              <span className="block text-[0.9375rem] font-medium text-[var(--mk-ink)]">
                {caption}
              </span>
              <span className="mt-1 block text-[var(--mk-micro)] text-[var(--mk-muted)]">
                {sub}
              </span>
            </figcaption>
          </figure>
        ))}
        <span aria-hidden className="mk-rail-pad shrink-0" />
      </div>
    </section>
  );
}
