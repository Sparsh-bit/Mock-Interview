'use client';

import Link from 'next/link';
import { AlertTriangle, FileText, Headphones, Volume2, Wifi } from 'lucide-react';

import { usePrimaryResume, useUserProfile } from '@/hooks/useData';

/**
 * What to sort out before the interview starts — InterviewReadiness.tsx
 *
 * Two different jobs on one card, and the split matters:
 *
 *   THINGS THAT WILL GO WRONG IN THE ROOM. A noisy background, a phone held at arm's length,
 *   speakers instead of headphones. None of these are faults in the product and none can be
 *   detected reliably, but every one of them produces a transcript full of holes and a score
 *   the candidate will not recognise as their own. The single highest-value thing this screen
 *   can do is say them out loud before the mic opens, because afterwards the interview is
 *   already spent — they get one attempt.
 *
 *   THINGS THAT ARE ACTUALLY MISSING. No resume, no name. These are checked rather than
 *   guessed at, and they are shown as WARNINGS rather than blocks: the interview works without
 *   either, just less well — an interviewer with no resume asks generic questions instead of
 *   asking about your projects by name. Blocking here would be worse than the shortfall it
 *   prevents.
 *
 * WHY THE TIPS ARE NOT A DISMISSIBLE BANNER. They are read once, immediately before starting,
 * on the screen where acting on them costs ten seconds. A banner that can be dismissed is
 * dismissed by the same people who most need it, and one that persists after the interview is
 * noise. Placed at the decision point, it needs no state at all.
 *
 * IT DOES NOT BLOCK, EVER. There is no gate here and no disabled button — the candidate
 * decides. Somebody sitting in a shared room ten minutes before a real drive does not need the
 * product refusing to let them practise.
 */
export function InterviewReadiness() {
  const { data: resume } = usePrimaryResume();
  const { data: profile } = useUserProfile();

  // Undefined while loading. Treated as "no warning yet" rather than as missing, so the card
  // does not flash a "you have no resume" warning at somebody who has one — which would teach
  // them the warnings are unreliable and worth ignoring.
  const resumeMissing = resume === null || (resume !== undefined && !resume.has_text);
  const nameMissing = profile !== undefined && !profile?.full_name?.trim();

  const gaps: Array<{ text: string; href: string; cta: string }> = [];
  if (resumeMissing) {
    gaps.push({
      text:
        'No resume on file — the interviewer will ask general questions instead of asking ' +
        'about your own projects by name.',
      href: '/profile',
      cta: 'Upload your resume',
    });
  }
  if (nameMissing) {
    gaps.push({
      text: 'Your name is not set, so the panel cannot greet you by it.',
      href: '/profile',
      cta: 'Add your name',
    });
  }

  return (
    <div className="rounded-2xl border border-border/70 bg-surface/40 p-4 sm:p-5">
      <p className="text-sm font-semibold text-foreground">Before you start</p>

      {/* THE ROOM. Ordered by how much damage each one does to the transcript: background
          noise ruins whole answers, mic distance clips the ends of sentences, speakers cause
          the panel's own voice to be transcribed back as if the candidate said it. */}
      <ul className="mt-3 space-y-2">
        {[
          {
            Icon: Volume2,
            text:
              'Find a quiet room. Background voices get transcribed into your answer and cost ' +
              'you marks you did earn.',
          },
          {
            Icon: Headphones,
            text:
              'Use headphones if you have them. On speakers, the interviewer’s voice can ' +
              'be picked up as if it were yours.',
          },
          {
            Icon: Wifi,
            text:
              'Stay close to the mic and on a steady connection — speak normally, at your ' +
              'usual pace.',
          },
        ].map(({ Icon, text }) => (
          <li key={text} className="flex items-start gap-2.5 text-xs leading-relaxed text-muted-foreground">
            <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" aria-hidden />
            <span>{text}</span>
          </li>
        ))}
      </ul>

      {/* WHAT IS MISSING, only when something is. An empty section here would be a checklist
          of ticks, which reads as ceremony; the absence of warnings is the message. */}
      {gaps.length > 0 && (
        <div className="mt-4 space-y-2 border-t border-border/60 pt-3">
          {gaps.map((gap) => (
            <div
              key={gap.cta}
              className="flex flex-wrap items-start gap-2 rounded-lg border border-accent-amber/40 bg-accent-amber/10 px-3 py-2"
            >
              <AlertTriangle
                className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent-amber-ink"
                aria-hidden
              />
              <p className="min-w-0 flex-1 text-xs leading-relaxed text-accent-amber-ink">
                {gap.text}
              </p>
              {/* A ROUTE TO FIXING IT, not just the news. A warning with no action is a
                  complaint, and the candidate is one screen away from resolving this. */}
              <Link
                href={gap.href}
                className="inline-flex shrink-0 items-center gap-1 text-xs font-semibold text-accent-amber-ink underline decoration-accent-amber/50 underline-offset-2 hover:decoration-accent-amber"
              >
                <FileText className="h-3 w-3" aria-hidden />
                {gap.cta}
              </Link>
            </div>
          ))}
          <p className="text-[11px] text-muted-foreground">
            You can start without these — the interview will simply be less tailored to you.
          </p>
        </div>
      )}
    </div>
  );
}

export default InterviewReadiness;
