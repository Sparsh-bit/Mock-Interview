'use client';

import { useCallback, useRef, useState } from 'react';

import { HelpCircle, LogOut, Menu } from 'lucide-react';
import { MOBILE_NAV_ID, MobileNav } from '@/components/layout/MobileNav';
import { ADMIN_NAV_ITEMS, NAV_ITEMS, useIsAdmin } from '@/components/layout/Sidebar';
import { useAuth } from '@/hooks/useAuth';
import type { User as SupabaseUser } from '@supabase/supabase-js';
import { usePathname } from 'next/navigation';

const ROUTE_LABELS: Record<string, string> = {
  '/dashboard': 'Dashboard',
  '/interview': 'Interviews',
  '/report': 'Reports',
  '/tracks': 'Interview Tracks',
  '/analytics': 'Analytics',
  '/achievements': 'Achievements',
  '/profile': 'Profile',
  '/settings': 'Settings',
};

function getPageTitle(pathname: string): string {
  for (const [route, label] of Object.entries(ROUTE_LABELS)) {
    if (pathname.startsWith(route)) return label;
  }
  return 'InterviewOS';
}

interface HeaderProps {
  user: SupabaseUser;
}

export function AppHeader({ user }: HeaderProps) {
  const { signOut } = useAuth();
  const pathname = usePathname();
  const title = getPageTitle(pathname);
  const isAdmin = useIsAdmin();

  const [navOpen, setNavOpen] = useState(false);
  // Held so focus can return here when the drawer closes, rather than to the top of the page.
  const menuButtonRef = useRef<HTMLButtonElement | null>(null);

  /*
   * STABLE IDENTITY, and that is the entire point of the useCallback.
   *
   * MobileNav's focus effect lists `onClose` in its dependencies — it has to, since it calls
   * it from the Escape handler. Passed as an inline `() => setNavOpen(false)` this prop was a
   * new function on every render of this header, so the effect tore down and re-ran on every
   * render while the drawer was open. Its cleanup FOCUSES THE HAMBURGER and its body focuses
   * the panel, so each of those re-runs yanked focus out of the drawer and back to the top of
   * it — and this header re-renders on things the user did not do: `useIsAdmin` reads the
   * billing balance through react-query, which revalidates on window focus.
   *
   * The visible failure was a keyboard or screen-reader user tabbing down to "Reports" and
   * being silently returned to the top of the drawer mid-navigation. Same cycle also saved
   * and restored `document.body.style.overflow` on every render, which is how a scroll lock
   * ends up stuck.
   */
  const closeNav = useCallback(() => setNavOpen(false), []);

  // The SAME list the desktop rail renders — imported, not copied, because two navs drift and
  // the one that drifts is always the one you look at less. Admin appended on the same
  // condition the rail uses.
  // ADMIN_NAV_ITEMS is a flat list of links, not a group, so it is wrapped rather than
  // spread — spreading produced an array with two different shapes in it.
  const navGroups = isAdmin
    ? [...NAV_ITEMS, { group: 'Admin', items: ADMIN_NAV_ITEMS }]
    : NAV_ITEMS;

  // Opaque, and no backdrop-blur.
  //
  // Nothing scrolls behind this header — <main> begins exactly at its bottom
  // edge, measured — so the blur cost a per-frame backdrop re-sample across
  // 1200x56 and changed no pixel. The translucency was equally pointless:
  // bg-background/70 was compositing over bg-background, the same colour.
  //
  // `backdrop-blur-xl/60` was also not a real class. Tailwind's backdrop-blur
  // takes no opacity modifier, so it emitted nothing, and the `backdrop-blur-md`
  // further along the same string was what actually applied.
  return (
    <header className="flex h-14 items-center justify-between border-b border-border/60 bg-background px-4 sm:px-6">
      {/* Page title, and the only way into navigation below lg */}
      <div className="flex min-w-0 items-center gap-2">
        <button
          ref={menuButtonRef}
          type="button"
          onClick={() => setNavOpen(true)}
          aria-label="Open navigation"
          aria-expanded={navOpen}
          // Names the thing it opens. `aria-expanded` on its own says "something is expanded"
          // without saying what, so a screen reader cannot tell the user where they have just
          // been taken. The id is imported from MobileNav rather than typed here, because an
          // aria-controls pointing at an id that does not exist is worse than none at all and
          // nothing in the build would ever catch the typo.
          aria-controls={MOBILE_NAV_ID}
          // Hidden at lg and up, where the rail is visible instead. 44px square, because a
          // thumb is not a cursor.
          className="-ml-2 flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground lg:hidden"
        >
          <Menu className="h-5 w-5" />
        </button>
        <h2 className="truncate text-sm font-semibold tracking-tight">{title}</h2>
      </div>

      <MobileNav
        open={navOpen}
        onClose={closeNav}
        triggerRef={menuButtonRef}
        groups={navGroups}
      />

      {/* Right actions */}
      <div className="flex items-center gap-1">
        {/* Help — real support link */}
        <a
          href="mailto:support@interviewos.app?subject=InterviewOS%20Help"
          title="Get help"
          className="flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
        >
          <HelpCircle className="h-4 w-4" />
        </a>

        {/* Divider */}
        <div className="mx-2 h-4 w-px bg-border/70" />

        {/* Sign out */}
        <button
          onClick={signOut}
          className="flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
        >
          <LogOut className="h-3.5 w-3.5" />
          Sign out
        </button>
      </div>
    </header>
  );
}
