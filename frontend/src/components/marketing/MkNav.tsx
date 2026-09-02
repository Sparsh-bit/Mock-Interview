'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { ArrowRight, Menu, X } from 'lucide-react';

import { Brandmark } from '@/components/brand/Brandmark';
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
 *  · Over a dark stage it inverts. The film is a 360vh section of near-black; an espresso
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
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <>
      <header className="pointer-events-none fixed inset-x-0 top-0 z-50 flex justify-center px-[var(--mk-gutter)] pt-3">
        <nav
          data-dark={onDark || undefined}
          className={cn(
            'pointer-events-auto flex w-full max-w-[var(--mk-max)] items-center gap-3 rounded-[var(--mk-r-pill)] px-3 py-2.5 transition-[background,border-color,box-shadow,backdrop-filter] duration-[400ms] sm:px-4',
            scrolled
              ? 'border border-[var(--mk-border)] bg-[rgb(251_246_236/0.82)] shadow-[var(--mk-shadow-card)] backdrop-blur-xl backdrop-saturate-150'
              : 'border border-transparent bg-transparent',
            onDark &&
              'border-[rgb(255_255_255/0.1)] bg-[rgb(20_16_10/0.62)] shadow-[0_10px_40px_-20px_rgb(0_0_0/0.9)] backdrop-blur-xl',
          )}
        >
          <Link
            href="/"
            className="group flex items-center gap-2.5 rounded-[var(--mk-r-pill)] px-1.5 py-1"
            aria-label="InterviewOS — home"
          >
            <Brandmark
              className={cn(
                'h-7 w-7 shrink-0 transition-opacity duration-300',
                onDark && 'opacity-95',
              )}
            />
            <span
              className={cn(
                'font-[family-name:var(--mk-font-display)] text-[1.0625rem] font-medium tracking-[-0.015em] transition-colors duration-[400ms]',
                onDark ? 'text-[var(--mk-on-dark-bright)]' : 'text-[var(--mk-ink)]',
              )}
            >
              Interview
              {/* The gold half of the wordmark. It is the only gold above the fold that is not
                  a button, and that is on purpose: it teaches the colour before the colour is
                  asked to mean "press this". */}
              <span className="text-[var(--mk-gold)]"> OS</span>
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

          <div className="ml-auto flex items-center gap-1.5 lg:ml-0">
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
                'mk-btn h-10 px-4 text-[0.9375rem]',
                onDark ? 'mk-btn-gold' : 'mk-btn-primary',
              )}
            >
              Start free
              <ArrowRight className="mk-arrow h-[15px] w-[15px]" strokeWidth={2.2} />
            </Link>
            <button
              type="button"
              onClick={() => setOpen(true)}
              aria-label="Open menu"
              aria-expanded={open}
              className={cn(
                'ml-0.5 grid h-10 w-10 place-items-center rounded-[var(--mk-r-pill)] transition-colors lg:hidden',
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
        <div className="fixed inset-0 z-[60] flex flex-col bg-[var(--mk-paper)] lg:hidden">
          <div className="flex items-center justify-between px-[var(--mk-gutter)] pt-5">
            <span className="flex items-center gap-2.5">
              <Brandmark className="h-7 w-7" />
              <span className="font-[family-name:var(--mk-font-display)] text-[1.0625rem] font-medium text-[var(--mk-ink)]">
                Interview<span className="text-[var(--mk-gold)]"> OS</span>
              </span>
            </span>
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label="Close menu"
              className="grid h-11 w-11 place-items-center rounded-[var(--mk-r-pill)] text-[var(--mk-ink)] hover:bg-[rgb(59_43_28/0.05)]"
            >
              <X className="h-5 w-5" strokeWidth={2} />
            </button>
          </div>

          <nav className="flex flex-1 flex-col justify-center gap-1 px-[var(--mk-gutter)] pb-24">
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
