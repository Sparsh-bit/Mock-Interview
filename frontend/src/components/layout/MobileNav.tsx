'use client';

import { AnimatePresence, motion } from 'framer-motion';
import { X } from 'lucide-react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useRef } from 'react';

import { Wordmark } from '@/components/brand/Brandmark';
import { BRAND } from '@/lib/brand';
import { ROUTE_TONE, TONES } from '@/lib/tones';
import { cn } from '@/lib/utils';

/**
 * The navigation drawer for phones — components/layout/MobileNav.tsx
 *
 * WHY THIS EXISTS. The sidebar was always rendered, animating between 72px and 240px with no
 * breakpoint at all. On a 375px phone that left roughly 135px for the actual page — so the
 * dashboard was not "a bit cramped" on mobile, it was unusable. For a product whose users are
 * final-year students in India, who are overwhelmingly phone-first, that outranked every
 * cosmetic question in the app.
 *
 * The rail is now `hidden lg:flex` and this takes over below that.
 *
 * IT IS A REAL MODAL, not a panel that slides in. That distinction is the difference between
 * a drawer that works and one that merely appears:
 *
 *   * ESCAPE CLOSES IT. Expected of anything modal, and the only way out for a keyboard user
 *     if the close button scrolls off.
 *   * FOCUS MOVES INTO IT on open and RETURNS to the trigger on close. Without that, a
 *     keyboard or screen-reader user opens the drawer and their focus is still behind it,
 *     tabbing through a page they cannot see.
 *   * FOCUS IS TRAPPED while open, so Tab cannot walk out of the drawer into the page beneath.
 *   * THE BODY DOES NOT SCROLL behind it. Scroll chaining is the single most common bug in a
 *     hand-rolled drawer: you swipe the nav, the page behind moves instead, and closing leaves
 *     you somewhere else entirely.
 *   * IT CLOSES ON NAVIGATION. Obvious in hindsight, invisible until you tap a link and the
 *     drawer stays open over the page you just asked for.
 */
/**
 * The drawer's DOM id, so the hamburger's `aria-controls` can name it.
 *
 * Exported rather than written out at both ends: an `aria-controls` whose value does not match
 * a real id is a promise to assistive technology that nothing in the build would ever check.
 */
export const MOBILE_NAV_ID = 'mobile-nav';

export interface MobileNavItem {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}

export interface MobileNavGroup {
  group: string;
  items: MobileNavItem[];
}

export interface MobileNavProps {
  open: boolean;
  onClose: () => void;
  groups: MobileNavGroup[];
  /** Element that opened the drawer, so focus can go back where it came from. */
  triggerRef?: React.RefObject<HTMLElement | null>;
}

export function MobileNav({ open, onClose, groups, triggerRef }: MobileNavProps) {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const pathname = usePathname();

  // Close on navigation. Without this, tapping a link leaves the drawer sitting over the page
  // it just loaded.
  useEffect(() => {
    if (open) onClose();
    // Only pathname — including `open` would close it the instant it opened.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

  // Escape, focus management and the focus trap.
  useEffect(() => {
    if (!open) return;

    const previouslyFocused = document.activeElement as HTMLElement | null;
    // Captured NOW, not read in cleanup. By the time cleanup runs the ref may point
    // somewhere else — and focus would be restored to the wrong element, or nothing.
    const trigger = triggerRef?.current ?? null;
    // Focus the panel itself rather than the first link: a screen reader then announces the
    // dialog and its label before reading the list, instead of dropping the user onto
    // "Dashboard" with no context.
    panelRef.current?.focus();

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key !== 'Tab') return;

      const focusables = panelRef.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled])',
      );
      if (!focusables?.length) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];

      // Wrap at both ends, so Tab cannot walk out of the drawer into the page beneath it.
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', onKeyDown);
    // Stop the page behind scrolling. Restored to whatever it was rather than hardcoded to
    // '', so a page that sets its own overflow is not quietly reset by closing the nav.
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = previousOverflow;
      // Back to the hamburger, not to the top of the page.
      (trigger ?? previouslyFocused)?.focus?.();
    };
  }, [open, onClose, triggerRef]);

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <motion.button
            type="button"
            aria-label="Close navigation"
            onClick={onClose}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
            className="absolute inset-0 h-full w-full bg-foreground/25 backdrop-blur-[2px]"
          />

          <motion.div
            ref={panelRef}
            id={MOBILE_NAV_ID}
            role="dialog"
            aria-modal="true"
            aria-label="Main navigation"
            tabIndex={-1}
            initial={{ x: '-100%' }}
            animate={{ x: 0 }}
            exit={{ x: '-100%' }}
            // Slightly slower out than in: a drawer that snaps shut reads as a glitch, while
            // one that leaves reads as dismissal.
            transition={{ type: 'spring', stiffness: 400, damping: 40 }}
            className={cn(
              'absolute inset-y-0 left-0 flex w-[min(82vw,300px)] flex-col',
              'border-r border-border/70 bg-surface shadow-2xl outline-none',
            )}
          >
            <div className="flex h-14 flex-shrink-0 items-center justify-between border-b border-border/60 px-4">
              <Link href="/dashboard" aria-label={`${BRAND.name} home`} className="min-w-0">
                <Wordmark />
              </Link>
              <button
                type="button"
                onClick={onClose}
                aria-label="Close navigation"
                className="flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <nav className="flex-1 overflow-y-auto px-3 py-3">
              {groups.map((group) => (
                <div key={group.group} className="mb-5">
                  <p className="mb-1.5 px-3 font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground/70">
                    {group.group}
                  </p>
                  {group.items.map((item) => {
                    const Icon = item.icon;
                    const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
                    /*
                     * THE TONE IS LOOKED UP BY HREF rather than added to `MobileNavItem`.
                     *
                     * A new field on the type would have to be set here, in the rail's own
                     * item list, and by every future caller — three places to keep in
                     * agreement, which is three places to disagree. Keyed on the route, the
                     * drawer and the rail cannot drift apart because they are reading the
                     * same table. `tones.test.ts` pins that table against the rail's source.
                     *
                     * Undefined for Profile and Settings, which are deliberately uncoloured,
                     * and those fall back to the neutral treatment.
                     */
                    const t = ROUTE_TONE[item.href] ? TONES[ROUTE_TONE[item.href]] : null;
                    return (
                      <Link
                        key={item.href}
                        href={item.href}
                        aria-current={active ? 'page' : undefined}
                        className={cn(
                          // min-h-11 is the ~44px touch target both platform guidelines ask
                          // for. The desktop rail's rows are smaller because a cursor is
                          // precise and a thumb is not.
                          'flex min-h-11 items-center gap-3 rounded-lg px-3 text-sm transition-colors',
                          active
                            ? cn('font-medium', t ? `${t.activeBg} ${t.activeText}` : 'bg-primary/10 text-primary')
                            : 'text-muted-foreground hover:bg-secondary hover:text-foreground',
                        )}
                      >
                        {/* Coloured whether or not the row is active, exactly as in the
                            desktop rail. A column of identical grey icons teaches nothing
                            about where things are; coloured, the list becomes a map you can
                            read without reading the words — which matters more here, since
                            this drawer is the ONLY navigation below lg. */}
                        <Icon
                          className={cn(
                            'h-4 w-4 flex-shrink-0',
                            t ? t.icon : 'text-muted-foreground',
                            !active && 'opacity-70',
                          )}
                        />
                        <span className="truncate">{item.label}</span>
                      </Link>
                    );
                  })}
                </div>
              ))}
            </nav>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}

export default MobileNav;
