'use client';

import Link from 'next/link';
import { motion } from 'framer-motion';
import { ArrowRight, Check } from 'lucide-react';
import { Filler, Pause, Rule, SectionMark, Strike, WipeUp } from '@/components/landing/Annotate';

/**
 * InterviewOS — landing page.
 *
 * ONE IDEA: the page marks up its own words in the product's own annotation
 * language. The product boxes your filler, stamps where you paused, strikes what
 * was wrong and writes the better line beside it — so the page does that to its
 * own copy, escalating as you scroll, and finishes by striking through the two
 * claims this very site used to make falsely and replacing them with counted
 * numbers.
 *
 * That move cannot be ported to another product. It only works for something that
 * annotates speech, and the finale only works for a company that actually made
 * those claims.
 *
 * RULES THIS PAGE OBEYS (see frontend/DESIGN-RULES.md):
 *  * No cards, no icon grids, no gradient orbs, no glassmorphism. Structure comes
 *    from typography and hairline rules.
 *  * One verb — annotation. Two gestures — a rule drawing, content wiping up from
 *    beneath a rule. Every entrance on the page is one of those two.
 *  * Colour carries meaning only. Near-monochrome, one accent, used perhaps six
 *    times on the whole page.
 *  * Every number is counted from the code. See the STATS finale.
 */

const EASE = [0.16, 1, 0.3, 1] as const;

/** Counted from the code, not rounded up. The finale strikes the old false ones. */
const NUMBERS = [
  { was: '50+ company tracks', now: '24', label: 'interview tracks, across 12 companies' },
  { was: '2,000+ question bank', now: '87', label: 'real previous-year questions, researched' },
];

const ROUNDS = [
  ['Interview', 'Adaptive questions, and a follow-up when an answer is thin.'],
  ['Group discussion', 'Three AI candidates who talk over you and move on if you stay silent.'],
  ['Coding', 'Runs your code, then judges the approach — and flags work that looks AI-written.'],
  ['Communication', 'Spoken answers scored on pace, structure and filler.'],
  ['Quiz', 'Timed MCQs, generated fresh or drawn from the bank.'],
  ['Report', 'One score, four competencies, every topic ranked, and what to fix first.'],
];

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-background">
      {/* ── Nav ──────────────────────────────────────────────────────────── */}
      <nav className="mx-auto flex max-w-6xl items-center justify-between px-6 py-6 sm:px-10">
        <span className="font-mono text-sm font-semibold tracking-tight">InterviewOS</span>
        <div className="flex items-center gap-6 text-sm">
          <Link href="/login" className="text-muted-foreground transition-colors hover:text-foreground">
            Sign in
          </Link>
          <Link
            href="/register"
            className="rounded-full bg-foreground px-4 py-1.5 text-sm font-medium text-background transition-opacity hover:opacity-85"
          >
            Get started
          </Link>
        </div>
      </nav>

      {/* ── 01 · Hero ────────────────────────────────────────────────────────
          The thesis, annotated. The sentence is the hero — no illustration, no
          object, no card. The marks ARE the art direction. */}
      <section className="mx-auto max-w-6xl px-6 pb-24 pt-16 sm:px-10 sm:pb-32 sm:pt-24">
        <SectionMark n="01" label="The thing nobody tells you" />

        <h1 className="mt-8 max-w-4xl text-[clamp(2.1rem,5.6vw,4.2rem)] font-medium leading-[1.06] tracking-[-0.035em]">
          <WipeUp>
            <span>You won&apos;t fail because you didn&apos;t</span>
          </WipeUp>
          <WipeUp delay={0.08}>
            <span>know the answer. You&apos;ll fail</span>
          </WipeUp>
          <WipeUp delay={0.16}>
            <span className="text-muted-foreground">because of how you said it.</span>
          </WipeUp>
        </h1>

        <div className="mt-14 grid gap-10 lg:grid-cols-[1.1fr_1fr] lg:items-end">
          <WipeUp delay={0.28}>
            <p className="max-w-lg text-base leading-relaxed text-muted-foreground sm:text-lg">
              A mock interview that pushes back. It cross-questions a thin answer, reads your
              resume, measures how you actually speak, and scores you out of a hundred.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Link
                href="/register"
                className="group inline-flex items-center gap-2 rounded-full bg-foreground px-6 py-3 text-sm font-medium text-background transition-opacity hover:opacity-85"
              >
                Start a mock interview
                <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
              </Link>
              <Link
                href="/demo"
                className="rounded-full border border-border px-6 py-3 text-sm text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground"
              >
                See a sample report
              </Link>
            </div>
          </WipeUp>

          {/* The first annotation. Your own sentence, marked up. */}
          <WipeUp delay={0.4}>
            <div>
              <p className="mb-3 font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
                What the panel heard
              </p>
              <p className="text-lg leading-loose text-foreground/80 sm:text-xl">
                I think <Filler>um</Filler> the main thing is
                <Pause seconds={3} /> <Filler>like</Filler> <Filler>you know</Filler> it just works
                <Pause seconds={4} />
              </p>
              <Rule className="mt-6" />
              <dl className="mt-4 grid grid-cols-4 gap-4">
                {[
                  ['12', 'pauses'],
                  ['29s', 'silent'],
                  ['10', 'fillers'],
                  ['125', 'wpm'],
                ].map(([v, l]) => (
                  <div key={l}>
                    <dt className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                      {l}
                    </dt>
                    <dd className="mt-0.5 text-xl font-medium tabular-nums tracking-[-0.02em]">{v}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </WipeUp>
        </div>
      </section>

      {/* ── 02 · The rewrite ─────────────────────────────────────────────────
          The annotation escalates: now it strikes and rewrites, which is exactly
          what the detailed analysis does to a real answer. */}
      <section className="border-y border-border bg-secondary/30">
        <div className="mx-auto max-w-6xl px-6 py-24 sm:px-10 sm:py-32">
          <SectionMark n="02" label="And the answer you should have given" />

          <div className="mt-10 grid gap-12 lg:grid-cols-2 lg:gap-16">
            <WipeUp>
              <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
                You said
              </p>
              <p className="mt-4 text-lg leading-loose text-muted-foreground">
                I think the JVM is <Filler>um</Filler> like a virtual machine that runs java code
                <Pause seconds={4} /> that&apos;s it.
              </p>
            </WipeUp>

            <WipeUp delay={0.15}>
              <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
                How to answer it
              </p>
              <p className="mt-4 text-lg leading-relaxed">
                The JVM is what actually runs my Java code. javac compiles to bytecode, and the JVM
                executes that bytecode on whatever OS I&apos;m on — that&apos;s what makes Java
                platform independent. It also handles memory for me through garbage collection.
              </p>
            </WipeUp>
          </div>

          <WipeUp delay={0.3}>
            <p className="mt-12 text-sm text-muted-foreground">
              Written against what you actually said — for every question you answered.
            </p>
          </WipeUp>
        </div>
      </section>

      {/* ── 03 · Rounds ──────────────────────────────────────────────────────
          A list, set like a contents page. Deliberately NOT a three-across icon
          grid: six items in an even grid is the single most template-looking
          shape on the internet. */}
      <section className="mx-auto max-w-6xl px-6 py-24 sm:px-10 sm:py-32">
        <SectionMark n="03" label="Six rounds, not one" />

        <div className="mt-10">
          {ROUNDS.map(([name, desc], i) => (
            <WipeUp key={name} delay={i * 0.05}>
              <div className="grid grid-cols-[2.5rem_1fr] gap-x-4 border-b border-border py-5 sm:grid-cols-[3rem_14rem_1fr] sm:gap-x-8">
                <span className="font-mono text-xs tabular-nums text-muted-foreground">
                  {String(i + 1).padStart(2, '0')}
                </span>
                <h3 className="text-base font-medium tracking-[-0.01em]">{name}</h3>
                <p className="col-start-2 mt-1 text-sm leading-relaxed text-muted-foreground sm:col-start-3 sm:mt-0">
                  {desc}
                </p>
              </div>
            </WipeUp>
          ))}
        </div>
      </section>

      {/* ── 04 · Target company ──────────────────────────────────────────── */}
      <section className="border-y border-border bg-secondary/30">
        <div className="mx-auto max-w-6xl px-6 py-24 sm:px-10 sm:py-32">
          <SectionMark n="04" label="Weighted by what they actually test" />

          <WipeUp>
            <h2 className="mt-8 max-w-3xl text-[clamp(1.6rem,3.4vw,2.6rem)] font-medium leading-[1.12] tracking-[-0.03em]">
              Amazon gives algorithms 45% of the paper. TCS gives aptitude 25%.
              <span className="text-muted-foreground"> Your plan should know the difference.</span>
            </h2>
          </WipeUp>

          {/* The weight bars ARE rules. No chart component, no card. */}
          <div className="mt-12 grid gap-x-16 gap-y-8 sm:grid-cols-2">
            {[
              { c: 'Amazon', rows: [['Data Structures & Algorithms', 45], ['Problem solving', 20], ['Leadership Principles', 15]] },
              { c: 'TCS', rows: [['Aptitude & Reasoning', 25], ['C / Java / Python', 20], ['Data Structures', 15]] },
            ].map((col, ci) => (
              <WipeUp key={col.c} delay={ci * 0.12}>
                <p className="mb-4 font-mono text-[11px] uppercase tracking-[0.2em] text-muted-foreground">
                  {col.c}
                </p>
                {col.rows.map(([topic, w]) => (
                  <div key={topic as string} className="mb-4">
                    <div className="mb-1.5 flex items-baseline justify-between gap-4">
                      <span className="text-sm">{topic}</span>
                      <span className="font-mono text-xs tabular-nums text-muted-foreground">{w}%</span>
                    </div>
                    <div className="h-px w-full bg-border">
                      <motion.div
                        className="h-px bg-foreground"
                        initial={{ scaleX: 0 }}
                        whileInView={{ scaleX: 1 }}
                        viewport={{ once: true }}
                        transition={{ duration: 0.8, ease: EASE }}
                        style={{ width: `${(w as number) * 2}%`, transformOrigin: 'left center' }}
                      />
                    </div>
                  </div>
                ))}
              </WipeUp>
            ))}
          </div>

          <WipeUp delay={0.3}>
            <p className="mt-10 max-w-xl text-sm leading-relaxed text-muted-foreground">
              Pick your target and get a dated plan: 48 subtopics, each with something to read,
              somewhere to practise, and a quiz to check you actually know it.
            </p>
          </WipeUp>
        </div>
      </section>

      {/* ── 05 · The finale ──────────────────────────────────────────────────
          The page marks up its OWN false claims. This is the beat the whole
          annotation idea has been building to, and it is the one section that
          could not exist on any other company's site. */}
      <section className="mx-auto max-w-6xl px-6 py-24 sm:px-10 sm:py-32">
        <SectionMark n="05" label="Numbers we can actually prove" />

        <WipeUp>
          <p className="mt-8 max-w-2xl text-base leading-relaxed text-muted-foreground">
            This page used to say something else. Both of these were rounded up until somebody
            counted. If we will not round up our own numbers, you can trust the ones on your
            report.
          </p>
        </WipeUp>

        <div className="mt-14 space-y-12">
          {NUMBERS.map((n, i) => (
            <div key={n.was} className="grid gap-2 sm:grid-cols-[1fr_auto] sm:items-end sm:gap-8">
              <div className="text-[clamp(1.5rem,4vw,2.6rem)] font-medium leading-tight tracking-[-0.03em]">
                <Strike
                  delay={i * 0.1}
                  replacement={
                    <span className="tabular-nums">
                      {n.now}
                      <span className="ml-3 text-base font-normal tracking-normal text-muted-foreground sm:text-lg">
                        {n.label}
                      </span>
                    </span>
                  }
                >
                  {n.was}
                </Strike>
              </div>
              <span className="inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.2em] text-muted-foreground">
                <Check className="h-3 w-3" /> counted
              </span>
            </div>
          ))}
        </div>

        <Rule className="mt-16" />

        <WipeUp delay={0.2}>
          <div className="mt-8 grid gap-8 sm:grid-cols-3">
            {[
              ['48', 'study subtopics, each with a reference'],
              ['13', 'AI surfaces — interviewer, panel, evaluator, coach'],
              ['12', 'companies that hire on campus'],
            ].map(([v, l]) => (
              <div key={l}>
                <p className="text-3xl font-medium tabular-nums tracking-[-0.03em]">{v}</p>
                <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{l}</p>
              </div>
            ))}
          </div>
        </WipeUp>
      </section>

      {/* ── 06 · Companies ───────────────────────────────────────────────────
          A contents page, not a logo wall — we have no rights to their marks. */}
      <section className="border-y border-border">
        <div className="mx-auto max-w-6xl px-6 py-20 sm:px-10">
          <SectionMark n="06" label="Who you can prepare for" />
          <WipeUp delay={0.1}>
            <div className="mt-8 grid grid-cols-2 gap-x-8 gap-y-3 sm:grid-cols-3 lg:grid-cols-4">
              {['TCS', 'Cognizant', 'Infosys', 'Wipro', 'Accenture', 'Capgemini', 'HCLTech', 'Tech Mahindra', 'LTIMindtree', 'IBM', 'Deloitte', 'Amazon'].map(
                (c, i) => (
                  <div key={c} className="flex items-baseline gap-3 border-b border-border/60 pb-2">
                    <span className="font-mono text-[10px] tabular-nums text-muted-foreground">
                      {String(i + 1).padStart(2, '0')}
                    </span>
                    <span className="text-sm">{c}</span>
                  </div>
                ),
              )}
            </div>
          </WipeUp>
        </div>
      </section>

      {/* ── 07 · Close ───────────────────────────────────────────────────── */}
      <section className="mx-auto max-w-6xl px-6 py-28 sm:px-10 sm:py-40">
        <WipeUp>
          <h2 className="max-w-3xl text-[clamp(2rem,5vw,3.6rem)] font-medium leading-[1.08] tracking-[-0.035em]">
            Practise the real thing
            <span className="text-muted-foreground"> before the real thing.</span>
          </h2>
        </WipeUp>
        <WipeUp delay={0.12}>
          <Link
            href="/register"
            className="group mt-10 inline-flex items-center gap-2 rounded-full bg-foreground px-7 py-3.5 text-sm font-medium text-background transition-opacity hover:opacity-85"
          >
            Start a mock interview
            <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
          </Link>
        </WipeUp>
      </section>

      {/* ── Developer ────────────────────────────────────────────────────── */}
      <section className="border-t border-border">
        <div className="mx-auto flex max-w-6xl flex-col gap-8 px-6 py-16 sm:flex-row sm:items-center sm:px-10">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/img/developer.jpg"
            alt="Sparsh Sharma, developer of InterviewOS"
            width={900}
            height={1349}
            loading="lazy"
            className="h-28 w-28 shrink-0 rounded-full object-cover object-top grayscale"
          />
          <div>
            <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
              Built by
            </p>
            <p className="mt-2 text-lg font-medium tracking-[-0.01em]">Sparsh Sharma</p>
            <p className="mt-2 max-w-xl text-sm leading-relaxed text-muted-foreground">
              The interview engine, the scoring pipeline, the group-discussion simulation, the
              coding evaluator and every screen — designed and built end to end by one developer.
            </p>
          </div>
        </div>
      </section>

      <footer className="border-t border-border">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-6 py-8 font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground sm:px-10">
          <span>InterviewOS</span>
          <span>© 2026</span>
        </div>
      </footer>
    </div>
  );
}
