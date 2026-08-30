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

  /*
   * NO NUMBER UNTIL THE SERVER HAS ONE — BUT ALWAYS A ROUTE.
   *
   * Two requirements pull against each other here and the first version of this got the
   * second one wrong. Rendering "0 left" while the balance is still loading would tell a
   * paying user they are blocked and they would believe it, so the figure has to wait. But I
   * returned `null` for that case, which also removed the header's link to /pricing — and the
   * comment on the button this replaced spells out exactly why that link must never
   * disappear: below `lg` the rail is hidden, so this is the ONLY always-visible route to the
   * one action that resolves a 402. A candidate who cannot find the way to unblock themselves
   * concludes the product is broken.
   *
   * `useBalance` also returns no data on a network failure, so the link vanished precisely
   * when somebody most needed it.
   *
   * So: the plain label while we do not know, the real figure once we do. No flash of a wrong
   * number, and the route is never gone.
   */
  if (!data) return <PlainPlansLink className={className} />;

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
  /*
   * THE SECOND HOLE, and I only found it because the test above states the property as "never
   * returns null" rather than describing the loading fix I had just made.
   *
   * If the server ever stops metering `interview` — a plan change, a feature rename, a partial
   * response — this returned nothing, and the header lost its only route to /pricing on
   * phones for reasons that have nothing to do with the account being in trouble. There is
   * nothing truthful to count in that case, so it falls back to the plain label rather than
   * inventing a number or disappearing.
   */
  if (!interviews) return <PlainPlansLink className={className} />;

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

/**
 * The chip with no figure on it: the word, the icon, and the route.
 *
 * Used whenever there is nothing truthful to count — the balance has not arrived, the request
 * failed, or the account does not meter interviews at all. It is deliberately the same size
 * and shape as the counted version so the header does not reflow when the number lands.
 */
function PlainPlansLink({ className }: { className?: string }) {
  return (
    <Link
      href="/pricing"
      // The name has to survive the label being hidden. `hidden` removes the span from the
      // accessibility tree as well as from the layout, so between 0 and 640px this would
      // otherwise be an anchor announced as "link" with no indication of where it goes — and
      // that is the width band this link exists for in the first place.
      aria-label="Plans and pricing"
      className={cn(
        'flex h-8 items-center gap-1.5 rounded-full border border-border bg-surface-elevated px-2.5 text-[11px] font-medium text-muted-foreground transition-colors hover:border-accent-amber/40 hover:text-foreground',
        className,
      )}
    >
      <Sparkles className="h-3.5 w-3.5 shrink-0 text-accent-amber/70" />
      <span className="hidden sm:inline">Plans</span>
    </Link>
  );
}
