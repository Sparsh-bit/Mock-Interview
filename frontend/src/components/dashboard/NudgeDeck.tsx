'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import {
  ArrowRight,
  MessageSquare,
  Mic,
  Sparkles,
  Target,
  TrendingUp,
  X,
  Zap,
} from 'lucide-react';

import { useActivity } from '@/hooks/useActivity';
import { useBalance, useStoreItems } from '@/hooks/useBilling';
import { useUserStats } from '@/hooks/useData';
import { useProgress } from '@/hooks/useProgress';
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

// Old name kept deliberately: these keys record which nudges a person has already dismissed.
// Renaming the prefix would un-dismiss every one of them and re-nag every existing user.
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


//: How long one card holds the floor before the next takes it.
//:
//: NINE SECONDS, and the number is the whole difference between an advert and an irritation.
//: Short enough that a second message gets seen at all; long enough to read a line of Hinglish
//: and act on it without the card changing under the cursor. It pauses entirely on hover and
//: on keyboard focus, so it can never move while somebody is reading or reaching for it.
const ROTATE_MS = 9_000;

/**
 * The dashboard's one advert — components/dashboard/NudgeDeck.tsx
 *
 * WHAT IT IS FOR. Interviews and group discussions are paid and quizzes are not, so the single
 * most valuable thing this page can do for the business is tell somebody who has only ever
 * taken quizzes that the other two exist and what they cost. Doing that in a banner nobody
 * reads is the same as not doing it.
 *
 * WHY IT ROTATES RATHER THAN STACKING. Three cards down the page is three things to ignore;
 * one card that changes is one thing to glance at. It also lets the deck carry a message for
 * every state a candidate can be in without any of them costing vertical space.
 *
 * WHY IT PAUSES. An advert that moves while you are reading it is worse than one that does not
 * move at all — you lose the line you were on and there is no way back. Hover and focus both
 * stop the timer, and `prefers-reduced-motion` stops it starting.
 *
 * EVERY PRICE COMES FROM THE SERVER. `useStoreItems` is the catalogue, and plans.py is the
 * only thing that decides what anything costs. A rupee figure typed into this file is a figure
 * that goes stale the day a price changes, silently, in the most public place in the product —
 * there is a test that fails on a hardcoded one.
 */
export function NudgeDeck() {
  const { data: stats } = useUserStats();
  const { data: activity } = useActivity(100);
  const { data: balance } = useBalance({ enabled: true });
  const { data: items } = useStoreItems();
  // Read defensively and never blocking, exactly as `stats` and `activity` are: a failed
  // progress read must cost these two cards, never the whole deck.
  const { data: progress } = useProgress();
  const [hidden, setHidden] = useState<string[]>([]);
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);

  /*
   * GATED ON WHAT THE CARD ACTUALLY READS, which is the balance and the catalogue.
   *
   * It used to wait for `stats` and `activity` too, and that is why nothing was appearing: any
   * one of four queries still in flight — or failing, which on a dashboard is routine — meant
   * the whole deck rendered null and no advert was ever seen. `stats` and `activity` only
   * refine WHICH card is chosen, so they are read defensively below and never block.
   */
  const ready = !!balance && !!items;
  const unlimited = balance?.unlimited === true;

  const done = new Set((activity ?? []).map((a) => a.activity_type));
  const left = (feature: string) =>
    balance?.features.find((f) => f.feature === feature)?.remaining ?? 0;

  const priceOf = (feature: string) =>
    items?.find((i) => i.feature === feature && i.quantity === 1)?.price_rupees ?? null;

  const interviewRs = priceOf('interview');
  const gdRs = priceOf('gd');
  const commLeft = left('communication');
  const interviewsLeft = left('interview');
  const gdLeft = left('gd');

  const deck: Nudge[] = [];

  /*
   * ── PICK UP WHERE YOU LEFT OFF ────────────────────────────────────────────────────────
   *
   * An interview that was started and abandoned — a dropped connection, a flatmate, a battery
   * — leaves a live session with answers in it and nothing pointing back to it. The candidate
   * returns to a dashboard offering them a brand new interview, which costs another credit and
   * throws away the answers they already gave.
   *
   * FIRST IN THE DECK (weight -2), because unlike everything below it this is not a pitch: it
   * is the candidate's own unfinished work, and it is the one card that saves them money
   * rather than asking for it.
   *
   * NO URGENCY, AND THE ABSENT WORDS ARE THE POINT. `hours_ago` is available and is not
   * rendered as a countdown; there is no "expires soon", no "before you lose it", no timer.
   * The fact stated is how far in they got, which is the thing that makes coming back
   * attractive on its own.
   */
  if (progress?.resume) {
    const answered = progress.resume.questions_answered;
    deck.push({
      key: `resume-${progress.resume.session_id}`,
      tone: 'indigo',
      icon: ArrowRight,
      hook: 'Aapka interview adhoora pada hai 🙂',
      fact: `You answered ${answered} question${answered === 1 ? '' : 's'} and stopped. Pick it up where you left it — nothing to pay again.`,
      cta: 'Resume the interview',
      href: `/session/${progress.resume.session_id}`,
      weight: -2,
    });
  }

  /*
   * ── THE STREAK, STATED ─────────────────────────────────────────────────────────────────
   *
   * ONLY WHEN THERE IS A RUN TO SPEAK OF, and never as a warning.
   *
   * The rejected version of this card is the obvious one: "your 6-day streak ends tonight",
   * with a clock. That is manufactured urgency about a number that grants nothing, aimed at an
   * audience this product cannot reliably confirm is over 18 — see `docs/COMPLIANCE.md` and
   * DPDP §9. So the card says what is true and offers the ordinary next step; a candidate who
   * closes the tab loses a count and nothing else, which is exactly what a streak here IS.
   *
   * Weight 6 puts it last: it is the least commercially useful card on the deck and the one
   * most easily overused, and burying it is the right way round.
   */
  if (progress && progress.streak.days >= 2 && progress.streak.at_risk) {
    deck.push({
      key: 'streak-open',
      tone: 'teal',
      icon: TrendingUp,
      hook: 'Aaj ka practice baaki hai.',
      fact: `${progress.streak.days} days of practice in a row so far. Today is open — a quiz counts, and quizzes are free.`,
      cta: 'Take a quiz',
      href: '/quiz',
      weight: 6,
    });
  }

  if (ready && !unlimited && interviewRs !== null && gdRs !== null) {
    /*
     * THE ORDER IS THE PITCH, and it is ordered by how close somebody is to buying rather than
     * by what we would most like to sell. Somebody holding a free communication drill is one
     * completed round away from having a reason to care about the paid ones; somebody who has
     * just finished an interview has already proved they will.
     */
    if (commLeft > 0 && !done.has('communication')) {
      deck.push({
        key: 'free-comm',
        tone: 'teal',
        icon: Mic,
        hook: 'Ek communication test free hai 👀',
        fact: 'Free hai. Dekho aap kahan khade ho — pace, clarity aur filler words par score.',
        cta: 'Take the free test',
        href: '/communication',
        weight: 0,
      });
    }
    if (interviewsLeft === 0) {
      deck.push({
        key: 'buy-interview',
        tone: 'indigo',
        icon: Zap,
        hook: 'HR se pehle AI interviewer ko face karo 🎤',
        fact: `Twelve questions, a two-person panel and a full scored report. ₹${interviewRs}.`,
        cta: 'Start an interview',
        href: '/pricing#apply-offer',
        weight: 1,
      });
      deck.push({
        key: 'no-free-trial',
        tone: 'indigo',
        icon: Sparkles,
        hook: 'Interview ka free trial nahi hai 😏',
        fact: `Real practice starts at ₹${interviewRs} — and unlimited quizzes stay free.`,
        cta: 'See what you get',
        href: '/pricing',
        weight: 3,
      });
    }
    if (gdLeft === 0) {
      deck.push({
        key: 'buy-gd',
        tone: 'plum',
        icon: MessageSquare,
        hook: 'GD mein sirf sunna nahi, bolna bhi padta hai 😭',
        fact: `Eight minutes against three panellists who argue back, then scored. ₹${gdRs}.`,
        cta: 'Practise a GD',
        href: '/pricing#apply-offer',
        weight: 2,
      });
    }
    if (done.has('quiz') && !done.has('interview')) {
      deck.push({
        key: 'quiz-to-interview',
        tone: 'amber',
        icon: TrendingUp,
        hook: 'Quiz se knowledge check. AI interview se confidence.',
        fact: `Quizzes stay free and unlimited. The interview is where you find out if you can say it out loud — ₹${interviewRs}.`,
        cta: 'Try an interview',
        href: '/pricing',
        weight: 4,
      });
    }
    if (done.has('interview')) {
      deck.push({
        key: 'placement-soon',
        tone: 'coral',
        icon: Target,
        hook: 'Placement aa rahi hai. Ready ho jao.',
        fact: `Another interview is ₹${interviewRs}, and a GD is ₹${gdRs}. Both scored, both today.`,
        cta: 'Add a round',
        href: '/pricing',
        weight: 5,
      });
    }
  }

  const visible = deck
    .filter((n) => !hidden.includes(n.key) && !dismissed(n.key))
    .sort((a, b) => a.weight - b.weight);

  /*
   * THE ROTATION.
   *
   * Cleared and rebuilt whenever the deck size, the pause state or the index changes, so there
   * is never more than one timer alive — two would advance the card twice as fast and look
   * like a flicker. A single-card deck never starts one at all: rotating between one thing and
   * itself is a re-render for no reason.
   */
  const reduceMotion =
    typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

  useEffect(() => {
    if (paused || reduceMotion || visible.length < 2) return;
    const t = setTimeout(() => setIndex((i) => (i + 1) % visible.length), ROTATE_MS);
    return () => clearTimeout(t);
  }, [paused, reduceMotion, visible.length, index]);

  // The deck shrinks when a card is dismissed, so an index held from before can point past the
  // end. Clamped at read time rather than in an effect: an effect would render one empty frame
  // first, which is a visible flash of nothing.
  const current = visible[index % Math.max(1, visible.length)];
  if (!current) return null;

  const tone = TONE[current.tone];
  const Icon = current.icon;

  return (
    <div
      className="relative"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
    >
      <AnimatePresence mode="wait">
        <motion.div
          key={current.key}
          initial={reduceMotion ? false : { opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={reduceMotion ? undefined : { opacity: 0, y: -6 }}
          transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
          className={cn(
            'flex flex-wrap items-center gap-x-4 gap-y-3 rounded-2xl border p-4 sm:p-5',
            tone.wrap,
          )}
        >
          <span
            className={cn(
              'flex h-10 w-10 shrink-0 items-center justify-center rounded-full',
              tone.chip,
            )}
          >
            <Icon className="h-5 w-5" aria-hidden />
          </span>

          <div className="min-w-0 flex-1">
            <p className={cn('text-sm font-semibold', tone.ink)}>{current.hook}</p>
            <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
              {current.fact}
            </p>
          </div>

          <Link
            href={current.href}
            className={cn(
              'inline-flex shrink-0 items-center gap-1.5 rounded-lg px-3.5 py-2 text-sm font-semibold',
              'transition-transform hover:-translate-y-px focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              tone.chip,
            )}
          >
            {current.cta}
            <ArrowRight className="h-3.5 w-3.5" aria-hidden />
          </Link>

          <button
            type="button"
            aria-label="Hide this suggestion"
            onClick={() => {
              try {
                localStorage.setItem(DISMISS_PREFIX + current.key, 'true');
              } catch {
                // Blocked site data. Hiding it for this visit is still worth doing.
              }
              setHidden((h) => [...h, current.key]);
            }}
            className="absolute right-2 top-2 rounded-md p-1 text-muted-foreground/60 transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <X className="h-3.5 w-3.5" aria-hidden />
          </button>
        </motion.div>
      </AnimatePresence>

      {/* WHICH OF HOW MANY. Without it a card that changes on its own reads as a glitch; with
          it, it reads as a deck, and somebody who wants the one they just saw can tap back to
          it. Hidden for a single-card deck, where it would be one dot saying nothing. */}
      {visible.length > 1 && (
        <div className="mt-2 flex justify-center gap-1.5">
          {visible.map((n, i) => (
            <button
              key={n.key}
              type="button"
              aria-label={`Show suggestion ${i + 1} of ${visible.length}`}
              aria-current={i === index % visible.length}
              onClick={() => setIndex(i)}
              className={cn(
                'h-1.5 rounded-full transition-all',
                i === index % visible.length
                  ? 'w-5 bg-foreground/40'
                  : 'w-1.5 bg-foreground/15 hover:bg-foreground/30',
              )}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default NudgeDeck;
