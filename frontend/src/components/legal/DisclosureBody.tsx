import type { Disclosure } from '@/lib/legal/disclosure';

/**
 * Renders the disclosure. Shared by the public /privacy page and the pre-upload sheet, so the
 * two cannot say different things — which they would within a month if each wrote its own copy.
 *
 * EVERY PIECE OF CONTENT COMES FROM THE PROP. There are no vendor names, countries or
 * retention periods in this file; the backend derives them from its own configuration, and a
 * second list here would drift exactly as the hardcoded one it replaced did.
 */
export function DisclosureBody({ disclosure }: { disclosure: Disclosure | null }) {
  if (!disclosure) {
    return (
      <p className="mt-8 rounded-xl border border-border/60 p-4 text-sm text-muted-foreground">
        We could not load this right now. It is not optional reading, so please try again — or
        write to the address on the contact page and we will send it to you.
      </p>
    );
  }

  const { grievance, fiduciary } = disclosure;

  return (
    <div className="mt-8 space-y-10 text-sm">
      {disclosure.draft && (
        /*
         * SHOWN, NOT HIDDEN IN A COMMENT. This text states facts an engineer verified from the
         * code — which service, which country, what is sent. It is not a lawyer-reviewed
         * privacy policy, and presenting it as one would be the misleading part.
         */
        <p className="rounded-xl border border-accent-amber/30 bg-accent-amber-soft p-4 leading-relaxed">
          <strong className="font-semibold">Draft wording.</strong> Everything below is accurate
          about how the system actually works, and it has not yet been reviewed by a lawyer. It
          describes our practice; it is not yet our formal privacy policy.
        </p>
      )}

      {/* FIRST, BECAUSE A NOTICE SHOULD SAY WHO IS GIVING IT BEFORE IT SAYS ANYTHING ELSE.
          This page listed what is collected, who processes it, how long it is kept and what
          rights attach - without ever naming the party responsible for any of it. Under DPDP
          the notice is issued BY a Data Fiduciary, and "some unnamed company holds your
          resume" is not a disclosure a person can act on: you cannot exercise a right against
          somebody you cannot name. */}
      {/* GUARDED, BECAUSE THE TWO SIDES DEPLOY SEPARATELY. A frontend that has shipped ahead
          of the backend receives a payload without this field, and reading through it is a
          500 on a legal page. Omitting the section degrades to exactly what this page showed
          before the field existed; crashing does not. */}
      {fiduciary && (
        <section>
          <h2 className="text-base font-semibold text-foreground">Who holds your data</h2>
          <p className="mt-2 leading-relaxed text-muted-foreground">
            <strong className="text-foreground">{fiduciary.name}</strong> operates{' '}
            {fiduciary.product} and is the {fiduciary.role} for everything described below.
            Where this page says &ldquo;we&rdquo;, it means {fiduciary.name}.
          </p>
        </section>
      )}

      <section>
        <h2 className="text-base font-semibold text-foreground">Who processes your data</h2>
        {disclosure.leaves_india && (
          <p className="mt-2 leading-relaxed text-muted-foreground">
            Some of this happens <strong className="text-foreground">outside India</strong>. The
            country is named for each one below.
          </p>
        )}
        <ul className="mt-4 space-y-4">
          {disclosure.processors.map((p) => (
            <li key={p.category} className="rounded-xl border border-border/60 p-4">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="font-medium text-foreground">{p.category}</span>
                <span className="text-xs text-muted-foreground">{p.country}</span>
              </div>
              <p className="mt-2 text-muted-foreground">{p.receives}</p>
              <p className="mt-1 text-xs text-muted-foreground">{p.purpose}</p>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2 className="text-base font-semibold text-foreground">How long we keep it</h2>
        <dl className="mt-4 space-y-4">
          {disclosure.retention.map((r) => (
            <div key={r.what}>
              <dt className="font-medium text-foreground">{r.what}</dt>
              <dd className="mt-1 leading-relaxed text-muted-foreground">{r.how_long}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section>
        <h2 className="text-base font-semibold text-foreground">What you can do</h2>
        <ul className="mt-3 list-disc space-y-1 pl-5 text-muted-foreground">
          {disclosure.rights.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      </section>

      <section>
        <h2 className="text-base font-semibold text-foreground">Who to complain to</h2>
        {grievance.configured ? (
          <p className="mt-3 leading-relaxed text-muted-foreground">
            {grievance.role}: <strong className="text-foreground">{grievance.name}</strong>,{' '}
            <a href={`mailto:${grievance.email}`} className="text-primary underline">
              {grievance.email}
            </a>
            . We answer within {grievance.response_days} days.
          </p>
        ) : (
          /*
           * AN OBVIOUS GAP BEATS A PLAUSIBLE FABRICATION. A made-up name here would look like
           * the obligation had been discharged. DPO_NAME and DPO_EMAIL are unset on the
           * backend, and that is what this says.
           */
          <p className="mt-3 rounded-xl border border-accent-rose/30 p-4 leading-relaxed text-muted-foreground">
            <strong className="font-semibold text-foreground">
              No grievance officer has been appointed yet.
            </strong>{' '}
            Indian data-protection law requires a named person to answer questions and
            complaints about how your data is handled. Until one is appointed and their contact
            set on the server, this is an open gap rather than a contact we can give you.
          </p>
        )}
      </section>

      <p className="text-xs text-muted-foreground">Notice version {disclosure.notice_version}</p>
    </div>
  );
}
