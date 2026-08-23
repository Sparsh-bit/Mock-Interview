'use client';

import Link from 'next/link';
import { ArrowRight, FileText } from 'lucide-react';

import { useUserSessions } from '@/hooks/useData';

/**
 * "Your analysis is ready" — components/ReportReadyNotice.tsx
 *
 * WHO THIS IS FOR, AND ONLY THEM. A candidate who finished an interview, whose answers were
 * all recorded and analysed, and whose REPORT did not score — because the model was
 * unreachable or the scoring call ran past its budget. Their per-question analysis exists and
 * is readable; only the summary and the score are missing.
 *
 * Those people had no way to know that. The report page showed 0/100 and "Scoring could not be
 * completed", and nothing anywhere told them their answers were safe or that generating again
 * would now work. So they left, and they are the largest group in the admin marketing view.
 *
 * IT DOES NOT GENERATE ANYTHING. It is a link. Generation is a billed model call and it happens
 * when the candidate opens their report and it is genuinely absent — never because a card
 * rendered on a dashboard. That distinction is the whole reason the report page's generation
 * moved out of a query and into a mutation: React Query was re-running it whenever the data
 * went stale, which bought a report per tab switch.
 *
 * IT DISAPPEARS ON ITS OWN. Once the report scores, `overall_score` stops being zero and this
 * renders nothing. There is no dismiss button and no stored state, because there is nothing to
 * remember: the condition IS the state.
 */
export function ReportReadyNotice() {
  // Enough to cover anybody's recent history without asking for a page of it. A candidate with
  // an unscored report from a month ago is not who this is for.
  const { data: sessions } = useUserSessions(10);

  /*
   * THE TARGET CONDITION, SPELLED OUT.
   *
   *   completed          — the interview finished, so a report is possible at all.
   *   questions_asked>0  — answers exist, which is what makes the detailed analysis readable.
   *                        Without this the card would point somebody at an empty page.
   *   no real score      — null means no report row; 0 means the unscored placeholder. Both are
   *                        "not scored yet", and both are what this card is about.
   */
  const pending = (sessions ?? []).find(
    (s) =>
      s.status === 'completed' &&
      s.questions_asked > 0 &&
      (s.overall_score === null || s.overall_score === 0),
  );

  if (!pending) return null;

  return (
    <Link
      href={`/report/${pending.id}`}
      className="group flex flex-wrap items-center gap-x-4 gap-y-2 rounded-2xl border border-accent-amber/40 bg-accent-amber/[0.08] p-4 transition-colors hover:bg-accent-amber/[0.12] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:p-5"
    >
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-accent-amber/20">
        <FileText className="h-5 w-5 text-accent-amber-ink" aria-hidden />
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold text-foreground">
          Your {pending.track_name || 'interview'} answers are analysed — finish your report
        </p>
        {/* SAYS THEIR ANSWERS ARE SAFE, FIRST. That is the thing they are actually worried
            about after seeing a 0/100, and it is true: the transcript and the per-question
            analysis are stored, and only the scoring pass is missing. */}
        <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
          All {pending.questions_asked} answers are saved and your question-by-question analysis
          is ready. The scoring pass did not finish last time — open it to complete your report.
        </p>
      </div>
      <span className="inline-flex shrink-0 items-center gap-1.5 text-sm font-semibold text-accent-amber-ink">
        Open report
        <ArrowRight
          className="h-4 w-4 transition-transform group-hover:translate-x-0.5"
          aria-hidden
        />
      </span>
    </Link>
  );
}

export default ReportReadyNotice;
