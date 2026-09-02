import Link from 'next/link';
import { ArrowRight, Check } from 'lucide-react';

/**
 * WHAT IT COSTS — components/marketing/MkPricing.tsx
 *
 * ── NO PRICE IS TYPED INTO THIS FILE, AND THAT IS A RULE ─────────────────────────────────
 * `backend/app/services/billing/plans.py` is the single source of truth for what anything
 * costs; `/pricing` fetches it from `GET /billing/items` and renders whatever comes back. A
 * figure written into a marketing component is a figure that goes stale silently — the
 * checkout charges the new price, the landing page keeps promising the old one, and the first
 * person to notice is a customer mid-payment. So this section states the SHAPE of the offer,
 * which changes rarely and is a product decision, and sends you one click away for the
 * number, which changes and is not.
 *
 * ── TWO CARDS, NOT THREE ─────────────────────────────────────────────────────────────────
 * The reference has three because it sells three things. This product sells two: a free tier
 * that is genuinely free forever, and sessions you buy one at a time. Inventing a third
 * column to fill a grid is how a pricing table starts describing a business that does not
 * exist — and the honest asymmetry is a better argument anyway, because "there is no
 * subscription" is the most unusual thing about the offer.
 *
 * ── THE HONESTY THAT COSTS A CONVERSION ──────────────────────────────────────────────────
 * The free card does not say "start your free interview". `TRIAL_ALLOWANCE` gives a new
 * account one communication drill and unlimited quizzes, and zero interviews — the front door
 * is a paywall, and plans.py says so in as many words. Copy that promises a free interview
 * would be false the moment somebody pressed the button, so this promises what is actually
 * free and lets that be smaller.
 */
const FREE = [
  'One full communication round, scored',
  'Unlimited quizzes — every topic, every difficulty',
  'Your target-company study plan',
  'Resume analysis',
];

const PAID = [
  'Full mock interviews with cross-questioning',
  'Group discussion against three AI panelists',
  'The coding round, compiled and judged',
  'The complete report, shareable as a PDF',
];

export function MkPricing() {
  return (
    <section id="pricing" className="mk-band mk-section">
      <div className="mk-shell">
        <p className="mk-eyebrow">What it costs</p>

        <h2
          className="mt-5 max-w-[22ch] text-balance leading-[1.06]"
          style={{ fontSize: 'var(--mk-h2)' }}
        >
          Free where it can be. <span className="mk-turn">Paid once, where it counts.</span>
        </h2>

        <p className="mt-5 max-w-[56ch] leading-[1.65]" style={{ fontSize: 'var(--mk-lead)' }}>
          There is no subscription to argue yourself into and nothing to cancel. You buy a
          session when you want one, and what you buy never expires.
        </p>

        <div className="mt-11 grid gap-5 lg:grid-cols-2">
          <PlanCard
            name="Free"
            price="₹0"
            note="forever, no card"
            items={FREE}
            cta={{ href: '/register', label: 'Create a free account' }}
          />
          <PlanCard
            highlighted
            name="Sessions"
            price="Pay per round"
            note="never expires"
            items={PAID}
            cta={{ href: '/pricing', label: 'See what a session costs' }}
          />
        </div>
      </div>
    </section>
  );
}

function PlanCard({
  name,
  price,
  note,
  items,
  cta,
  highlighted,
}: {
  name: string;
  price: string;
  note: string;
  items: readonly string[];
  cta: { href: string; label: string };
  highlighted?: boolean;
}) {
  return (
    <div
      className="mk-card flex flex-col p-7 sm:p-8"
      style={
        highlighted
          ? { borderColor: 'var(--mk-gold-line)', boxShadow: '0 20px 50px -30px rgb(200 146 58 / 0.55)' }
          : undefined
      }
    >
      <p className="mk-eyebrow">{name}</p>

      <p className="mt-5 flex items-baseline gap-2">
        <span className="font-[family-name:var(--mk-font-display)] text-[2.25rem] leading-none text-[var(--mk-ink)]">
          {price}
        </span>
        <span className="text-[var(--mk-micro)] text-[var(--mk-muted)]">{note}</span>
      </p>

      <ul className="mt-7 flex-1 space-y-3">
        {items.map((item) => (
          <li key={item} className="flex gap-3 text-[0.9375rem] leading-[1.5] text-[var(--mk-body)]">
            <Check
              className="mt-[3px] h-[15px] w-[15px] shrink-0 text-[var(--mk-gold)]"
              strokeWidth={2.6}
            />
            {item}
          </li>
        ))}
      </ul>

      <Link
        href={cta.href}
        className={`mk-btn mt-8 w-full ${highlighted ? 'mk-btn-primary' : 'mk-btn-ghost'}`}
      >
        {cta.label}
        <ArrowRight className="mk-arrow h-4 w-4" strokeWidth={2.2} />
      </Link>
    </div>
  );
}
