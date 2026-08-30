import type { Policy } from '@/lib/legal/policies';

/**
 * One policy, rendered — components/legal/PolicyBody.tsx
 *
 * PLAIN TEXT, DELIBERATELY. The sections are strings and are rendered as text nodes, so
 * there is no markup path through this component at all. React's raw-HTML escape hatch
 * appears nowhere in this codebase — `test_pentest_surface.py` greps for it — and a policy
 * renderer would be a poor place to introduce the first one.
 *
 * THE DRAFT BANNER IS NOT OPTIONAL. It is driven by `policy.draft`, which is typed as the
 * literal `true` — so a policy cannot be written that renders without it until somebody
 * changes the type, which is the point at which a lawyer has actually adopted the wording.
 */
export function PolicyBody({ policy }: { policy: Policy }) {
  return (
    <div className="mt-8 space-y-10 text-sm">
      {policy.draft && (
        <p className="rounded-xl border border-accent-amber/30 bg-accent-amber-soft p-4 leading-relaxed">
          <strong className="font-semibold">Draft wording.</strong> This describes how the
          service actually works and has not yet been reviewed by a lawyer. It is our stated
          practice; it is not yet a formal legal instrument.
        </p>
      )}

      {policy.sections.map((section) => (
        <section key={section.heading}>
          <h2 className="text-base font-semibold text-foreground">{section.heading}</h2>
          {section.body.map((paragraph) => (
            <p key={paragraph} className="mt-2 leading-relaxed text-muted-foreground">
              {paragraph}
            </p>
          ))}
        </section>
      ))}

      {policy.needsLegalReview.length > 0 && (
        /*
         * SHOWN RATHER THAN FILED. The DPDP work established that an obvious gap beats a
         * plausible fabrication, because a polished document reads as though the obligation
         * was discharged. Listing the open questions in public is the honest version of the
         * draft banner: it says exactly which parts are not settled.
         */
        <section className="rounded-xl border border-border bg-muted/30 p-4">
          <h2 className="text-base font-semibold text-foreground">
            Still to be settled with a lawyer
          </h2>
          <ul className="mt-2 list-disc space-y-1 pl-5 leading-relaxed text-muted-foreground">
            {policy.needsLegalReview.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
      )}

      <p className="text-xs text-muted-foreground">Last updated {policy.updated}.</p>
    </div>
  );
}

export default PolicyBody;
