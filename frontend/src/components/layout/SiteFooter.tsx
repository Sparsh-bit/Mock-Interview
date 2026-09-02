import Link from 'next/link';

import { BRAND } from '@/lib/brand';

/**
 * The public footer — components/layout/SiteFooter.tsx
 *
 * EXTRACTED FROM THE LANDING PAGE because it now carries the legal links, and a legal page
 * that only one route links to is a legal page most people never find. Terms, refunds,
 * privacy and the grievance contact have to be reachable from every page a signed-out
 * visitor can land on, which means the footer has to be a component rather than markup
 * inside `app/page.tsx`.
 *
 * The signed-in half is handled separately: somebody who is already paying lives inside the
 * dashboard and never scrolls past a marketing page again, so Settings links the same four.
 */
/**
 * THE FOUR LEGAL LINKS, AND THE ONLY DECLARATION OF THEM.
 *
 * Exported because there are now two footers: this one (the product's, on /pricing and the
 * legal pages) and `components/marketing/MkFooter` (the public site's, on the landing page).
 * Both have to carry all four, and `legal-pages.test.ts` checks the list against THIS file —
 * so a second footer with its own copy would be a set of legal links nothing verifies. It
 * would also be the exact shape of the bug this file was extracted to fix, one level up:
 * a legal page reachable from one footer and not the other.
 *
 * Add a route here and both footers get it.
 */
export const LEGAL_LINKS = [
  { href: '/terms', label: 'Terms' },
  { href: '/refund', label: 'Refunds' },
  { href: '/privacy', label: 'Your data' },
  { href: '/grievance', label: 'Grievance' },
] as const;

export function SiteFooter() {
  return (
    <footer className="border-t border-border">
      <div className="mx-auto flex max-w-6xl flex-col gap-6 px-6 py-8 font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground sm:px-10">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <span className="flex items-center gap-2">
            {/* THE FOOTER IS NOT THE LIT ELEMENT. docs/DESIGN-LANGUAGE.md allows one per
                page and it belongs to the content above; this dot is a marker, at the
                footer's own muted weight, not a second focal point. */}
            <span className="h-1.5 w-1.5 rounded-full bg-accent-indigo" />
            {BRAND.name}
          </span>
          {/* A real address, and a mailto rather than plain text — on a phone, which is where
              most of this traffic lands, plain text means copying an email by hand. Kept in
              the footer's own type scale so it reads as contact detail rather than a CTA
              competing with the buttons above. `normal-case` because an email address in
              uppercase is not the same address. */}
          <a
            href="mailto:sparsh42005@gmail.com"
            className="normal-case tracking-normal transition-colors hover:text-foreground"
          >
            sparsh42005@gmail.com
          </a>
          <span>© 2026</span>
        </div>

        <nav
          aria-label="Legal"
          className="flex flex-wrap items-center gap-x-6 gap-y-2 border-t border-border/40 pt-5"
        >
          {LEGAL_LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="transition-colors hover:text-foreground"
            >
              {link.label}
            </Link>
          ))}
        </nav>
      </div>
    </footer>
  );
}

export default SiteFooter;
