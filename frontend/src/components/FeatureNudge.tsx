'use client';

import Link from 'next/link';
import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Mic, MessageSquare, ArrowRight, Sparkles } from 'lucide-react';
import { useActivity, type ActivityType } from '@/hooks/useActivity';

interface Nudge {
  type: ActivityType;
  href: string;
  icon: typeof Mic;
  title: string;
  body: string;
  cta: string;
  dismissKey: string;
}

// Features we gently encourage the candidate to try if they haven't yet.
const NUDGES: Nudge[] = [
  {
    type: 'communication',
    href: '/communication',
    icon: Mic,
    title: 'Try the Communication Round',
    body: 'Practice speaking answers aloud — we measure your pace, filler words and pauses, plus a new reading-comprehension mode.',
    cta: 'Start speaking practice',
    dismissKey: 'interviewos:nudge:communication',
  },
  {
    type: 'group_discussion',
    href: '/gd',
    icon: MessageSquare,
    title: 'Try a Group Discussion',
    body: 'Join an AI-simulated panel discussion and get scored on contribution, clarity and engagement — a key placement round.',
    cta: 'Start a group discussion',
    dismissKey: 'interviewos:nudge:gd',
  },
];

/**
 * A dismissible nudge encouraging the candidate to try a round they haven't
 * done yet (communication or group discussion). Data-driven off their real
 * activity history — it never suggests something they've already completed, and
 * dismissals persist locally so it isn't nagging.
 */
export function FeatureNudge() {
  const { data: activity } = useActivity(100);
  const [dismissed, setDismissed] = useState<string[]>([]);

  if (!activity) return null;

  const doneTypes = new Set(activity.map((a) => a.activity_type));

  const nudge = NUDGES.find((n) => {
    if (doneTypes.has(n.type)) return false;
    if (dismissed.includes(n.dismissKey)) return false;
    if (typeof window !== 'undefined' && localStorage.getItem(n.dismissKey) === 'true') return false;
    return true;
  });

  if (!nudge) return null;

  const Icon = nudge.icon;
  const dismiss = () => {
    localStorage.setItem(nudge.dismissKey, 'true');
    setDismissed((d) => [...d, nudge.dismissKey]);
  };

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, height: 0 }}
        // A flat indigo tint, not a two-hue gradient. The gradient ran from the
        // primary to a second accent and was the only place in the app where two
        // colours blended into each other — which read as decoration, and put a
        // purple wash across the top of the dashboard that matched nothing else.
        className="relative overflow-hidden rounded-2xl border border-accent-indigo/20 bg-accent-indigo-soft p-5"
      >
        <button
          onClick={dismiss}
          aria-label="Dismiss"
          className="absolute right-3 top-3 rounded-md p-1 text-muted-foreground transition-colors hover:bg-black/5 hover:text-foreground"
        >
          <X className="h-4 w-4" />
        </button>
        <div className="flex items-start gap-4 pr-6">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-accent-indigo text-white">
            <Icon className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <Sparkles className="h-3.5 w-3.5 text-accent-indigo-ink" />
              <p className="text-[11px] font-semibold uppercase tracking-wider text-accent-indigo-ink">New for you</p>
            </div>
            <h3 className="mt-1 text-base font-semibold">{nudge.title}</h3>
            <p className="mt-1 text-sm text-muted-foreground">{nudge.body}</p>
            <Link
              href={nudge.href}
              className="mt-3 inline-flex items-center gap-1.5 text-sm font-semibold text-primary transition-opacity hover:opacity-80"
            >
              {nudge.cta} <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
