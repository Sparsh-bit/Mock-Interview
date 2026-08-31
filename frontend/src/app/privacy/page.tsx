import type { Metadata } from 'next';
import Link from 'next/link';

import { BRAND } from '@/lib/brand';
import { createServerApiClient } from '@/lib/api/server';
import type { Disclosure } from '@/lib/legal/disclosure';
import { DisclosureBody } from '@/components/legal/DisclosureBody';
import { SiteFooter } from '@/components/layout/SiteFooter';


export const metadata: Metadata = {
  title: 'Your data',
  description: `What ${BRAND.name} collects, who processes it, where, and how to get it back or delete it.`,
};

/**
 * The §5 notice, the §16 transfer disclosure, and the §8(9)–(10) contact.
 *
 * PUBLIC, AND SERVER-RENDERED FROM THE LIVE BACKEND. Both halves are deliberate:
 *
 *   Public, because §5 requires notice BEFORE processing begins, which is before there is an
 *   account to authenticate. A notice you have to sign up to read is not notice — and the
 *   register page links here, so it has to be readable by someone who has not signed up.
 *
 *   Fetched rather than written out in this file, because the processor list is derived from
 *   the backend's own configuration (services/legal/disclosure.py). A page with the vendors
 *   typed into it is correct on the day it ships and wrong the first time somebody changes
 *   AI_PROVIDER — and a notice naming the wrong country is worse than no notice, because it
 *   is a statement the reader relied on.
 *
 * If the backend is unreachable this renders the fallback rather than an error page: somebody
 * trying to find out who holds their data should not be met with a 500.
 */
export default async function PrivacyPage() {
  let disclosure: Disclosure | null = null;
  try {
    // No token: this endpoint is public by design, and this page is reachable by somebody
    // who has not signed up — which is the whole point of a notice given before processing.
    const api = createServerApiClient();
    const response = await api.get<Disclosure>('/api/v1/legal/disclosure');
    disclosure = response.data;
  } catch {
    disclosure = null;
  }

  return (
    <div className="flex min-h-dvh flex-col">
      <main className="mx-auto w-full max-w-3xl flex-1 px-5 py-14 sm:px-8">
      <Link href="/" className="text-sm text-muted-foreground hover:text-foreground">
        ← {BRAND.name}
      </Link>

      <h1 className="mt-6 text-2xl font-semibold sm:text-3xl">Your data</h1>
      <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
        What {BRAND.name} collects, who processes it, where in the world that happens, and how
        to get it back or delete it.
      </p>

      <DisclosureBody disclosure={disclosure} />
        {/* NOT A DEAD END. Somebody who has read this far is the person most likely to
            want the complaints route, and this page had no way out of it. */}
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
