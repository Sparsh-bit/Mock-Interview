'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { motion } from 'framer-motion';
import { BarChart3, BookOpen, ChevronLeft, Coins, FileText, LayoutDashboard, ListChecks, Loader2, MessageSquare, Play, Settings, ShieldCheck, Sparkles, Tag, Target, TrendingUp, Trophy, User, Users } from 'lucide-react';

import { useBalance } from '@/hooks/useBilling';
import { cn } from '@/lib/utils';
import { useEffect, useState } from 'react';
import type { User as SupabaseUser } from '@supabase/supabase-js';

/**
 * The navigation. Exported so the mobile drawer renders the SAME list — two copies of a nav
 * is two navs that drift, and the one that drifts is always the one you look at less.
 */
export const NAV_ITEMS = [
  {
    group: 'Main',
    items: [
      { href: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
      { href: '/prepare', icon: Target, label: 'Target Company' },
      { href: '/interview', icon: Play, label: 'Start Interview' },
      { href: '/quiz', icon: ListChecks, label: 'Practice Quiz' },
      { href: '/communication', icon: MessageSquare, label: 'Communication' },
      { href: '/gd', icon: Users, label: 'Group Discussion' },
      { href: '/report', icon: FileText, label: 'Reports' },
    ],
  },
  {
    group: 'Practice',
    items: [
      { href: '/tracks', icon: BookOpen, label: 'Interview Tracks' },
      { href: '/analytics', icon: BarChart3, label: 'Analytics' },
      { href: '/achievements', icon: Trophy, label: 'Standing' },
    ],
  },
  {
    group: 'Account',
    items: [
      { href: '/profile', icon: User, label: 'Profile' },
      { href: '/pricing', icon: Sparkles, label: 'Plans' },
      { href: '/settings', icon: Settings, label: 'Settings' },
    ],
  },
];

// Admin-only. `Users` is permanent; `AI cost` goes when the temporary ledger
// does — see docs/TEMPORARY-token-counter.md.
export const ADMIN_NAV_ITEMS = [
  { href: '/admin', icon: ShieldCheck, label: 'Users' },
  { href: '/admin/offers', icon: Tag, label: 'Offers' },
  // Revenue, vector-cache storage, and cost avoided. Distinct from `AI cost` above, which
  // answers "what did we spend and on what"; this answers "what came in, and is the spend
  // falling per user as we grow". They read the same ledger and are not the same question.
  { href: '/admin/analytics', icon: TrendingUp, label: 'Analytics' },
  { href: '/ai-usage', icon: Coins, label: 'AI cost' },
];

interface SidebarProps {
  user: SupabaseUser;
}

/**
 * Is this an admin account?
 *
 * Answered by probing an admin-gated endpoint rather than by adding an `is_admin`
 * field to a user response. The probe IS the authorisation check, so there is no
 * second source of truth that could disagree with the server — and no extra API
 * surface to remove when the temporary cost view goes.
 *
 * `/admin/overview` is the cheapest admin read, and `retry: false` means a 403 costs
 * exactly one request. A non-admin never sees the links.
 *
 * IT USED TO BE `staleTime: Infinity, gcTime: Infinity`, AND THAT WAS THE BUG. The answer
 * was cached for the whole session and never revalidated, so an admin whose access was
 * revoked kept the Users and AI cost links in their sidebar until they hard-reloaded — the
 * audit log showed exactly that happening, and the demoted account was still being shown
 * admin navigation.
 *
 * Not a privilege escalation: every admin route is independently gated by the `AdminUser`
 * dependency server-side, so clicking one of those stale links returns 403 and the page
 * shows nothing. But an interface that offers an action the server will refuse is lying
 * about who you are, and for an access control that is not a small lie.
 *
 * So the answer now expires. Five minutes, plus a re-check whenever the tab regains focus
 * or the shell remounts — revocation lands within a few minutes without a reload, and the
 * cost is one cheap request per five minutes for the handful of accounts that are admins.
 */
export function useIsAdmin(): boolean {
  /*
   * READ FROM THE BALANCE, WHICH THIS PAGE ALREADY FETCHES.
   *
   * This used to answer "am I an admin" by calling /admin/overview and watching for a 403.
   * That works, and it costs three refused requests and three warning log lines on every
   * page load for every ordinary user — a 403 there is the correct response and a completely
   * normal state, so it made a healthy system look like it was being probed.
   *
   * `/billing/me` is loaded on every dashboard page anyway, so this is now free.
   *
   * FAILS CLOSED, and that is unchanged: `data` is undefined while loading and on any error,
   * and only an explicit `true` counts. It also changes nothing about ACCESS — every admin
   * endpoint is gated by the `AdminUser` dependency server-side and returns 403 whatever the
   * navigation shows. This decides what is rendered, not what is permitted.
   *
   * The per-user cache key is gone with the probe: the balance query is cleared on every
   * identity change by Providers, along with everything else.
   */
  const { data } = useBalance();
  return data?.is_admin === true;
}


export function AppSidebar({ user }: SidebarProps) {
  const [collapsed, setCollapsed] = useState(false);
  const isAdmin = useIsAdmin();
  const pathname = usePathname();

  /*
   * WHICH ITEM THE USER JUST CLICKED, so the click has a visible consequence immediately.
   *
   * THE REPORT: "the sidebar options does not respond". They did respond — there was simply
   * nothing to see. Every page in this group is server-rendered on demand, so a click starts
   * a network fetch for that segment, and until it lands: the old page is still fully drawn,
   * and the active pill below is driven by `pathname`, which does not change until the
   * navigation COMMITS. So for the whole duration of the slowest part of the interaction the
   * rail looks exactly as it did before the click. On a cold backend that is seconds of an
   * app that appears dead, and the natural response is to click again.
   *
   * `loading.tsx` in this route group fixes the page area. This fixes the rail, which is
   * where the user is actually looking when they click it.
   *
   * WHY NOT `useLinkStatus`. That is the framework's own answer to exactly this and it is
   * not in Next 15.3.3 — checked, `next/link` does not export it. When this project moves to
   * a version that has it, this state and its two effects should be deleted in favour of it:
   * it is per-link and needs no bookkeeping, where this has to know when to stop.
   *
   * CLEARED ON THE PATHNAME CHANGING, which is the definition of "the navigation finished".
   */
  const [pendingHref, setPendingHref] = useState<string | null>(null);

  useEffect(() => {
    setPendingHref(null);
  }, [pathname]);

  /*
   * AND CLEARED ON A TIMER, because "the navigation finished" is not the only way it can end.
   *
   * A failed segment fetch, an aborted navigation, a redirect back to the same URL — none of
   * those change the pathname, so without this the spinner would turn forever on an item the
   * user is no longer waiting for. A permanent spinner is a worse lie than no spinner: it
   * says the app is still working on something it has given up on.
   *
   * Eight seconds is past any navigation that is going to succeed, including a cold start,
   * and short enough that a stuck one stops claiming to be in progress.
   */
  useEffect(() => {
    if (!pendingHref) return;
    const timer = setTimeout(() => setPendingHref(null), 8000);
    return () => clearTimeout(timer);
  }, [pendingHref]);

  return (
    <motion.aside
      animate={{ width: collapsed ? 72 : 240 }}
      transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
      // `bg-surface` is the warm recessed fill, so the rail reads as part of the
      // same sheet of paper as the page. At 70% over a white body it came out
      // cooler than the content beside it.
      //
      // NO backdrop-blur. It was here, and it was doing nothing at all: the
      // sidebar sits BESIDE <main>, never over it — measured, aside.right is
      // exactly main.left — so no content ever passes behind it, and the
      // background is opaque anyway so the backdrop is never visible. What it
      // did do was force the compositor to re-sample and re-blur a 240x950
      // region every frame the page scrolled.
      // `hidden lg:flex` — the rail is desktop-only. It used to render at every width,
      // taking 240px of a 375px phone and leaving the page about 135px. Below lg the
      // drawer in MobileNav.tsx takes over.
      className="relative hidden flex-shrink-0 flex-col border-r border-border/70 bg-surface lg:flex"
    >
      {/* Logo */}
      <div className={cn('flex h-14 items-center px-3', collapsed && 'justify-center')}>
        <Link href="/dashboard" className="flex min-w-0 items-center gap-2.5">
          <span className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-md bg-foreground font-mono text-[11px] font-bold text-background">
            IO
          </span>
          {!collapsed && (
            <span className="truncate font-mono text-[13px] font-semibold tracking-tight">InterviewOS</span>
          )}
        </Link>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-3 py-3">
        {NAV_ITEMS.map(({ group, items: baseItems }) => (
          <div key={group} className="mb-5">
            {!collapsed && (
              <p className="mb-1.5 px-2.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground/60">
                {group}
              </p>
            )}
            <ul className="space-y-0.5">
              {/* Admin entries hang off Account, and only for accounts the
                  server actually answers admin reads for. */}
              {(group === 'Account' && isAdmin
                ? [...baseItems, ...ADMIN_NAV_ITEMS]
                : baseItems
              ).map(({ href, icon: Icon, label }) => {
                const isActive = pathname === href || pathname.startsWith(href + '/');
                return (
                  <li key={href} className="relative">
                    <Link
                      href={href}
                      title={collapsed ? label : undefined}
                      // Not set when the item is already active: that click starts no
                      // navigation, so the pathname never changes, so nothing would ever
                      // clear it except the timeout above — eight seconds of a spinner for
                      // a page the user is already on.
                      onClick={() => {
                        if (!isActive) setPendingHref(href);
                      }}
                      className={cn(
                        // 30px rows on an 8pt rhythm, rounded-md (10px) because
                        // they sit inside a 12px-padded rail — the nesting rule.
                        'relative z-10 flex items-center gap-2.5 rounded-md px-2.5 py-[7px] text-[13px] transition-colors',
                        collapsed && 'justify-center px-2',
                        isActive
                          ? 'font-medium text-foreground'
                          : 'text-muted-foreground hover:text-foreground'
                      )}
                    >
                      {/* The icon becomes a spinner in place. Same box, so nothing in the
                          rail moves — a layout shift in a nav the user is mid-click on is
                          how a click lands on the wrong row. */}
                      {pendingHref === href ? (
                        <Loader2
                          className="h-[15px] w-[15px] flex-shrink-0 animate-spin"
                          strokeWidth={1.9}
                        />
                      ) : (
                        <Icon className="h-[15px] w-[15px] flex-shrink-0" strokeWidth={1.9} />
                      )}
                      {!collapsed && <span className="truncate">{label}</span>}
                    </Link>
                    {isActive && (
                      <motion.div
                        layoutId="sidebar-active-pill"
                        className="absolute inset-0 rounded-md bg-foreground/[0.07]"
                        transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
                      />
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      {/* User info at bottom */}
      <div className={cn('border-t border-border/70 p-3', collapsed && 'flex justify-center')}>
        <Link
          href="/profile"
          className={cn('flex items-center gap-3 rounded-lg p-2 transition-colors hover:bg-secondary', collapsed && 'justify-center')}
        >
          <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-primary/15 text-xs font-bold text-primary">
            {user.email?.[0]?.toUpperCase() || 'U'}
          </div>
          {!collapsed && (
            <div className="min-w-0">
              <p className="truncate text-xs font-medium">{user.email}</p>
              <p className="text-[10px] text-muted-foreground">View profile</p>
            </div>
          )}
        </Link>
      </div>

      {/* Collapse toggle */}
      <button
        onClick={() => setCollapsed((v) => !v)}
        className="absolute -right-3 top-20 z-10 flex h-6 w-6 items-center justify-center rounded-full border border-border bg-surface text-muted-foreground shadow-sm transition-colors hover:text-foreground"
      >
        <ChevronLeft
          className={cn('h-3 w-3 transition-transform duration-300', collapsed && 'rotate-180')}
        />
      </button>
    </motion.aside>
  );
}
