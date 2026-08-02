'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { motion } from 'framer-motion';
import {
  Target,
  BarChart3,
  BookOpen,
  ChevronLeft,
  FileText,
  LayoutDashboard,
  ListChecks,
  MessageSquare,
  Play,
  Users,
  Settings,
  Trophy,
  User,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useState } from 'react';
import type { User as SupabaseUser } from '@supabase/supabase-js';

const NAV_ITEMS = [
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
      { href: '/achievements', icon: Trophy, label: 'Achievements' },
    ],
  },
  {
    group: 'Account',
    items: [
      { href: '/profile', icon: User, label: 'Profile' },
      { href: '/settings', icon: Settings, label: 'Settings' },
    ],
  },
];

interface SidebarProps {
  user: SupabaseUser;
}

export function AppSidebar({ user }: SidebarProps) {
  const [collapsed, setCollapsed] = useState(false);
  const pathname = usePathname();

  return (
    <motion.aside
      animate={{ width: collapsed ? 72 : 240 }}
      transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
      className="relative flex flex-shrink-0 flex-col border-r border-border/60 bg-surface/70 backdrop-blur-xl"
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
        {NAV_ITEMS.map(({ group, items }) => (
          <div key={group} className="mb-5">
            {!collapsed && (
              <p className="mb-1.5 px-2.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground/60">
                {group}
              </p>
            )}
            <ul className="space-y-0.5">
              {items.map(({ href, icon: Icon, label }) => {
                const isActive = pathname === href || pathname.startsWith(href + '/');
                return (
                  <li key={href} className="relative">
                    <Link
                      href={href}
                      title={collapsed ? label : undefined}
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
                      <Icon className="h-[15px] w-[15px] flex-shrink-0" strokeWidth={1.9} />
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
