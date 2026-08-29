'use client';

import Link from 'next/link';

import { Infinity as InfinityIcon, Sparkles } from 'lucide-react';

import { useBalance } from '@/hooks/useBilling';
import { cn } from '@/lib/utils';

/**
 * What you have left — components/billing/BalanceChip.tsx
 *
 * This replaced a permanent "Plans" button in the header, and the swap is the whole idea.
 *
 * A button that says "Plans" is an advert: it asks every time, it says the same thing whether
 * you have ten interviews left or none, and people stop seeing it within a day. A chip that
 * says "2 left" is INFORMATION — and it happens to be the single most persuasive thing we can
 * put on the screen, because the person reading it already wants the thing it is counting.
 * The pricing page is one tap away from it either way; the difference is that this one earns
 * the tap instead of begging for it.
 *
 * IT ESCALATES BY COLOUR, and the colours are the ones the design system already assigns:
 *
 *   plenty (3+)  quiet — a number, no tint. Nothing is wrong, so nothing shouts.
 *   low (1-2)    amber, which means money everywhere else in this product.
 *   none (0)     coral, which means blocked. The label becomes an instruction.
 *   unlimited    plum, and it says so rather than showing a stuck counter.
 *
 * Escalation matters more than volume. If it were amber all the time, amber would stop meaning
 * "soon" — and then there would be nothing left to say "now".
 *
 * IT SHOWS INTERVIEWS SPECIFICALLY, not a sum across features. Interviews are what people come
 * for and what costs the most to serve; a combined number would be reassuringly large and
 * would hide the one allowance that actually runs out. If interviews are not metered for this
 * account, the chip shows nothing rather than inventing something to say.
 */
export function BalanceChip({ className }: { className?: string }) {
  const { data } = useBalance();

  // No opinion until the server has one. Rendering "0 left" during load would tell a paying
  // user they are blocked, and they would believe it — a flash of a wrong number is worse
  // than a beat of nothing.
  if (!data) return null;

  if (data.unlimited) {
    return (
      <Link
        href="/pricing"
        aria-label="Plans and pricing — this account is unlimited"
        className={cn(
          'flex h-8 items-center gap-1.5 rounded-full border border-accent-plum/25 bg-accent-plum-soft px-2.5 text-[11px] font-medium text-accent-plum-ink transition-colors hover:border-accent-plum/45',
          className,
        )}
      >
        <InfinityIcon className="h-3.5 w-3.5 shrink-0" />
        <span className="hidden sm:inline">Unlimited</span>
      </Link>
    );
  }

  const interviews = data.features.find((f) => f.feature === 'interview');
  if (!interviews) return null;

  const left = interviews.remaining;
  const out = left <= 0;
  const low = left > 0 && left <= 2;

  /*
   * The label is written for the state, not templated from it. "Out of interviews" tells you
   * what happened; "0 left" makes you work it out. And at the moment somebody is blocked, the
   * short version on a narrow screen should be the verb — "Get more" — because that is the
   * only thing left to do.
   */
  const full = out ? 'Out of interviews' : `${left} interview${left === 1 ? '' : 's'} left`;
  const short = out ? 'Get more' : `${left} left`;

  return (
    <Link
      href="/pricing"
      // The accessible name is always the full sentence, even when the visible text is
      // abbreviated — a screen reader announcing "2 left" gives no clue what is being counted.
      aria-label={`${full} — see plans and pricing`}
      title={full}
      className={cn(
        'flex h-8 items-center gap-1.5 rounded-full border px-2.5 text-[11px] font-medium transition-colors',
        out &&
          'border-accent-coral/30 bg-accent-coral-soft text-accent-coral-ink hover:border-accent-coral/50',
        low &&
          'border-accent-amber/30 bg-accent-amber-soft text-accent-amber-ink hover:border-accent-amber/50',
        !out &&
          !low &&
          'border-border bg-surface-elevated text-muted-foreground hover:border-accent-amber/40 hover:text-foreground',
        className,
      )}
    >
      <Sparkles
        className={cn(
          'h-3.5 w-3.5 shrink-0',
          out && 'text-accent-coral',
          low && 'text-accent-amber',
          !out && !low && 'text-accent-amber/70',
        )}
      />
      <span className="hidden md:inline">{full}</span>
      <span className="md:hidden">{short}</span>
    </Link>
  );
}
