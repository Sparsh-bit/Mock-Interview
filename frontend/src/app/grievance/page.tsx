import type { Metadata } from 'next';
import Link from 'next/link';

import { SiteFooter } from '@/components/layout/SiteFooter';
import { createServerApiClient } from '@/lib/api/server';
import { BRAND } from '@/lib/brand';
import type { Disclosure } from '@/lib/legal/disclosure';
import { RESPONSE_WINDOW_DAYS } from '@/lib/legal/policies';


export const metadata: Metadata = {
  title: 'Complaints and grievances',
  description: 'Who to contact if something has gone wrong, and what happens when you do.',
};

/**
 * The single point of contact — app/grievance/page.tsx
 *
 * ONE CONTACT, NOT TWO, AND THAT IS THE WHOLE DESIGN OF THIS PAGE.
 *
 * DPDP §8(9)–(10) requires a published grievance-redressal contact, and `/privacy` already
 * publishes one from `DPO_NAME` / `DPO_EMAIL`. Publishing a *second* address here for
 * refunds and service complaints would be worse than publishing none: a person picks one,
 * writes to the wrong inbox, hears nothing, and concludes the company ignores complaints.
 *
 * So this fetches the same `/api/v1/legal/disclosure` payload that `/privacy` renders. There
 * is one source — the backend's settings — and these two pages cannot disagree, because
 * neither of them holds a copy.
 *
 * IT SAYS "NOT APPOINTED" WHEN NOBODY IS. `DPO_NAME` and `DPO_EMAIL` are unset in this
 * deployment, and the honest rendering of that is to say so. `docs/COMPLIANCE.md` records
 * why: an obvious gap beats a plausible fabrication, because a made-up name makes it look
 * like the obligation was discharged. This is the single largest blocker on that document's
 * list, and this page is where it becomes visible.
 */
export default async function GrievancePage() {
  let disclosure: Disclosure | null = null;
  try {
    // No token: public by design, and somebody with a complaint may well be locked out of
    // their account — which is one of the things they might be complaining about.
    const api = createServerApiClient();
    const response = await api.get<Disclosure>('/api/v1/legal/disclosure');
    disclosure = response.data;
  } catch {
    disclosure = null;
  }

  const grievance = disclosure?.grievance ?? null;

  return (
    <div className="flex min-h-dvh flex-col">
      <main className="mx-auto w-full max-w-3xl flex-1 px-5 py-14 sm:px-8">
        <Link href="/" className="text-sm text-muted-foreground hover:text-foreground">
          ← {BRAND.name}
        </Link>
        <h1 className="mt-6 text-2xl font-semibold tracking-tight">Complaints and grievances</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          One contact for everything: your data, a payment, a score you think is wrong, or
          anything else that has gone wrong.
        </p>

        <div className="mt-8 space-y-10 text-sm">
          <section>
            <h2 className="text-base font-semibold text-foreground">Who to write to</h2>
            {grievance?.configured ? (
              <p className="mt-2 leading-relaxed text-muted-foreground">
                {grievance.role}:{' '}
                <strong className="text-foreground">{grievance.name}</strong>,{' '}
                <a href={`mailto:${grievance.email}`} className="text-primary underline">
                  {grievance.email}
                </a>
                . We answer within {grievance.response_days} days.
              </p>
            ) : (
              <p className="mt-2 rounded-xl border border-accent-amber/30 bg-accent-amber-soft p-4 leading-relaxed">
                <strong className="font-semibold">No grievance officer has been appointed
                yet.</strong>{' '}
                That is a gap, not an oversight in this page — the Digital Personal Data
                Protection Act requires a named contact and one has not been set for this
                deployment. Until it is, use the address in the footer below and we will
                route it. We would rather tell you this than print a name that does not
                answer.
              </p>
            )}
          </section>

          <section>
            <h2 className="text-base font-semibold text-foreground">What to include</h2>
            <p className="mt-2 leading-relaxed text-muted-foreground">
              The email address on your account, and roughly what happened and when. If it is
              about a payment, roughly when you paid is enough — you do not need an order
              number or a receipt. If it is about a report, a link to it or the date of the
              session is enough.
            </p>
          </section>

          <section>
            <h2 className="text-base font-semibold text-foreground">What happens next</h2>
            <p className="mt-2 leading-relaxed text-muted-foreground">
              We acknowledge your complaint and tell you the outcome within{' '}
              {grievance?.response_days ?? RESPONSE_WINDOW_DAYS} days. If we need longer we
              will say so and why, rather than going quiet.
            </p>
            <p className="mt-2 leading-relaxed text-muted-foreground">
              If your complaint is about a score or written feedback, it goes to a person who
              reads the session and the report. A review can correct the report, explain why
              the score stands, or credit the session back — it will not be closed silently.
            </p>
          </section>

          <section>
            <h2 className="text-base font-semibold text-foreground">If you are not satisfied</h2>
            <p className="mt-2 leading-relaxed text-muted-foreground">
              For a complaint about how your personal data has been handled, you may escalate
              to the Data Protection Board of India after raising it with us first.
            </p>
          </section>
        </div>

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
