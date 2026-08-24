'use client';

import Link from 'next/link';
import { useState } from 'react';
import { motion } from 'framer-motion';
import { ArrowRight, Mic, Users, X, FileText, Zap, Timer } from 'lucide-react';

import { useActivity } from '@/hooks/useActivity';
import { useBalance, useStoreItems } from '@/hooks/useBilling';
import { useUserStats } from '@/hooks/useData';
import { cn } from '@/lib/utils';

/**
 * The nudge deck — components/dashboard/NudgeDeck.tsx
 *
 * ASKED FOR AS "ads on the dashboard like we get on Zomato", with Hinglish punchlines. The
 * format is borrowed; the content deliberately is not.
 *
 * WHY EVERY CARD CARRIES A NUMBER THE CANDIDATE CAN CHECK. A food app can advertise a
 * discount to everyone because the discount is the same for everyone. Here the only thing
 * worth saying is about THIS person's practice, and DESIGN-RULES.md bans the alternative
 * outright: no vague superlatives, no rounded-up stats, no claim the code cannot support. So
 * a card only exists when a real condition is true, and the sentence names the figure that
 * made it true — 0 interviews left, an average of 54, a group discussion never attempted.
 * Generic copy would be both worse advertising and a rule violation.
 *
 * THE HINGLISH IS THE HOOK, THE ENGLISH IS THE FACT. Two registers doing two jobs: the first
 * line is how somebody would actually say it out loud to a friend preparing for placements,
 * and the second is the measurable thing underneath it. That split is also why the Hinglish
 * never carries the number — a claim should not be made in the register that is allowed to be
 * casual.
 *
 * IT IS A SCROLLING STRIP, NOT A GRID. Three equal cards across is the single most
 * recognisable machine-made layout there is, and DESIGN-RULES.md names it. A strip of
 * differently-weighted cards also degrades correctly: with one card it is a banner, with four
 * it scrolls, and neither state needs a different component.
 *
 * IT RENDERS NOTHING WHEN THERE IS NOTHING TRUE TO SAY. No filler card, no "explore our
 * features". An empty deck collapses and the dashboard below it moves up.
 */

type Tone = 'indigo' | 'amber' | 'coral' | 'plum' | 'teal';

interface Nudge {
  key: string;
  tone: Tone;
  icon: typeof Mic;
  /** The spoken hook. Never carries a number — see the note above. */
  hook: string;
  /** The checkable fact. Always carries the number that made this card appear. */
  fact: string;
  cta: string;
  href: string;
  /** Higher wins. Only the top few are shown. */
  weight: number;
}

/**
 * Tone → classes, resolved eagerly rather than by string interpolation.
 *
 * Tailwind compiles the classes it can SEE. `bg-accent-${tone}-soft` is invisible to the
 * scanner, so it survives dev (where the JIT has already met the literal elsewhere) and
 * silently loses its background in a production build — the exact failure mode that is
 * hardest to catch, because the component still renders.
 *
 * The colour bindings are DESIGN-RULES.md's, not decoration: indigo is the product and its
 * primary actions, amber is preparation and effort, coral is flagged or needs work, plum is
 * the behavioural rounds, teal is measurement. `-ink` is the only tone safe for text under
 * 18px.
 */
const TONE: Record<Tone, { wrap: string; chip: string; ink: string }> = {
  indigo: {
    wrap: 'border-accent-indigo/30 bg-accent-indigo-soft',
    chip: 'bg-accent-indigo/15 text-accent-indigo-ink',
    ink: 'text-accent-indigo-ink',
  },
  amber: {
    wrap: 'border-accent-amber/30 bg-accent-amber-soft',
    chip: 'bg-accent-amber/15 text-accent-amber-ink',
    ink: 'text-accent-amber-ink',
  },
  coral: {
    wrap: 'border-accent-coral/30 bg-accent-coral-soft',
    chip: 'bg-accent-coral/15 text-accent-coral-ink',
    ink: 'text-accent-coral-ink',
  },
  plum: {
    wrap: 'border-accent-plum/30 bg-accent-plum-soft',
    chip: 'bg-accent-plum/15 text-accent-plum-ink',
    ink: 'text-accent-plum-ink',
  },
  teal: {
    wrap: 'border-accent-teal/30 bg-accent-teal-soft',
    chip: 'bg-accent-teal/15 text-accent-teal-ink',
    ink: 'text-accent-teal-ink',
  },
};

const DISMISS_PREFIX = 'interviewos:nudge:';

function dismissed(key: string): boolean {
  if (typeof window === 'undefined') return false;
  try {
    return localStorage.getItem(DISMISS_PREFIX + key) === 'true';
  } catch {
    // Private windows and blocked site data throw on access rather than returning null. A
    // nudge that cannot read its dismissal is a nudge that shows again, which is a far better
    // failure than a dashboard that throws.
    return false;
  }
}

export function NudgeDeck() {
  const { data: stats } = useUserStats();
  const { data: activity } = useActivity(100);
  const { data: balance } = useBalance({ enabled: true });
  const { data: items } = useStoreItems();
  const [hidden, setHidden] = useState<string[]>([]);

  // Everything below reads real state, so nothing renders until it has arrived. A card that
  // appears and then changes its number a moment later reads as a guess.
  if (!stats || !activity || !balance) return null;
  if (balance.unlimited) return null; // Operator accounts are not sold to.

  const done = new Set(activity.map((a) => a.activity_type));
  const left = (feature: string) =>
    balance.features.find((f) => f.feature === feature)?.remaining ?? 0;

  const interviewsLeft = left('interview');
  const gdLeft = left('gd');

  const single = items?.find((i) => i.feature === 'interview' && i.quantity === 1);
  const bundle = items?.find((i) => i.feature === 'interview' && i.quantity > 1);
  const perUnit = bundle ? Math.round(bundle.price_rupees / bundle.quantity) : null;

  const candidates: Nudge[] = [];

  /*
   * OUT OF INTERVIEWS — the only card that is unambiguously an advert, and it is shown to the
   * one person for whom it is useful information rather than a pitch: somebody with none left.
   * The saving is computed from the catalogue rather than written down, because a price
   * written into the frontend is a price that goes stale silently.
   */
  if (interviewsLeft === 0 && single && bundle && perUnit) {
    candidates.push({
      key: 'buy-interview',
      tone: 'indigo',
      icon: Zap,
      hook: 'Interview khatam. Ek aur chahiye?',
      fact:
        `You have 0 mock interviews left. One is ₹${single.price_rupees}; ` +
        `the pack of ${bundle.quantity} works out at ₹${perUnit} each.`,
      cta: 'See plans',
      href: '/pricing',
      weight: 100,
    });
  }

  /*
   * PAID FOR AND UNUSED. The opposite problem, and worth more to the candidate than to us: an
   * interview sitting in their account is practice they have already bought and not taken.
   */
  if (interviewsLeft > 0) {
    candidates.push({
      key: 'use-interview',
      tone: 'amber',
      icon: Timer,
      hook: 'Pade hue hain. Use kar lo.',
      fact:
        `${interviewsLeft} mock interview${interviewsLeft === 1 ? '' : 's'} on your account, ` +
        'unused. Twelve questions and a scored report each.',
      cta: 'Start one',
      href: '/interview',
      weight: 80,
    });
  }

  /*
   * A LOW AVERAGE, STATED PLAINLY. The pitch here is not "improve" — it is that a real panel
   * never tells you WHY, and the report does. That is the actual product difference, and it
   * is the sentence DESIGN-RULES.md asks for: one somebody believes, not a feature summary.
   */
  if (stats.completed_sessions > 0 && stats.average_score !== null && stats.average_score < 60) {
    candidates.push({
      key: 'low-average',
      tone: 'coral',
      icon: FileText,
      hook: 'Panel ye nahi batayega.',
      fact:
        `Your average is ${Math.round(stats.average_score)}/100 across ` +
        `${stats.completed_sessions} interview${stats.completed_sessions === 1 ? '' : 's'}. ` +
        'The report breaks it down question by question, with the answer you should have given.',
      cta: 'Open your reports',
      href: '/report',
      weight: 90,
    });
  }

  /*
   * THE TWO ROUNDS PEOPLE SKIP. Both are real placement rounds and both are the ones
   * candidates avoid precisely because they are spoken rather than written. The facts are the
   * measured mechanics, not adjectives.
   */
  if (!done.has('group_discussion')) {
    candidates.push({
      key: 'try-gd',
      tone: 'plum',
      icon: Users,
      hook: 'GD mein bolne ka mauka hi nahi milta?',
      fact:
        'Eight minutes against three AI panelists who interrupt and argue back, then scored on ' +
        'contribution and clarity.' +
        (gdLeft > 0 ? ` You have ${gdLeft} left.` : ''),
      cta: 'Try a group discussion',
      href: '/gd',
      weight: 70,
    });
  }

  if (!done.has('communication')) {
    candidates.push({
      key: 'try-communication',
      tone: 'teal',
      icon: Mic,
      hook: 'Bolte waqt "matlab" kitni baar aata hai?',
      fact:
        'The communication round counts every filler, times your pauses to the second and ' +
        'measures your pace in words per minute.',
      cta: 'Speak an answer',
      href: '/communication',
      weight: 60,
    });
  }

  const deck = candidates
    .filter((n) => !hidden.includes(n.key) && !dismissed(n.key))
    .sort((a, b) => b.weight - a.weight)
    .slice(0, 3);

  if (deck.length === 0) return null;

  const hide = (key: string) => {
    setHidden((prev) => [...prev, key]);
    try {
      localStorage.setItem(DISMISS_PREFIX + key, 'true');
    } catch {
      // Dismissal that cannot be persisted still works for this page view. Not worth an error.
    }
  };

  return (
    /*
     * min-w-0 ON THE ITEMS IS LOAD-BEARING. A flex item defaults to min-width:auto, so it
     * refuses to shrink below its content and the scroll container never actually scrolls —
     * the row just overflows the page instead, which is how horizontal scroll silently becomes
     * a broken layout on a phone.
     */
    <div
      className="-mx-1 flex snap-x snap-mandatory gap-3 overflow-x-auto px-1 pb-2 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      aria-label="Suggestions based on your practice"
    >
      {deck.map((n, i) => {
        const tone = TONE[n.tone];
        const Icon = n.icon;
        return (
          <motion.div
            key={n.key}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.28, delay: i * 0.05 }}
            className={cn(
              'relative flex min-w-0 shrink-0 snap-start flex-col justify-between rounded-2xl border p-4',
              // Deliberately uneven widths. Equal cards in a row is the layout DESIGN-RULES.md
              // names as the machine-made tell; the first card is also the highest-weighted
              // one, so the extra width is carrying meaning rather than decorating.
              i === 0 ? 'w-[19rem] sm:w-[23rem]' : 'w-[17rem] sm:w-[20rem]',
              tone.wrap,
            )}
          >
            <button
              type="button"
              onClick={() => hide(n.key)}
              aria-label={`Dismiss: ${n.hook}`}
              className="absolute right-2 top-2 rounded-md p-1 text-muted-foreground transition-colors hover:bg-black/5 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <X className="h-3.5 w-3.5" aria-hidden />
            </button>

            <div className="min-w-0 pr-6">
              <span
                className={cn(
                  'inline-flex h-7 w-7 items-center justify-center rounded-lg',
                  tone.chip,
                )}
              >
                <Icon className="h-4 w-4" aria-hidden />
              </span>
              {/* The hook is the largest thing on the card and carries no claim. */}
              <p className={cn('mt-2.5 text-[0.95rem] font-semibold leading-snug', tone.ink)}>
                {n.hook}
              </p>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{n.fact}</p>
            </div>

            <Link
              href={n.href}
              className={cn(
                'group mt-3 inline-flex items-center gap-1.5 text-xs font-semibold',
                tone.ink,
              )}
            >
              {n.cta}
              <ArrowRight
                className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5 motion-reduce:transition-none motion-reduce:group-hover:translate-x-0"
                aria-hidden
              />
            </Link>
          </motion.div>
        );
      })}
    </div>
  );
}

export default NudgeDeck;
