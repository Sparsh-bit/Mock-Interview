'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { motion } from 'framer-motion';
import {
  BarChart3,
  BookOpen,
  ChevronLeft,
  Code2,
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
      className="relative flex flex-shrink-0 flex-col border-r border-border/70 bg-surface"
    >
      {/* Logo */}
      <div className={cn('flex h-16 items-center border-b border-border/70 px-4', collapsed && 'justify-center')}>
        <Link href="/dashboard" className="flex min-w-0 items-center gap-2.5">
          <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary to-accent-violet shadow-glow">
            <Code2 className="h-4 w-4 text-primary-foreground" />
          </div>
          {!collapsed && (
            <span className="truncate text-sm font-bold tracking-tight">InterviewOS</span>
          )}
        </Link>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-3 py-4">
        {NAV_ITEMS.map(({ group, items }) => (
          <div key={group} className="mb-6">
            {!collapsed && (
              <p className="mb-2 px-2 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/70">
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
                        'relative z-10 flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                        collapsed && 'justify-center px-2',
                        isActive ? 'text-primary' : 'text-muted-foreground hover:text-foreground'
                      )}
                    >
                      <Icon className="h-4 w-4 flex-shrink-0" />
                      {!collapsed && <span className="truncate">{label}</span>}
                    </Link>
                    {isActive && (
                      <motion.div
                        layoutId="sidebar-active-pill"
                        className="absolute inset-0 rounded-lg bg-primary/10 ring-1 ring-primary/25"
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
              <p className="text-[10px] text-muted-foreground">Free Plan</p>
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
