'use client';

import Link from 'next/link';
import { motion } from 'framer-motion';
import { ArrowRight, Check } from 'lucide-react';
import { Filler, Pause, Rule, SectionMark, Strike, WipeUp } from '@/components/landing/Annotate';
import {
  CodeArtefact,
  InterviewArtefact,
  PlanArtefact,
  ReportArtefact,
} from '@/components/landing/Artefacts';
import { CROP, ParallaxPhoto, Photo } from '@/components/landing/Photo';
import FlipWords from '@/components/lightswind-pro/flip-words';
import FocusCards from '@/components/lightswind-pro/focus-cards';
import TextGenerateEffect from '@/components/lightswind-pro/text-generate-effect';

/**
 * Hotseat — landing page.
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
 * ── Photography ────────────────────────────────────────────────────────────
 * Three photographs, each placed where it carries an argument rather than
 * where a slot needed filling:
 *
 *   hero    the desk. Before. What preparation actually looks like at 11pm.
 *   finale  the marked-up score sheet. During. The thing the product produces.
 *   close   walking into the building. After. What all of it was for.
 *
 * Before / during / after, in that order down the page. Three of the six
 * supplied images are not used and Photo.tsx records why for each.
 *
 * ── Colour ─────────────────────────────────────────────────────────────────
 * The page was near-monochrome and read as unfinished rather than restrained.
 * It now uses the six-colour system from globals.css, where every colour is
 * bound to one meaning. The discipline is not "less colour", it is that colour
 * is never decorative: the six rounds are colour-coded because there are six of
 * them and the coding is a legend; the strike is coral because coral means
 * wrong everywhere in this product; the rewrite is emerald because emerald
 * means correct. Nothing here is tinted to look nice.
 *
 * RULES THIS PAGE OBEYS (see frontend/DESIGN-RULES.md):
 *  * No gradient orbs, no glassmorphism, no three-across icon grid. Structure
 *    comes from typography, hairline rules and photography.
 *  * One verb — annotation. Two gestures — a rule drawing, content wiping up
 *    from beneath a rule. Photographs settle from a 1.06 scale; that is the
 *    third and last motion on the page.
 *  * Every number is counted from the code. See the STATS finale.
 */

const EASE = [0.16, 1, 0.3, 1] as const;

/** Counted from the code, not rounded up. The finale strikes the old false ones. */
const NUMBERS = [
  { was: '50+ company tracks', now: '24', label: 'interview tracks, across 12 companies' },
  { was: '2,000+ question bank', now: '87', label: 'real previous-year questions, researched' },
];

/**
 * Six rounds, six colours — and the colour is the legend, not decoration.
 * Each maps to its meaning in the system: the interview is the product itself,
 * the GD is behavioural, coding is measurement, communication is where filler
 * gets flagged, the quiz is timed effort, the report is completion.
 */
const ROUNDS = [
  ['Interview', 'Adaptive questions, and a follow-up when an answer is thin.', 'bg-accent-indigo'],
  ['Group discussion', 'Three AI candidates who talk over you and move on if you stay silent.', 'bg-accent-plum'],
  ['Coding', 'Runs your code, then judges the approach — and flags work that looks AI-written.', 'bg-accent-teal'],
  ['Communication', 'Spoken answers scored on pace, structure and filler.', 'bg-accent-coral'],
  ['Quiz', 'Timed MCQs, generated fresh or drawn from the bank.', 'bg-accent-amber'],
  ['Report', 'One score, four competencies, every topic ranked, and what to fix first.', 'bg-accent-emerald'],
];

/** The primary call to action. Indigo, because indigo is the product. */
/**
 * The recruiters this product has tracks for, with what each one's fresher programme is
 * actually called. The programme name is the part a candidate recognises — "GenC Next" means
 * something to someone preparing for Cognizant in a way that "Cognizant" alone does not.
 */
const RECRUITERS: { name: string; programme: string }[] = [
  { name: 'Cognizant', programme: 'GenC · GenC Next · Digital Nurture' },
  { name: 'TCS', programme: 'NQT · Ninja · Digital' },
  { name: 'Infosys', programme: 'SP · DSE · Power Programmer' },
  { name: 'Wipro', programme: 'Elite NTH · Turbo' },
  { name: 'Accenture', programme: 'ASE · Advanced App Engineer' },
  { name: 'Capgemini', programme: 'Analyst · Senior Analyst' },
  { name: 'HCLTech', programme: 'TechBee · Graduate Engineer' },
  { name: 'Tech Mahindra', programme: 'Associate Software Engineer' },
  { name: 'LTIMindtree', programme: 'Graduate Engineer Trainee' },
  { name: 'IBM', programme: 'Associate System Engineer' },
  { name: 'Deloitte', programme: 'Analyst · NLA' },
  { name: 'Amazon', programme: 'SDE I · Support Engineer' },
];

const CTA =
  'group inline-flex items-center gap-2 rounded-full bg-accent-indigo px-6 py-3 text-sm font-medium text-white shadow-elev-1 transition-[color,background-color,border-color,box-shadow,transform,opacity] hover:bg-accent-indigo-ink hover:shadow-elev-2';

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-background">
      {/* ── Nav ──────────────────────────────────────────────────────────── */}
      <nav className="mx-auto flex max-w-6xl items-center justify-between px-6 py-6 sm:px-10">
        <span className="flex items-center gap-2.5 font-mono text-sm font-semibold tracking-tight">
          <span className="h-2.5 w-2.5 rounded-full bg-accent-indigo" />
          Hotseat
        </span>
        <div className="flex items-center gap-6 text-sm">
          <Link href="/login" className="text-muted-foreground transition-colors hover:text-foreground">
            Sign in
          </Link>
          <Link
            href="/register"
            className="rounded-full bg-accent-indigo px-4 py-1.5 text-sm font-medium text-white transition-colors hover:bg-accent-indigo-ink"
          >
            Get started
          </Link>
        </div>
      </nav>

      {/* ── 01 · Hero ────────────────────────────────────────────────────────
          The thesis, beside the desk it happens at. The photograph is the only
          one that gets `priority` — it is the LCP element. */}
      <section className="hero-wash relative">
        <div className="mx-auto max-w-6xl px-6 pb-20 pt-14 sm:px-10 sm:pb-28 sm:pt-20">
          <SectionMark n="01" label="The thing nobody tells you" />

          <div className="mt-8 grid gap-12 lg:grid-cols-[1.15fr_0.85fr] lg:items-center lg:gap-16">
            <div>
              <h1 className="text-[clamp(2.1rem,5.2vw,3.9rem)] font-medium leading-[1.06] tracking-[-0.035em]">
                <WipeUp>
                  <span>You won&apos;t fail because you didn&apos;t</span>
                </WipeUp>
                <WipeUp delay={0.08}>
                  <span>know the answer. You&apos;ll fail</span>
                </WipeUp>
                <WipeUp delay={0.16}>
                  <span className="text-muted-foreground">
                    because of <span className="text-accent-coral-ink">how you said it.</span>
                  </span>
                </WipeUp>
              </h1>

              {/* Twelve recruiters are covered and a static line can only name one. Cycling
                  them tells a candidate preparing for Wipro that this is for them, without
                  printing a list above the fold. */}
              <WipeUp delay={0.22}>
                <p className="mt-5 font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
                  Practise for{' '}
                  <FlipWords
                    words={['Cognizant', 'TCS', 'Infosys', 'Wipro', 'Accenture', 'Capgemini']}
                    className="font-semibold text-accent-indigo"
                  />
                </p>
              </WipeUp>

              <WipeUp delay={0.28}>
                <p className="mt-7 max-w-lg text-base leading-relaxed text-muted-foreground sm:text-lg">
                  A mock interview that pushes back. It cross-questions a thin answer, reads your
                  resume, measures how you actually speak, and scores you out of a hundred.
                </p>
                <div className="mt-8 flex flex-wrap items-center gap-3">
                  <Link href="/register" className={CTA}>
                    Start a mock interview
                    <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                  </Link>
                  <Link
                    href="/demo"
                    className="rounded-full border border-border bg-surface-elevated px-6 py-3 text-sm text-muted-foreground transition-colors hover:border-accent-indigo/40 hover:text-accent-indigo-ink"
                  >
                    See a sample report
                  </Link>
                </div>
              </WipeUp>
            </div>

            <WipeUp delay={0.36}>
              <Photo
                name="desk"
                ratio="portrait"
                priority
                rounded="rounded-xl"
                sizes="(max-width: 1024px) 100vw, 42vw"
                className="shadow-elev-3"
              />
            </WipeUp>
          </div>
        </div>
      </section>

      {/* ── 01b · What the panel heard ───────────────────────────────────────
          The first annotation, given its own band so the marks land rather than
          competing with the hero. */}
      <section className="border-y border-border bg-surface-elevated">
        <div className="mx-auto max-w-6xl px-6 py-16 sm:px-10 sm:py-20">
          <WipeUp>
            <p className="mb-4 font-mono text-[10px] uppercase tracking-[0.22em] text-muted-foreground">
              What the panel heard
            </p>
            <p className="max-w-3xl text-xl leading-loose text-foreground/85 sm:text-2xl">
              I think <Filler>um</Filler> the main thing is
              <Pause seconds={3} /> <Filler>like</Filler> <Filler>you know</Filler> it just works
              <Pause seconds={4} />
            </p>
          </WipeUp>

          <Rule className="mt-8" />

          <WipeUp delay={0.15}>
            <dl className="mt-6 grid grid-cols-2 gap-6 sm:grid-cols-4">
              {[
                ['12', 'pauses', 'text-accent-amber-ink'],
                ['29s', 'silent', 'text-accent-coral-ink'],
                ['10', 'fillers', 'text-accent-coral-ink'],
                ['125', 'wpm', 'text-accent-teal-ink'],
              ].map(([v, l, tone]) => (
                <div key={l}>
                  <dt className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                    {l}
                  </dt>
                  <dd className={`mt-1 text-3xl font-medium tabular-nums tracking-[-0.03em] ${tone}`}>
                    {v}
                  </dd>
                </div>
              ))}
            </dl>
          </WipeUp>
        </div>
      </section>

      {/* ── 02 · The rewrite ─────────────────────────────────────────────────
          The annotation escalates: now it strikes and rewrites, which is exactly
          what the detailed analysis does to a real answer. Coral for what was
          said, emerald for what should have been — the same two colours the
          product uses everywhere for wrong and right. */}
      <section className="border-b border-border bg-secondary/40">
        <div className="mx-auto max-w-6xl px-6 py-24 sm:px-10 sm:py-32">
          <SectionMark n="02" label="And the answer you should have given" />

          <div className="mt-10 grid gap-6 lg:grid-cols-2 lg:gap-8">
            <WipeUp stretch>
              <div className="h-full rounded-lg border border-accent-coral/25 bg-accent-coral-soft p-6 sm:p-7">
                <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-accent-coral-ink">
                  You said
                </p>
                <p className="mt-4 text-lg leading-loose text-foreground/70">
                  I think the JVM is <Filler>um</Filler> like a virtual machine that runs java code
                  <Pause seconds={4} /> that&apos;s it.
                </p>
              </div>
            </WipeUp>

            <WipeUp delay={0.15} stretch>
              <div className="h-full rounded-lg border border-accent-emerald/25 bg-accent-emerald-soft p-6 sm:p-7">
                <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-accent-emerald-ink">
                  How to answer it
                </p>
                {/* Resolves word by word as it scrolls in — because this panel IS generated
                    text, so the effect shows what the product does rather than decorating it.
                    The words are in the DOM from the first frame, only their opacity animates,
                    so the paragraph stays selectable and readable without JavaScript. */}
                <TextGenerateEffect
                  className="mt-4 text-lg leading-relaxed"
                  text="The JVM is what actually runs my Java code. javac compiles to bytecode, and the JVM executes that bytecode on whatever OS I'm on — that's what makes Java platform independent. It also handles memory for me through garbage collection."
                />
              </div>
            </WipeUp>
          </div>

          <WipeUp delay={0.3}>
            <p className="mt-8 text-sm text-muted-foreground">
              Written against what you actually said — for every question you answered.
            </p>
          </WipeUp>

          {/* The interview itself, running. Placed after the rewrite because the
              rewrite is the argument and this is the evidence for it. */}
          <div className="mt-16 grid gap-6 lg:grid-cols-[1fr_1.15fr] lg:items-center lg:gap-14">
            <WipeUp>
              <h3 className="text-[clamp(1.4rem,2.8vw,2rem)] font-medium leading-[1.15] tracking-[-0.03em]">
                Answer vaguely and it pushes back —
                <span className="text-accent-indigo-ink"> the way a real interviewer does.</span>
              </h3>
              <p className="mt-4 max-w-md text-sm leading-relaxed text-muted-foreground">
                It reads what you actually said, not a script. A thin answer gets a follow-up,
                and the follow-up is about the specific thing you skipped.
              </p>
            </WipeUp>
            <InterviewArtefact />
          </div>
        </div>
      </section>

      {/* ── 03 · Rounds ──────────────────────────────────────────────────────
          A list, set like a contents page. Deliberately NOT a three-across icon
          grid: six items in an even grid is the single most template-looking
          shape on the internet. The colour bar down the left is the legend for
          the six colours used everywhere else in the product. */}
      <section className="mx-auto max-w-6xl px-6 py-24 sm:px-10 sm:py-32">
        <SectionMark n="03" label="Six rounds, not one" />

        <div className="mt-10 grid gap-12 lg:grid-cols-[1.25fr_1fr] lg:items-start lg:gap-16">
          <div>
            {ROUNDS.map(([name, desc, tone], i) => (
              <WipeUp key={name} delay={i * 0.05}>
                <div className="group grid grid-cols-[0.5rem_2.25rem_1fr] items-baseline gap-x-4 border-b border-border py-5 sm:grid-cols-[0.5rem_2.5rem_13rem_1fr] sm:gap-x-6">
                  <span className={`h-2 w-2 translate-y-[-1px] rounded-full ${tone}`} />
                  <span className="font-mono text-xs tabular-nums text-muted-foreground">
                    {String(i + 1).padStart(2, '0')}
                  </span>
                  <h3 className="text-base font-medium tracking-[-0.01em]">{name}</h3>
                  <p className="col-start-3 mt-1 text-sm leading-relaxed text-muted-foreground sm:col-start-4 sm:mt-0">
                    {desc}
                  </p>
                </div>
              </WipeUp>
            ))}
          </div>

          {/* The coding round, shown. The AI-authorship flag is the beat that
              makes people stop — it says the tool is on the interviewer's side. */}
          <div className="lg:sticky lg:top-12">
            <CodeArtefact />
          </div>
        </div>
      </section>

      {/* ── 04 · Target company ──────────────────────────────────────────── */}
      <section className="border-y border-border bg-secondary/40">
        <div className="mx-auto max-w-6xl px-6 py-24 sm:px-10 sm:py-32">
          <SectionMark n="04" label="Weighted by what they actually test" />

          <WipeUp>
            <h2 className="mt-8 max-w-3xl text-[clamp(1.6rem,3.4vw,2.6rem)] font-medium leading-[1.12] tracking-[-0.03em]">
              Amazon gives algorithms 45% of the paper. TCS gives aptitude 25%.
              <span className="text-accent-indigo-ink"> Your plan should know the difference.</span>
            </h2>
          </WipeUp>

          {/* The weight bars ARE rules — no chart component. Two companies, two
              colours, so the columns can be told apart at a glance. */}
          <div className="mt-12 grid gap-x-16 gap-y-8 sm:grid-cols-2">
            {[
              {
                c: 'Amazon',
                tone: 'bg-accent-indigo',
                label: 'text-accent-indigo-ink',
                rows: [['Data Structures & Algorithms', 45], ['Problem solving', 20], ['Leadership Principles', 15]],
              },
              {
                c: 'TCS',
                tone: 'bg-accent-teal',
                label: 'text-accent-teal-ink',
                rows: [['Aptitude & Reasoning', 25], ['C / Java / Python', 20], ['Data Structures', 15]],
              },
            ].map((col, ci) => (
              <WipeUp key={col.c} delay={ci * 0.12}>
                <p className={`mb-4 font-mono text-[11px] uppercase tracking-[0.2em] ${col.label}`}>
                  {col.c}
                </p>
                {col.rows.map(([topic, w]) => (
                  <div key={topic as string} className="mb-4">
                    <div className="mb-1.5 flex items-baseline justify-between gap-4">
                      <span className="text-sm">{topic}</span>
                      <span className="font-mono text-xs tabular-nums text-muted-foreground">{w}%</span>
                    </div>
                    <div className="h-[3px] w-full rounded-full bg-border">
                      <motion.div
                        className={`h-[3px] rounded-full ${col.tone}`}
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

          <div className="mt-14 grid gap-8 lg:grid-cols-[1fr_1.1fr] lg:items-center lg:gap-14">
            <WipeUp>
              <p className="max-w-md text-sm leading-relaxed text-muted-foreground">
                Pick your target and get a dated plan: 48 subtopics, each with something to read,
                somewhere to practise, and a quiz to check you actually know it. Tick one off and
                the plan remembers.
              </p>
            </WipeUp>
            <PlanArtefact />
          </div>
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
              <div className="text-[clamp(1.5rem,4vw,2.6rem)] font-medium leading-tight tracking-[-0.03em] text-accent-coral-ink">
                <Strike
                  delay={i * 0.1}
                  replacement={
                    <span className="tabular-nums text-foreground">
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
              <span className="inline-flex items-center gap-1.5 rounded-full bg-accent-emerald-soft px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.2em] text-accent-emerald-ink">
                <Check className="h-3 w-3" /> counted
              </span>
            </div>
          ))}
        </div>

        {/* The report — the artefact a candidate actually keeps. Shown twice on
            purpose: the photograph is the object on the table, the component is
            what it looks like on screen. */}
        <div className="mt-16 grid gap-8 lg:grid-cols-[1.1fr_1fr] lg:items-center lg:gap-14">
          <ReportArtefact />
          <WipeUp>
            <h3 className="text-[clamp(1.4rem,2.8vw,2rem)] font-medium leading-[1.15] tracking-[-0.03em]">
              One score. Four competencies.
              <span className="text-accent-teal-ink"> Every topic ranked.</span>
            </h3>
            <p className="mt-4 max-w-md text-sm leading-relaxed text-muted-foreground">
              No score pop-ups mid-interview to break your flow. At the end: where you stand, what
              to fix first, and how many hours it will take.
            </p>
            <Photo
              name="report"
              ratio="wide"
              objectPosition={CROP.reportRing}
              sizes="(max-width: 1024px) 100vw, 45vw"
              className="mt-8 shadow-elev-2"
            />
          </WipeUp>
        </div>

        <Rule className="mt-16" />

        <WipeUp delay={0.2}>
          <div className="mt-8 grid gap-8 sm:grid-cols-3">
            {[
              ['48', 'study subtopics, each with a reference', 'text-accent-amber-ink'],
              ['13', 'AI surfaces — interviewer, panel, evaluator, coach', 'text-accent-plum-ink'],
              ['12', 'companies that hire on campus', 'text-accent-indigo-ink'],
            ].map(([v, l, tone]) => (
              <div key={l}>
                <p className={`text-4xl font-medium tabular-nums tracking-[-0.03em] ${tone}`}>{v}</p>
                <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{l}</p>
              </div>
            ))}
          </div>
        </WipeUp>
      </section>

      {/* ── 06 · Companies ───────────────────────────────────────────────────
          A contents page, not a logo wall — we have no rights to their marks. */}
      <section className="border-y border-border bg-surface-elevated">
        <div className="mx-auto max-w-6xl px-6 py-20 sm:px-10">
          <SectionMark n="06" label="Who you can prepare for" />
          <WipeUp delay={0.1}>
            {/* Focus cards rather than a flat list: hovering one dims the rest, so a grid of
                twelve stops being a wall and becomes the one you are considering. Still a
                contents page — no logos, because we have no rights to their marks. */}
            <FocusCards
              className="mt-8"
              items={RECRUITERS.map((c, i) => ({
                id: c.name,
                index: String(i + 1).padStart(2, '0'),
                title: c.name,
                subtitle: c.programme,
              }))}
            />
          </WipeUp>
        </div>
      </section>

      {/* ── 07 · What it costs ───────────────────────────────────────────────
          BEFORE the close, not after it. A visitor who has read this far has decided the
          product might be for them and the very next question is the price — sending them
          hunting for it after the final call to action is how you lose the ones who were
          nearly convinced.

          Deliberately not a three-column pricing table. That is a decision surface, and the
          decision here is only "is this free to try", which it is. The full comparison lives
          on /pricing for people who have already answered that one. */}
      <section className="border-y border-border bg-secondary/40">
        <div className="mx-auto max-w-6xl px-6 py-20 sm:px-10">
          <SectionMark n="07" label="What it costs" />
          <WipeUp delay={0.1}>
            <h2 className="mt-8 max-w-3xl text-[clamp(1.6rem,3.4vw,2.4rem)] font-medium leading-[1.12] tracking-[-0.03em]">
              Start free with a communication drill and
              <span className="text-accent-indigo-ink"> unlimited quizzes — no card.</span>
            </h2>
          </WipeUp>
          <WipeUp delay={0.18}>
            <p className="mt-5 max-w-2xl text-base leading-relaxed text-muted-foreground">
              A mock interview is the real thing — a full panel, a coding round and a
              hire/no-hire report — and interviews and group discussions are what you buy, from
              ₹49. There is no subscription to argue yourself into: you buy a session when you
              want one, and what you buy never expires. A communication drill and unlimited
              quizzes you can try without paying.
            </p>
          </WipeUp>
          <WipeUp delay={0.24}>
            <div className="mt-8 flex flex-wrap items-center gap-4">
              <Link href="/register" className={CTA}>
                Start free
                <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
              </Link>
              <Link
                href="/pricing"
                className="text-sm font-medium text-muted-foreground underline-offset-4 transition-colors hover:text-foreground hover:underline"
              >
                See what a session costs
              </Link>
            </div>
          </WipeUp>
        </div>
      </section>

      {/* ── 08 · Close ───────────────────────────────────────────────────────
          The one parallax on the site, on the last image. Parallax everywhere is
          a tell; parallax exactly once, at the end, reads as an ending. */}
      <section className="relative">
        <ParallaxPhoto name="arrival" ratio="wide" className="rounded-none border-x-0" />

        <div className="mx-auto max-w-6xl px-6 py-24 sm:px-10 sm:py-32">
          <WipeUp>
            <h2 className="max-w-3xl text-[clamp(2rem,5vw,3.6rem)] font-medium leading-[1.08] tracking-[-0.035em]">
              Practise the real thing
              <span className="text-accent-indigo-ink"> before the real thing.</span>
            </h2>
          </WipeUp>
          <WipeUp delay={0.12}>
            <Link href="/register" className={`${CTA} mt-10 px-7 py-3.5`}>
              Start a mock interview
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
            </Link>
          </WipeUp>
        </div>
      </section>

      {/* ── Developer ────────────────────────────────────────────────────── */}
      <section className="border-t border-border bg-surface-elevated">
        <div className="mx-auto flex max-w-6xl flex-col gap-8 px-6 py-16 sm:flex-row sm:items-center sm:px-10">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/img/developer.jpg"
            alt="Sparsh Sharma, developer of Hotseat"
            width={900}
            height={1349}
            loading="lazy"
            className="h-28 w-28 shrink-0 rounded-full object-cover object-top ring-2 ring-accent-indigo/20 ring-offset-4 ring-offset-surface-elevated"
          />
          <div>
            <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-accent-indigo-ink">
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
          <span className="flex items-center gap-2">
            <span className="h-1.5 w-1.5 rounded-full bg-accent-indigo" />
            Hotseat
          </span>
          {/* A real address, and a mailto rather than plain text — on a phone, which is where
              most of this traffic lands, plain text means copying an email by hand. Kept in
              the footer's own type scale so it reads as contact detail rather than a CTA
              competing with the buttons above. `normal-case` because an email address in
              uppercase is not the same address. */}
          <a
            href="mailto:sparsh42005@gmail.com"
            className="normal-case tracking-normal transition-colors hover:text-foreground"
          >
            sparsh42005@gmail.com
          </a>
          <span>© 2026</span>
        </div>
      </footer>
    </div>
  );
}
