'use client';

import { useRef } from 'react';
import Link from 'next/link';
import { motion, useInView, useReducedMotion } from 'framer-motion';
import { ArrowRight } from 'lucide-react';

import {
  AI_SURFACE_COUNT,
  COMPANY_COUNT,
  QUESTION_COUNT,
  SUBTOPIC_COUNT,
  TRACK_COUNT,
  WEIGHTINGS,
} from './content';

/**
 * WHAT IT MEASURES — components/marketing/MkProof.tsx
 *
 * The section that has to survive somebody deciding to check.
 *
 * ── THE ARGUMENT ─────────────────────────────────────────────────────────────────────────
 * Two recruiters, two completely different papers. Amazon spends 45% of its assessment on
 * algorithms; TCS spends 25% on aptitude and reasoning and does not test algorithms at that
 * depth at all. A candidate who "prepared for placements" in the abstract has, necessarily,
 * mis-prepared for one of them. That is the case for a product that knows which company you
 * are sitting for, and it is made better by two bar charts than by any adjective.
 *
 * ── AND THEN THE NUMBERS ─────────────────────────────────────────────────────────────────
 * Four figures, all counted from the repository, none rounded. DESIGN-RULES bans "50+" and
 * "1000+" and it is right to: a rounded-up number is the one thing on a landing page that a
 * visitor can catch you on for free, and 24 is a more persuasive figure than 50+ precisely
 * because nobody would choose it if they were making it up.
 *
 * The bars grow on entry rather than arriving at their width. A bar already at 45% states a
 * fact; a bar travelling to 45% shows the measurement being taken, and the measurement is
 * what is being sold.
 */

const COUNTED = [
  { n: TRACK_COUNT, label: 'interview tracks', sub: `across ${COMPANY_COUNT} campus recruiters` },
  { n: QUESTION_COUNT, label: 'real questions', sub: 'from previous-year papers, researched' },
  { n: SUBTOPIC_COUNT, label: 'study subtopics', sub: 'each with a video and a reference' },
  { n: AI_SURFACE_COUNT, label: 'AI surfaces', sub: 'from the interviewer to the evaluator' },
];

export function MkProof() {
  const ref = useRef<HTMLDivElement | null>(null);
  const reduced = useReducedMotion();
  /* `once` so a bar never re-animates on the way back up. A chart that redraws every time it
     crosses the fold is the page fidgeting. */
  const inView = useInView(ref, { once: true, margin: '-18%' });

  return (
    <section id="proof" className="mk-band mk-section">
      <div className="mk-shell">
        <p className="mk-eyebrow">Weighted by what they actually test</p>

        <div className="mt-7 grid gap-x-16 gap-y-12 lg:grid-cols-[1.05fr_0.95fr]">
          <div>
            <h2
              className="max-w-[24ch] text-balance leading-[1.08]"
              style={{ fontSize: 'var(--mk-h2)' }}
            >
              Amazon gives algorithms 45% of the paper. TCS gives aptitude 25%.{' '}
              <span className="mk-turn">Your plan should know the difference.</span>
            </h2>

            <p className="mt-6 max-w-[48ch] leading-[1.65]" style={{ fontSize: 'var(--mk-lead)' }}>
              Pick your target and get a dated plan: {SUBTOPIC_COUNT} subtopics, each with
              something to read, somewhere to practise, and a quiz to check you actually know
              it. Tick one off and the plan remembers.
            </p>

            <Link href="/register" className="mk-btn mk-btn-primary mt-8">
              Build my plan
              <ArrowRight className="mk-arrow h-4 w-4" strokeWidth={2.2} />
            </Link>
          </div>

          <div ref={ref} className="grid gap-8 sm:grid-cols-2 lg:gap-6 lg:pt-2">
            {WEIGHTINGS.map((w) => (
              <div key={w.company}>
                <p className="font-[family-name:var(--mk-font-display)] text-[1.125rem] text-[var(--mk-ink)]">
                  {w.company}
                </p>
                <ul className="mt-4 space-y-4">
                  {w.rows.map((row, i) => (
                    <li key={row.label}>
                      <div className="flex items-baseline justify-between gap-3">
                        <span className="text-[0.8125rem] text-[var(--mk-body)]">
                          {row.label}
                        </span>
                        <span className="mk-num text-[0.8125rem] text-[var(--mk-ink)]">
                          {row.pct}%
                        </span>
                      </div>
                      <div className="mt-1.5 h-[3px] w-full rounded-full bg-[rgb(59_43_28/0.1)]">
                        <motion.span
                          /* `--mk-gold-graphic`, not `--mk-gold`. This bar IS the fact — its length is
                             the 45%, and there is no text alternative beside it — so it has to
                             clear 3:1 against the band it sits on. Bare gold measures 2.6:1 and
                             cannot; the graphic tone is the same hue darkened until it does. */
                          className="block h-full origin-left rounded-full bg-[var(--mk-gold-graphic)]"
                          style={{ width: `${row.pct}%` }}
                          initial={reduced ? false : { scaleX: 0 }}
                          animate={inView || reduced ? { scaleX: 1 } : undefined}
                          transition={{
                            duration: 0.85,
                            delay: 0.1 + i * 0.12,
                            ease: [0.22, 1, 0.36, 1],
                          }}
                        />
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>

        {/* THE COUNTED FIGURES. Set in mono at display size, on a hairline, with the label
            underneath — the same treatment the report gives a score, because it is the same
            kind of claim and it should look like it. */}
        <dl className="mt-16 grid gap-y-9 border-t border-[var(--mk-border)] pt-10 sm:grid-cols-2 lg:grid-cols-4">
          {COUNTED.map((c) => (
            <div key={c.label}>
              <dt className="mk-num text-[2.75rem] leading-none text-[var(--mk-ink)]">{c.n}</dt>
              <dd className="mt-2">
                <span className="block text-[0.9375rem] font-medium text-[var(--mk-ink)]">
                  {c.label}
                </span>
                <span className="mt-0.5 block text-[var(--mk-micro)] text-[var(--mk-muted)]">
                  {c.sub}
                </span>
              </dd>
            </div>
          ))}
        </dl>

        <p className="mt-8 max-w-[62ch] text-[var(--mk-micro)] leading-[1.6] text-[var(--mk-muted)]">
          Every one of those is counted from the code rather than rounded up. This page used to
          say &ldquo;50+ company tracks&rdquo; and &ldquo;2,000+ question bank&rdquo;; both
          were rounded up until somebody counted. If we will not round up our own numbers, you
          can trust the ones on your report.
        </p>
      </div>
    </section>
  );
}
