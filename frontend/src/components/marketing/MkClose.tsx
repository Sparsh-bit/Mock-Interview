import Link from 'next/link';
import { ArrowRight } from 'lucide-react';

import { BRAND } from '@/lib/brand';

/**
 * THE CLOSE — components/marketing/MkClose.tsx
 *
 * The second and last dark band on the page, and the only place the gold button appears at
 * full size. It is dark for a structural reason rather than a decorative one: the film
 * established that dark means "this is the product doing something", so returning to dark at
 * the end frames the ask as the same subject rather than as a new one. A cream CTA after a
 * cream pricing section is a fourth cream band and reads as the page running out.
 *
 * `data-nav-dark` flips the floating nav here too, which means the last thing a visitor sees
 * at the bottom of the page is a gold "Start free" in the nav and a gold "Start a mock
 * interview" in the band — the same action, twice, in the same colour. That is the one place
 * on the site where repeating a CTA is not clutter.
 */
export function MkClose() {
  return (
    <section
      data-nav-dark
      className="mk-on-dark relative overflow-hidden bg-[linear-gradient(180deg,var(--mk-dark-top)_0%,var(--mk-dark-warm)_100%)]"
    >
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            'radial-gradient(58% 62% at 50% 108%, rgb(200 146 58 / 0.22), transparent 70%)',
        }}
      />

      <div className="mk-shell relative flex flex-col items-center py-24 text-center sm:py-32">
        <h2
          className="max-w-[18ch] text-balance leading-[1.04]"
          style={{ fontSize: 'var(--mk-final)' }}
        >
          Sit in it <span className="mk-turn">before it counts.</span>
        </h2>

        <p className="mt-6 max-w-[52ch] text-pretty leading-[1.65] text-[var(--mk-on-dark-muted)]">
          {BRAND.promise}
        </p>

        <div className="mt-9 flex flex-col items-center gap-4 sm:flex-row">
          <Link href="/register" className="mk-btn mk-btn-gold">
            Start a mock interview
            <ArrowRight className="mk-arrow h-4 w-4" strokeWidth={2.2} />
          </Link>
          <span className="mk-num text-[var(--mk-micro)] text-[var(--mk-on-dark-muted)]">
            Free to start · no card
          </span>
        </div>
      </div>
    </section>
  );
}
