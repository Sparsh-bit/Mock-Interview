'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { ArrowRight, Menu, X } from 'lucide-react';

import { Brandmark, TwoToneName } from '@/components/brand/Brandmark';
import { BRAND } from '@/lib/brand';
import { cn } from '@/lib/utils';

import { NAV_LINKS } from './content';

/**
 * THE FLOATING NAV — components/marketing/MkNav.tsx
 *
 * A pill that floats clear of the page rather than a bar welded to the top of it. The
 * difference is not decoration: a full-width bar draws a horizontal line across the viewport
 * and that line competes with the hero for the first thing your eye lands on. A pill with
 * paper visible on all four sides has no edge to follow, so the headline wins, which is the
 * one job the top of a landing page has.
 *
 * ── THE THREE STATES ─────────────────────────────────────────────────────────────────────
 *  · At rest, over the hero, it is transparent — no fill, no border, no shadow. The hero's
 *    line-art runs underneath it uninterrupted.
 *  · Once the page has moved past ~24px it takes a translucent paper fill, a hairline and a
 *    soft shadow, because from that point on there is content sliding under it and text
 *    passing through text is the one thing a floating nav must not allow.
 *  · Over a dark stage it inverts. The film is a 540vh section of near-black; an espresso
 *    wordmark on it is invisible, and a cream pill sitting on it is a hole punched through
 *    the film at its most dramatic moment. So the pill goes glass-on-dark and the type goes
 *    cream, and the transition between the two is slow enough (0.4s) to read as the nav
 *    responding to the page rather than as a flicker.
 *
 * ── HOW "OVER A DARK STAGE" IS DECIDED ───────────────────────────────────────────────────
 * Every dark section marks itself `data-nav-dark`. On scroll this measures their rects and
 * asks whether one of them covers the horizontal line the nav sits on. That is a geometric
 * question with a geometric answer, and it keeps the knowledge in the section that is
 * actually dark — add a second dark band later and the nav handles it with no edit here.
 *
 * `IntersectionObserver` is the reflex answer and is the wrong tool: it reports whether two
 * boxes overlap at all, not whether one covers a specific 1px line, so a dark section would
 * flip the nav the moment its top edge entered the viewport 900px below the pill.
 */

/* The y-coordinate the nav occupies — its top offset plus half its height. Measured once as a
   constant rather than read from the DOM because reading it means a layout flush inside a
   scroll handler, which is the classic way to turn a cheap listener into jank. */
const NAV_MIDLINE = 44;
const SCROLLED_AT = 24;

export function MkNav() {
  const [scrolled, setScrolled] = useState(false);
  const [onDark, setOnDark] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let frame = 0;

    const measure = () => {
      frame = 0;
      setScrolled(window.scrollY > SCROLLED_AT);

      const stages = document.querySelectorAll<HTMLElement>('[data-nav-dark]');
      let dark = false;
      for (const stage of stages) {
        const r = stage.getBoundingClientRect();
        if (r.top <= NAV_MIDLINE && r.bottom >= NAV_MIDLINE) {
          dark = true;
          break;
        }
      }
      setOnDark(dark);
    };

    const onScroll = () => {
      if (frame) return;
      frame = requestAnimationFrame(measure);
    };

    measure();
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll);
    return () => {
      if (frame) cancelAnimationFrame(frame);
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onScroll);
    };
  }, []);

  /* The mobile sheet is the one thing on this page that can trap a page-length of scroll
     behind it. Locking the body while it is open is not polish — without it the sheet stays
     put and the page scrolls underneath, and closing it drops you somewhere you never chose
     to be. */
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    /*
     * The attribute is not decoration — `useSmoothScroll` reads it and stands down.
     *
     * Without it the wheel handler kept swallowing events and advancing its internal target
     * while the body was locked, so no scroll ever happened and `onScroll` never fired to
     * re-sync. The loop retired at a position the page had never been at, and the next wheel
     * notch after closing the menu teleported there. An attribute is the cheap signal: the
     * alternative is `getComputedStyle(document.body)` on every wheel event, which is a layout
     * read in the hottest handler on the page.
     */
    document.body.dataset.scrollLocked = 'true';
    return () => {
      document.body.style.overflow = prev;
      delete document.body.dataset.scrollLocked;
    };
  }, [open]);

  /*
   * THE SHEET IS A MODAL DIALOG AND HAS TO BEHAVE LIKE ONE.
   *
   * It covers the viewport over a locked body, and it had none of the three things that makes
   * that survivable for a keyboard user: focus was never moved into it, so Tab walked the
   * page UNDERNEATH the cover with the focus ring invisible off-screen; Tab was never trapped,
   * so there was no way to know you had left; and focus was never restored, so closing it
   * dropped you at the top of the document rather than back on the button you opened it with.
   *
   * Escape already closed it, which is the one part that worked.
   */
  const panelRef = useRef<HTMLDivElement | null>(null);
  const openerRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!open) return;

    const panel = panelRef.current;
    /* Captured at setup, not read at teardown. The hamburger is mounted for the whole time the
       sheet is open so the two are the same element either way — but reading a ref inside a
       cleanup is the pattern that breaks the moment the element ISN'T stable, and the lint
       rule is right to insist. */
    const opener = openerRef.current;
    /* The close button is the right landing point: it is the first control in the sheet and
       the one a visitor most likely wants if they opened the menu by accident. */
    panel?.querySelector<HTMLElement>('[data-close]')?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false);
        return;
      }
      if (e.key !== 'Tab' || !panel) return;

      /* Queried on each Tab rather than cached: the sheet's contents are static today, but a
         cached list is how a focus trap silently stops covering a control somebody adds later. */
      const focusable = panel.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])',
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;

      if (e.shiftKey && (active === first || !panel.contains(active))) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && (active === last || !panel.contains(active))) {
        e.preventDefault();
        first.focus();
      }
    };

    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
      /* Back to the control that opened it. Without this, closing the sheet resets focus to
         <body> and the next Tab starts from the top of the document. */
      opener?.focus();
    };
  }, [open]);

  return (
    <>
      <header className="pointer-events-none fixed inset-x-0 top-0 z-50 flex justify-center px-[var(--mk-gutter)] pt-3">
        <nav
          data-dark={onDark || undefined}
          className={cn(
            /* `gap-2 px-2` below `sm`. At 320px the pill's contents — mark, wordmark, CTA,
               hamburger — came to about 20px more than the viewport, and because the header is
               `fixed` the page itself gained a horizontal scrollbar. Measured at 320/360/390;
               the whole cluster now fits at 320 with room to spare. */
            'pointer-events-auto flex w-full max-w-[var(--mk-max)] items-center gap-2 rounded-[var(--mk-r-pill)] px-2 py-2.5 transition-[background,border-color,box-shadow,backdrop-filter] [transition-duration:400ms] sm:gap-3 sm:px-4',
            scrolled
              ? 'border border-[var(--mk-border)] bg-[rgb(251_246_236/0.82)] shadow-[var(--mk-shadow-card)] backdrop-blur-xl backdrop-saturate-150'
              : 'border border-transparent bg-transparent',
            onDark &&
              'border-[rgb(255_255_255/0.1)] bg-[rgb(20_16_10/0.62)] shadow-[0_10px_40px_-20px_rgb(0_0_0/0.9)] backdrop-blur-xl',
          )}
        >
          <Link
            href="/"
            className="group flex items-center gap-2 rounded-[var(--mk-r-pill)] px-1 py-1 sm:gap-2.5 sm:px-1.5"
            aria-label={`${BRAND.name} - home`}
          >
            <Brandmark
              className={cn(
                'h-6 w-6 shrink-0 transition-opacity duration-300 sm:h-7 sm:w-7',
                onDark && 'opacity-95',
              )}
            />
            {/* HIDDEN BELOW 360px, WHERE IT IS THE 20px THAT DOES NOT FIT.
                At 320 the pill's contents came to 340 and, because the header is `fixed`, the
                whole page gained a horizontal scrollbar. The wordmark is ~85px of that and the
                brandmark beside it still identifies the product, so it is the right thing to
                drop. 360 is the threshold rather than 400 because every current phone - iPhone
                12 to 16 at 390, Pixel at 393 - sits above it and keeps the full lockup; only
                the 320px class loses it.

                THE WHOLE WORDMARK GOES, NOT ITS FIRST HALF. `hidden` used to sit on the
                "Interview" span alone, so a 320px phone did not lose the wordmark - it kept
                the gold "OS" and lost the product's name, which is worse than showing no name
                at all. The mark identifies the product on its own; a stray "OS" identifies
                nothing. */}
            <span
              className={cn(
                /* `whitespace-nowrap` is load-bearing at 390px: without it the pill's flex
                   layout breaks the wordmark after "Interview" and the mark sits beside a
                   two-line lockup, which is the one place on the site the brand looks
                   accidental. */
                'hidden whitespace-nowrap font-[family-name:var(--mk-font-display)] text-[0.9375rem] font-medium tracking-[-0.015em] transition-colors [transition-duration:400ms] min-[360px]:inline sm:text-[1.0625rem]',
                onDark ? 'text-[var(--mk-on-dark-bright)]' : 'text-[var(--mk-ink)]',
              )}
            >
              {/* The gold second half is the only gold above the fold that is not a button,
                  and that is on purpose: it teaches the colour before the colour is asked to
                  mean "press this". Shared with the drawer, the footer and the welcome wizard
                  so the four cannot spell the brand differently, which they did. */}
              <TwoToneName />
            </span>
          </Link>

          <div className="hidden flex-1 items-center justify-center gap-1 lg:flex">
            {NAV_LINKS.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className={cn(
                  'rounded-[var(--mk-r-pill)] px-3.5 py-2 text-[0.875rem] transition-colors duration-200',
                  onDark
                    ? 'text-[var(--mk-on-dark-muted)] hover:bg-white/5 hover:text-[var(--mk-on-dark-bright)]'
                    : 'text-[var(--mk-body)] hover:bg-[rgb(59_43_28/0.05)] hover:text-[var(--mk-ink)]',
                )}
              >
                {link.label}
              </Link>
            ))}
          </div>

          <div className="ml-auto flex min-w-0 items-center gap-1 sm:gap-1.5 lg:ml-0">
            <Link
              href="/login"
              className={cn(
                'hidden rounded-[var(--mk-r-pill)] px-3.5 py-2 text-[0.875rem] transition-colors duration-200 sm:block',
                onDark
                  ? 'text-[var(--mk-on-dark-muted)] hover:text-[var(--mk-on-dark-bright)]'
                  : 'text-[var(--mk-body)] hover:text-[var(--mk-ink)]',
              )}
            >
              Log in
            </Link>
            <Link
              href="/register"
              className={cn(
                'mk-btn h-9 px-3 text-[0.875rem] sm:h-10 sm:px-4 sm:text-[0.9375rem]',
                onDark ? 'mk-btn-gold' : 'mk-btn-primary',
              )}
            >
              Start free
              <ArrowRight className="mk-arrow h-[15px] w-[15px]" strokeWidth={2.2} />
            </Link>
            <button
              ref={openerRef}
              type="button"
              onClick={() => setOpen(true)}
              aria-label="Open menu"
              aria-expanded={open}
              className={cn(
                /* `shrink-0`: without it flex solved an over-wide row by squashing the
                     hamburger to half size rather than by overflowing, so the symptom was a
                     visibly deformed 18px button next to a page that scrolled sideways. */
                'grid h-9 w-9 shrink-0 place-items-center rounded-[var(--mk-r-pill)] transition-colors sm:ml-0.5 sm:h-10 sm:w-10 lg:hidden',
                onDark
                  ? 'text-[var(--mk-on-dark)] hover:bg-white/5'
                  : 'text-[var(--mk-ink)] hover:bg-[rgb(59_43_28/0.05)]',
              )}
            >
              <Menu className="h-[18px] w-[18px]" strokeWidth={2} />
            </button>
          </div>
        </nav>
      </header>

      {/* THE MOBILE SHEET. A full cover rather than a dropdown, because a dropdown over a
          page with a dark film behind it inherits whatever is underneath and half the links
          become unreadable at some scroll positions. A cover has one background by
          definition. */}
      {open && (
        <div
          ref={panelRef}
          role="dialog"
          aria-modal="true"
          aria-label="Menu"
          className="fixed inset-0 z-[60] flex flex-col bg-[var(--mk-paper)] lg:hidden"
        >
          <div className="flex items-center justify-between px-[var(--mk-gutter)] pt-5">
            <span className="flex items-center gap-2.5">
              <Brandmark className="h-7 w-7" />
              {/* Same two halves as the header pill, from the same source. This copy had the
                  identical leading-space bug, so the drawer and the header agreed with each
                  other and disagreed with the rest of the product. */}
              <span className="font-[family-name:var(--mk-font-display)] text-[1.0625rem] font-medium text-[var(--mk-ink)]">
                <TwoToneName />
              </span>
            </span>
            <button
              type="button"
              data-close
              onClick={() => setOpen(false)}
              aria-label="Close menu"
              className="grid h-11 w-11 place-items-center rounded-[var(--mk-r-pill)] text-[var(--mk-ink)] hover:bg-[rgb(59_43_28/0.05)]"
            >
              <X className="h-5 w-5" strokeWidth={2} />
            </button>
          </div>

          {/* THE SHEET HAS TO SCROLL, AND IT DID NOT.
              This is `fixed inset-0` and the effect above locks `body`, so this <nav> is the
              only thing on screen that can scroll — and it had no `overflow-y-auto`, which
              meant nothing could. The content is about 650px tall (five 78px rows, the CTA and
              its `pb-24`), so every phone in landscape — 390px on an iPhone 14 — and any short
              or zoomed desktop window clipped it. `justify-center` made that worse rather than
              better: overflow was split across BOTH ends, so the first link and the "Start
              free" button went out of reach together, and the primary conversion action on the
              site was the thing you could not tap.

              `safe center` is the fix rather than dropping the centring: it centres while the
              content fits and falls back to flex-start the moment it does not, so nothing is
              ever pushed past the top edge. An engine that does not know `safe` drops the
              declaration and lands on `normal`, which is flex-start — the safe direction.

              `data-native-scroll` because this is now a real scroller, and the page's inertial
              wheel loop must let it have the wheel. `components/layout/MobileNav.tsx` is the
              signed-in equivalent and has always been `flex-1 overflow-y-auto`; this is the
              same shape, and it is the public copy that drifted. */}
          <nav
            data-native-scroll
            className="flex flex-1 flex-col [justify-content:safe_center] gap-1 overflow-y-auto px-[var(--mk-gutter)] pb-24"
          >
            {NAV_LINKS.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                onClick={() => setOpen(false)}
                className="border-b border-[var(--mk-border)] py-5 font-[family-name:var(--mk-font-display)] text-[1.75rem] text-[var(--mk-ink)]"
              >
                {link.label}
              </Link>
            ))}
            <Link
              href="/login"
              onClick={() => setOpen(false)}
              className="border-b border-[var(--mk-border)] py-5 font-[family-name:var(--mk-font-display)] text-[1.75rem] text-[var(--mk-ink)]"
            >
              Log in
            </Link>
            <Link
              href="/register"
              onClick={() => setOpen(false)}
              className="mk-btn mk-btn-primary mt-8 w-full"
            >
              Start free
              <ArrowRight className="mk-arrow h-4 w-4" strokeWidth={2.2} />
            </Link>
          </nav>
        </div>
      )}
    </>
  );
}
