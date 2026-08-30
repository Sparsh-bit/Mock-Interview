import type { Metadata } from 'next';
import Link from 'next/link';

import { PolicyBody } from '@/components/legal/PolicyBody';
import { SiteFooter } from '@/components/layout/SiteFooter';
import { BRAND } from '@/lib/brand';
import { REFUND } from '@/lib/legal/policies';

export const runtime = 'edge';

export const metadata: Metadata = {
  title: REFUND.title,
  description: REFUND.summary,
};

/**
 * PUBLIC AND STATIC. Unlike /privacy this needs nothing from the backend — the wording is
 * the same for every deployment, and the one value that is deployment-specific (the
 * grievance contact) deliberately lives on /grievance so there is one page to keep correct
 * rather than three copies to keep in step.
 */
export default function REFUNDPage() {
  return (
    <div className="flex min-h-dvh flex-col">
      <main className="mx-auto w-full max-w-3xl flex-1 px-5 py-14 sm:px-8">
        <Link href="/" className="text-sm text-muted-foreground hover:text-foreground">
          ← {BRAND.name}
        </Link>
        <h1 className="mt-6 text-2xl font-semibold tracking-tight">{REFUND.title}</h1>
        <p className="mt-2 text-sm text-muted-foreground">{REFUND.summary}</p>

        <PolicyBody policy={REFUND} />

        <nav className="mt-12 flex flex-wrap gap-x-6 gap-y-2 border-t border-border pt-6 text-sm">
          <Link href="/terms" className="text-muted-foreground hover:text-foreground">Terms</Link>
          <Link href="/refund" className="text-muted-foreground hover:text-foreground">Refunds</Link>
          <Link href="/privacy" className="text-muted-foreground hover:text-foreground">Your data</Link>
          <Link href="/grievance" className="text-muted-foreground hover:text-foreground">Grievance</Link>
        </nav>
      </main>
      <SiteFooter />
    </div>
  );
}
