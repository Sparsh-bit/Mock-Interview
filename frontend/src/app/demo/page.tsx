'use client';

export const runtime = 'edge';

import Link from 'next/link';
import { ArrowLeft, Calendar, FileText, TrendingUp } from 'lucide-react';

import { SiteFooter } from '@/components/layout/SiteFooter';
import { formatDate } from '@/lib/format-date';
import { scoreBand } from '@/lib/score-bands';
import { cn } from '@/lib/utils';

export default function DemoReportPage() {
  const sampleReport = {
    session_name: 'Cognizant GenC — Java FSE',
    company: 'Cognizant',
    program: 'GenC',
    overall_score: 78,
    status: 'completed',
    started_at: '2026-07-20T14:30:00Z',
    readiness_level: 'Ready with practice',
    questions_asked: 6,
    topics: ['Java Collections', 'Spring Boot', 'SQL', 'HR Round', 'Problem Solving'],
  };

  const answers = [
    {
      q: "Tell me about yourself and walk me through the project you're most proud of.",
      a: "I'm a final-year Computer Science student. My most proud project was a Spring Boot inventory management system where I designed the REST API and integrated it with PostgreSQL. I handled 50,000+ records and optimized queries to reduce latency by 40%. The system is used by 5 small retailers locally.",
      keywords: ['Spring Boot', 'REST API', 'PostgreSQL', 'optimization'],
      clarity_score: 8.2,
      confidence_score: 8.5,
    },
    {
      q: "Explain Java Collections and when you'd use a HashMap vs LinkedHashMap.",
      a: "Collections are interfaces and classes in java.util for storing groups of objects. HashMap is a hash table that provides O(1) average lookup but doesn't maintain insertion order. LinkedHashMap maintains insertion order by using a doubly linked list. I'd use HashMap for caches where order doesn't matter and LinkedHashMap when I need to preserve insertion order like in LRU caches.",
      keywords: ['HashMap', 'LinkedHashMap', 'O(1)', 'insertion order'],
      clarity_score: 8.8,
      confidence_score: 8.0,
    },
    {
      q: 'Tell me about the Spring Framework and key annotations you use.',
      a: 'Spring is a lightweight framework that provides dependency injection and simplifies enterprise Java development. Key annotations I use: @SpringBootApplication for the entry point, @RestController for REST endpoints, @Service for business logic, @Autowired for dependency injection, @GetMapping/@PostMapping for HTTP methods. Spring Boot auto-configures most of the setup so we focus on writing business logic.',
      keywords: ['Spring', 'DI', '@RestController', '@Service'],
      clarity_score: 8.5,
      confidence_score: 7.8,
    },
  ];

  const scoreBreakdown = [
    { label: 'Technical Depth', value: 7.8 },
    { label: 'Communication', value: 8.3 },
    { label: 'Problem Solving', value: 7.5 },
    { label: 'Confidence', value: 8.1 },
  ];

  const strengths = [
    'Clear explanations with concrete examples from real projects',
    'Good command of Java fundamentals and Spring ecosystem',
    'Demonstrates hands-on experience with databases and optimization',
  ];

  const improvements = [
    'Dive deeper into Spring Boot internals (bean lifecycle, auto-configuration mechanics)',
    'Practice designing distributed systems and handling edge cases',
    'Prepare specific metrics and trade-off discussions for architectural decisions',
  ];

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <div className="border-b border-border/50 bg-surface/50 py-6">
        <div className="mx-auto max-w-5xl px-6">
          <Link
            href="/"
            className="mb-6 inline-flex items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to home
          </Link>
          <div className="space-y-2">
            {/* The same coloured rule PageHeader draws before every eyebrow in the app. */}
            <p className="flex items-center gap-2 font-mono text-[11px] font-medium uppercase tracking-[0.18em] text-accent-teal-ink">
              <span aria-hidden className="h-px w-3.5 shrink-0 bg-accent-teal" />
              Sample report
            </p>
            {/* The display face, matching `PageHeader` — which every other page in the product
                uses and this one hand-rolls, because it predates it. The section headings
                below stay in Inter: a serif at 20px inside a card reads as a pull quote, and
                the rule is that the display face is for the LARGEST thing on a surface, not
                for anything that happens to be a heading. */}
            <h1 className="font-display text-3xl font-[480] tracking-[-0.022em]">
              {sampleReport.session_name}
            </h1>
            <div className="flex items-center gap-4 text-sm text-muted-foreground">
              <span className="flex items-center gap-1">
                <Calendar className="h-3.5 w-3.5" />
                {formatDate(sampleReport.started_at)}
              </span>
              <span>•</span>
              <span>{sampleReport.questions_asked} questions asked</span>
              <span>•</span>
              <span
                className={`rounded-full px-2 py-1 text-xs font-semibold ${
                  sampleReport.status === 'completed'
                    ? 'bg-accent-emerald/10 text-accent-emerald-ink'
                    : 'bg-accent-amber/10 text-accent-amber-ink'
                }`}
              >
                {sampleReport.status}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="mx-auto max-w-5xl space-y-8 px-6 py-12">
        {/* Overall Score Card */}
        {/* THE LIT ELEMENT — docs/DESIGN-LANGUAGE §1. This page is linked from the landing
            page, so for a lot of people it is the first real thing they see the product
            produce. The score is what they came to look at; the transcript below is evidence
            for it. It was one of several identical glass panels, which DESIGN-RULES names as
            a tell: one glass surface is a choice, six is a preset. */}
        <div className="lit rounded-2xl p-8">
          <div className="grid gap-8 sm:grid-cols-3">
            <div>
              <p className="text-sm font-medium text-muted-foreground">Overall Readiness</p>
              {/* Banded and monospaced, like every other score in the product. `text-primary`
                  meant this sample would have looked identical at 34 and at 88 — on the page
                  we use to show somebody what a report looks like. */}
              <p
                className={cn(
                  'mt-2 font-mono text-4xl font-bold tabular-nums tracking-[-0.03em]',
                  scoreBand(sampleReport.overall_score).ink,
                )}
              >
                {sampleReport.overall_score}
                <span className="text-lg font-medium text-muted-foreground">/100</span>
              </p>
              <p className="mt-1 text-sm text-muted-foreground">{sampleReport.readiness_level}</p>
            </div>
            <div>
              <p className="text-sm font-medium text-muted-foreground">Topics Covered</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {sampleReport.topics.slice(0, 3).map((t) => (
                  <span key={t} className="rounded-full border border-border bg-surface px-2.5 py-1 text-xs font-medium">
                    {t}
                  </span>
                ))}
                {sampleReport.topics.length > 3 && (
                  <span className="rounded-full border border-border bg-surface px-2.5 py-1 text-xs font-medium text-muted-foreground">
                    +{sampleReport.topics.length - 3} more
                  </span>
                )}
              </div>
            </div>
            <div>
              <p className="text-sm font-medium text-muted-foreground">Score Breakdown</p>
              <div className="mt-3 space-y-2">
                {scoreBreakdown.slice(0, 2).map(({ label, value }) => (
                  <div key={label} className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">{label}</span>
                    <span className="font-semibold">{value.toFixed(1)}/10</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Detailed Scores */}
        <div>
          <h2 className="mb-4 text-xl font-semibold">Performance Breakdown</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            {scoreBreakdown.map(({ label, value }) => {
              /*
               * BANDED, NOT GRADIENT-FILLED — the same treatment the real report and the group
               * discussion use, from lib/score-bands.
               *
               * These bars were `from-primary to-accent-violet`: two hues blended across an 8px
               * strip. Apply DESIGN-RULES' own test — if this were greyscale, would information
               * be lost? No, because the WIDTH already says the value. The gradient was
               * decoration, and worse, it made a 7.5 and an 8.3 exactly the same colour on the
               * page we use to show a prospective candidate what a report looks like.
               *
               * ×10 because these are the 0–10 sub-scores; lib/score-bands works in 0–100, and
               * they are the same scale printed at different precisions.
               */
              const band = scoreBand(value * 10);
              return (
                <div key={label} className="rounded-xl border border-border bg-surface-elevated p-4">
                  <p className="text-sm font-medium text-muted-foreground">{label}</p>
                  <div className="mt-3 flex items-center gap-3">
                    <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
                      <div
                        className={cn('h-full rounded-full transition-[width]', band.bar)}
                        style={{ width: `${(value / 10) * 100}%` }}
                      />
                    </div>
                    <span className={cn('font-mono font-bold tabular-nums', band.ink)}>
                      {value.toFixed(1)}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Q&A with Scores */}
        <div>
          <h2 className="mb-4 text-xl font-semibold">Question-by-Question Review</h2>
          <div className="space-y-4">
            {answers.map((item, idx) => (
              <div key={idx} className="rounded-xl border border-border bg-surface-elevated p-6">
                <div className="mb-4 flex items-start justify-between">
                  <h3 className="text-sm font-semibold">Q{idx + 1}: {item.q}</h3>
                  <div className="flex gap-3 text-right">
                    <div>
                      <p className="text-xs text-muted-foreground">Clarity</p>
                      <p className="font-semibold">{item.clarity_score.toFixed(1)}/10</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">Confidence</p>
                      <p className="font-semibold">{item.confidence_score.toFixed(1)}/10</p>
                    </div>
                  </div>
                </div>
                <p className="mb-3 text-sm leading-relaxed text-foreground/85">{item.a}</p>
                <div>
                  <p className="mb-2 text-xs font-medium text-muted-foreground uppercase">Key Keywords Used</p>
                  <div className="flex flex-wrap gap-1.5">
                    {item.keywords.map((k) => (
                      <span
                        key={k}
                        className="rounded-full bg-accent-indigo-soft px-2 py-1 text-xs text-accent-indigo-ink"
                      >
                        {k}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Strengths & Improvements */}
        <div className="grid gap-6 sm:grid-cols-2">
          <div className="rounded-xl border border-accent-emerald/25 bg-accent-emerald-soft/50 p-6">
            <h3 className="mb-4 font-semibold text-accent-emerald-ink">Strengths</h3>
            <ul className="space-y-2">
              {strengths.map((s, i) => (
                <li key={i} className="flex gap-3 text-sm">
                  <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-accent-emerald" />
                  <span className="text-foreground/80">{s}</span>
                </li>
              ))}
            </ul>
          </div>

          <div className="rounded-xl border border-accent-amber/25 bg-accent-amber-soft/50 p-6">
            <h3 className="mb-4 font-semibold text-accent-amber-ink">To Improve</h3>
            <ul className="space-y-2">
              {improvements.map((im, i) => (
                <li key={i} className="flex gap-3 text-sm">
                  <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-accent-amber" />
                  <span className="text-foreground/80">{im}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>

        {/* CTA */}
        <div className="rounded-xl border border-primary/20 bg-primary/5 p-8 text-center">
          <h3 className="text-lg font-semibold">Ready to practice?</h3>
          <p className="mt-2 text-sm text-muted-foreground">
            This is what your report will look like after an interview. Get personalized feedback, topic breakdowns, and a readiness assessment.
          </p>
          <Link
            href="/register"
            className="mt-6 inline-flex items-center gap-2 rounded-lg bg-primary px-6 py-3 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90"
          >
            <FileText className="h-4 w-4" />
            Start Your Mock Interview
          </Link>
        </div>
      </div>

      {/*
        * THE FOOTER, WHICH THIS PAGE WAS MISSING ENTIRELY.
        *
        * A real orphan, not a cosmetic gap. `/demo` is linked from the public footer as
        * "Sample report" and from the hero as "See a sample report", so it is one of the most
        * likely pages for a signed-out visitor to be standing on — and it rendered no footer,
        * which meant Terms, Refunds, Your data and the grievance contact were unreachable from
        * it. That is the exact failure `SiteFooter` was extracted from the landing page to fix,
        * and it survived because `legal-pages.test.ts` checked two hardcoded paths rather than
        * every public page. It now derives the list, so the next page added cannot repeat this.
        */}
      <SiteFooter />
    </div>
  );
}
