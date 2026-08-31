import type { Metadata } from 'next';

/**
 * Shared reports are readable by anyone with the link, and by NO search engine.
 *
 * THE BUG THIS FIXES. `/r/<id>` is the one genuinely public, unauthenticated page in the
 * product that renders a named person's assessment — `data.candidate_name` sits in the `<h1>`
 * beside their score, their readiness level and their weakest topics. It inherited
 * `robots: { index: true, follow: true }` from the root layout, so a candidate who shared a
 * link with one placement cell would have had that assessment crawled, indexed and returned
 * for a search of their own name, indefinitely, long after the link stopped mattering to them.
 *
 * "Unlisted" and "public" are different things and the product already promises the first:
 * sharing is opt-in, revocable from the report page, and the footer states that individual
 * answers are excluded. An indexed page is not unlisted, and revoking the share does not
 * retract what a crawler already took.
 *
 * A LAYOUT RATHER THAN THE PAGE, because the page is a client component (`'use client'` for
 * `useParams`) and Next.js does not allow a client component to export `metadata`. A layout
 * for the segment is the supported way to attach it, and it covers every route under `/r`
 * including any added later — which is the more important property: this is a rule about the
 * whole segment, not about one file.
 *
 * `nocache` and the explicit googleBot block are belt and braces: `index: false` is the
 * instruction, and the rest closes the gap where a crawler honours one directive and not
 * another.
 */
export const metadata: Metadata = {
  robots: {
    index: false,
    follow: false,
    nocache: true,
    googleBot: { index: false, follow: false },
  },
};

export default function SharedReportLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
