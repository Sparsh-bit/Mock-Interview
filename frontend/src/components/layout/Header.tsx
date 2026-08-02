'use client';

import { HelpCircle, LogOut } from 'lucide-react';
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
    <header className="flex h-14 items-center justify-between border-b border-border/60 bg-background/70 backdrop-blur-xl/60 px-6 backdrop-blur-md">
      {/* Page title */}
      <div>
        <h2 className="text-sm font-semibold tracking-tight">{title}</h2>
      </div>

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
