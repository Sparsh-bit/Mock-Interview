import Link from 'next/link';

import { Brandmark } from '@/components/brand/Brandmark';
import { BRAND } from '@/lib/brand';

import { ROUNDS } from './content';

/**
 * THE PUBLIC FOOTER — components/marketing/MkFooter.tsx
 *
 * A separate component from `layout/SiteFooter`, which stays exactly as it is. SiteFooter is
 * the product's footer: mono, 11px, four legal links, and it appears at the bottom of the
 * pricing page, the legal pages and a shared report, where a four-column marketing footer
 * would be absurd. This one is the landing page's footer and it is allowed to be a site map.
 *
 * The legal column is the reason both exist rather than one. Terms, refunds, the privacy
 * notice and the grievance contact have to be reachable from every page a signed-out visitor
 * can land on — that is a compliance requirement, not a design preference — so the four links
 * are duplicated here rather than dropped. Duplicating four links is cheap; a legal page that
 * only one route links to is a legal page nobody finds.
 */
const COLUMNS = [
  {
    title: 'Rounds',
    links: ROUNDS.map((r) => ({ href: r.href, label: r.name })),
  },
  {
    title: 'Product',
    links: [
      { href: '/demo', label: 'Sample report' },
      { href: '/pricing', label: 'Pricing' },
      { href: '/register', label: 'Create an account' },
      { href: '/login', label: 'Log in' },
    ],
  },
  {
    title: 'Legal',
    links: [
      { href: '/terms', label: 'Terms' },
      { href: '/refund', label: 'Refunds' },
      { href: '/privacy', label: 'Your data' },
      { href: '/grievance', label: 'Grievance' },
    ],
  },
] as const;

export function MkFooter() {
  return (
    <footer className="border-t border-[var(--mk-border)] bg-[var(--mk-paper)]">
      <div className="mk-shell grid gap-12 py-16 lg:grid-cols-[1.4fr_repeat(3,minmax(0,1fr))]">
        <div>
          <span className="flex items-center gap-2.5">
            <Brandmark className="h-7 w-7" />
            <span className="font-[family-name:var(--mk-font-display)] text-[1.0625rem] font-medium text-[var(--mk-ink)]">
              Interview<span className="text-[var(--mk-gold)]"> OS</span>
            </span>
          </span>

          <p className="mt-4 max-w-[34ch] text-[var(--mk-small)] leading-[1.6] text-[var(--mk-muted)]">
            {BRAND.tagline}. A mock interview that pushes back, measures how you speak, and
            tells you what the panel would have said.
          </p>

          {/* A mailto and not plain text. Most of this traffic is on a phone, where plain text
              means copying an address by hand. Kept at body scale so it reads as contact
              detail rather than as a fifth call to action. */}
          <a
            href={`mailto:${BRAND.supportEmail}`}
            className="mt-5 inline-block text-[var(--mk-small)] text-[var(--mk-body)] underline decoration-[var(--mk-border)] underline-offset-4 transition-colors hover:text-[var(--mk-ink)] hover:decoration-[var(--mk-gold)]"
          >
            {BRAND.supportEmail}
          </a>
        </div>

        {COLUMNS.map((col) => (
          <nav key={col.title} aria-label={col.title}>
            <p className="mk-eyebrow">{col.title}</p>
            <ul className="mt-5 space-y-3">
              {col.links.map((link) => (
                <li key={link.href + link.label}>
                  <Link
                    href={link.href}
                    className="text-[var(--mk-small)] text-[var(--mk-body)] transition-colors hover:text-[var(--mk-ink)]"
                  >
                    {link.label}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        ))}
      </div>

      <div className="mk-shell flex flex-wrap items-center justify-between gap-4 border-t border-[var(--mk-border)] py-6 text-[var(--mk-micro)] text-[var(--mk-muted)]">
        <span>© 2026 {BRAND.name}</span>
        <span>Built end to end by one developer.</span>
      </div>
    </footer>
  );
}
