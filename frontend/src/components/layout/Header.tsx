'use client';

import { Bell, HelpCircle, LogOut, Search } from 'lucide-react';
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

  return (
    <header className="flex h-16 items-center justify-between border-b border-border bg-surface/50 px-6 backdrop-blur-sm">
      {/* Page title */}
      <div>
        <h2 className="text-sm font-semibold">{title}</h2>
      </div>

      {/* Right actions */}
      <div className="flex items-center gap-2">
        {/* Search — placeholder for Phase 9 */}
        <button
          disabled
          title="Coming soon"
          className="flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground cursor-not-allowed opacity-50"
        >
          <Search className="h-4 w-4" />
        </button>

        {/* Notifications placeholder */}
        <button
          disabled
          title="Coming soon"
          className="relative flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground cursor-not-allowed opacity-50"
        >
          <Bell className="h-4 w-4" />
          <span className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-primary" />
        </button>

        {/* Help */}
        <button
          disabled
          title="Coming soon"
          className="flex h-8 w-8 items-center justify-center rounded-lg text-muted-foreground cursor-not-allowed opacity-50"
        >
          <HelpCircle className="h-4 w-4" />
        </button>

        {/* Divider */}
        <div className="mx-2 h-4 w-px bg-border" />

        {/* Sign out */}
        <button
          onClick={signOut}
          className="flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
        >
          <LogOut className="h-3.5 w-3.5" />
          Sign out
        </button>
      </div>
    </header>
  );
}
