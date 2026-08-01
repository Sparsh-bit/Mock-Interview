'use client';

import { motion, type Variants } from 'framer-motion';
import Link from 'next/link';
import {
  ArrowRight,
  Brain,
  ChevronRight,
  Code2,
  FileText,
  Mic,
  Target,
  TrendingUp,
  MessageSquare,
  ListChecks,
  Camera,
  Sparkles,
  ShieldCheck,
  Cpu,
} from 'lucide-react';
import { SplineHero } from '@/components/three/SplineHero';
import { cn } from '@/lib/utils';

const FEATURES = [
  {
    icon: Brain,
    title: 'Company & Program Tailored',
    description:
      'Tell us the company and program — Cognizant GenC, GenC Next, TCS, Infosys — and the AI builds a realistic, ordered interview: warm-up first, then technical, scenario and HR.',
    color: 'from-blue-500/20 to-blue-600/5',
    iconColor: 'text-blue-600',
  },
  {
    icon: FileText,
    title: 'Resume-Aware Questions',
    description:
      'Add your resume and the interviewer asks about YOUR actual projects, skills and experience — exactly like a real panel that read it beforehand.',
    color: 'from-purple-500/20 to-purple-600/5',
    iconColor: 'text-accent-violet',
  },
  {
    icon: Mic,
    title: 'Voice-First Interview',
    description:
      'Speak your answers aloud with a natural interviewer voice reading each question. Typing is always there as a fallback, so you are never stuck.',
    color: 'from-green-500/20 to-green-600/5',
    iconColor: 'text-emerald-600',
  },
  {
    icon: Sparkles,
    title: 'Live Cross-Questions',
    description:
      'The AI listens to what you actually said and occasionally follows up — probing a claim or asking for a concrete example — just like a real interviewer.',
    color: 'from-amber-500/20 to-amber-600/5',
    iconColor: 'text-amber-600',
  },
  {
    icon: TrendingUp,
    title: 'Full Report at the End',
    description:
      'No score pop-ups mid-interview to break your flow. At the end you get an interview-readiness assessment, topic-by-topic scores and an improvement roadmap.',
    color: 'from-red-500/20 to-red-600/5',
    iconColor: 'text-red-600',
  },
  {
    icon: Target,
    title: 'Bluffing Detection',
    description:
      'The report flags answers that sounded confident but were factually thin — so you fix the gaps you did not know you had. No easy passes.',
    color: 'from-orange-500/20 to-orange-600/5',
    iconColor: 'text-orange-600',
  },
];

const MODES = [
  { icon: MessageSquare, title: 'Group Discussion', text: 'An AI panel debates a topic; you contribute and get scored on clarity, relevance and engagement.' },
  { icon: Mic, title: 'Communication Round', text: 'AI-proctored spoken answers scored on pace, structure, filler words and confidence.' },
  { icon: ListChecks, title: 'Practice Quizzes', text: 'Timed MCQs — curated fresher banks or fresh AI-generated sets, different every time.' },
  { icon: Code2, title: 'Coding Round', text: 'A real in-browser editor wired to a compiler for hands-on coding questions.' },
  { icon: Camera, title: 'Presence Analysis', text: 'Optional on-device camera & mic check for eye-contact and delivery — never stored, never uploaded.' },
  { icon: FileText, title: 'Unified Activity Report', text: 'Every interview, GD, communication round and quiz in one history, newest first.' },
];

/**
 * Counted from the code, not rounded up for effect.
 *
 * This replaced "50+ company tracks" and a "2,000+ question bank", neither of
 * which was true — the catalogue holds 12 companies and 24 tracks, and the seeded
 * bank is a fraction of two thousand. A specific real number is also a better
 * sell than a vague large one: "87 previous-year questions, researched" is
 * checkable, and checkable is what makes the rest of the page believable.
 */
const STATS = [
  { value: '12', label: 'Companies that hire on campus' },
  { value: '24', label: 'Interview tracks' },
  { value: '48', label: 'Study subtopics, with videos' },
  { value: '87', label: 'Real previous-year questions' },
];

const COMPANIES = ['Cognizant', 'TCS', 'Infosys', 'Wipro', 'Capgemini', 'Accenture'];

const PERSONAS = [
  { name: 'Riya', role: 'Friendly HR', from: '#6366f1', to: '#8b5cf6' },
  { name: 'Arjun', role: 'Tech Lead', from: '#0ea5e9', to: '#2563eb' },
  { name: 'Meera', role: 'Senior Panelist', from: '#10b981', to: '#059669' },
];

const containerVariants: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { staggerChildren: 0.08 } },
};

const itemVariants: Variants = {
  hidden: { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.4, ease: 'easeOut' } },
};

/** A filler word, marked the way the product marks it. */
function Filler({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded-md bg-red-500/15 px-2 py-0.5 font-semibold text-red-400">
      {children}
    </span>
  );
}

/** A pause, shown where it actually happened rather than as a total. */
function Pause({ s }: { s: number }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-white/15 px-2.5 py-1 text-xs font-semibold text-white/40">
      ⏸ {s}s
    </span>
  );
}

function PersonaAvatar({ name, from, to }: { name: string; from: string; to: string }) {
  const initial = name.charAt(0);
  return (
    <svg viewBox="0 0 64 64" className="h-12 w-12 shrink-0" aria-hidden>
      <defs>
        <linearGradient id={`g-${name}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor={from} />
          <stop offset="100%" stopColor={to} />
        </linearGradient>
      </defs>
      <circle cx="32" cy="32" r="32" fill={`url(#g-${name})`} />
      <text x="32" y="41" textAnchor="middle" fontSize="26" fontWeight="700" fill="white">
        {initial}
      </text>
    </svg>
  );
}

export default function LandingPage() {
  return (
    <div className="hero-wash relative min-h-screen overflow-hidden bg-background">
      {/* Background grid + gradient orbs for depth */}
      <div className="pointer-events-none absolute inset-0 grid-bg opacity-100" />
      <div className="pointer-events-none absolute -left-40 top-20 h-96 w-96 rounded-full bg-primary/20 blur-[120px]" />
      <div className="pointer-events-none absolute -right-40 top-96 h-96 w-96 rounded-full bg-accent-violet/20 blur-[120px]" />

      {/* ── Navbar ─────────────────────────────────────────────────────────── */}
      {/* Sits over the dark hero, so it is inverted rather than inheriting the
          page's light palette. */}
      <nav className="relative z-20 mx-auto flex max-w-7xl items-center justify-between px-8 py-6">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary">
            <Code2 className="h-4 w-4 text-primary-foreground" />
          </div>
          <span className="text-lg font-bold tracking-tight text-white">InterviewOS</span>
        </div>

        <div className="hidden items-center gap-8 text-sm text-white/55 md:flex">
          <Link href="#features" className="transition-colors hover:text-white">Features</Link>
          <Link href="#rounds" className="transition-colors hover:text-white">Rounds</Link>
          <Link href="#companies" className="transition-colors hover:text-white">Companies</Link>
          <Link href="#tech" className="transition-colors hover:text-white">Technology</Link>
        </div>

        <div className="flex items-center gap-3">
          <Link href="/login" className="text-sm text-white/55 transition-colors hover:text-white">
            Sign in
          </Link>
          <Link
            href="/register"
            className="inline-flex items-center gap-1.5 rounded-full bg-white px-4 py-2 text-sm font-semibold text-[#07070b] transition-colors hover:bg-white/90"
          >
            Get Started
            <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </div>
      </nav>

      {/* ── Hero ─────────────────────────────────────────────────────────────
          A dark, full-viewport stage with the robot centred and the copy set
          around it as editorial metadata — corner labels, wide letter-spacing,
          low-contrast greys. The object is the subject; the text frames it.

          Deliberately inverted against the rest of the page, which is light. The
          hard boundary at the bottom edge is the section separator: one cinematic
          statement, then the product explains itself in daylight. */}
      <section className="relative isolate -mt-24 flex min-h-[100svh] items-center overflow-hidden bg-[#07070b] pt-24">
        {/* Depth: a pool of light under the robot, and a vignette to hold the eye. */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              'radial-gradient(58% 48% at 50% 42%, rgba(0,138,230,0.18) 0%, transparent 70%), radial-gradient(40% 30% at 50% 88%, rgba(94,92,230,0.14) 0%, transparent 70%)',
          }}
        />
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0"
          style={{ background: 'radial-gradient(120% 90% at 50% 50%, transparent 45%, #07070b 100%)' }}
        />

        {/* The robot, centred and behind everything. */}
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <SplineHero className="h-full w-full max-w-5xl" zoom={1.55} stage="#07070b" />
        </div>

        {/* Corner frame — thin rules that turn the viewport into a plate. */}
        <div aria-hidden className="pointer-events-none absolute inset-6 sm:inset-10">
          {[
            'left-0 top-0 border-l border-t',
            'right-0 top-0 border-r border-t',
            'left-0 bottom-0 border-l border-b',
            'right-0 bottom-0 border-r border-b',
          ].map((pos) => (
            <span key={pos} className={cn('absolute h-10 w-10 border-white/15', pos)} />
          ))}
        </div>

        {/* ── Copy, arranged around the object ───────────────────────────── */}
        <div className="relative z-10 mx-auto flex h-full w-full max-w-7xl flex-col justify-between px-8 py-14 sm:px-14 sm:py-20">
          {/* Top row */}
          <div className="flex items-start justify-between gap-8">
            <motion.div
              initial={{ opacity: 0, y: 18 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
              className="max-w-xl"
            >
              <h1 className="text-[clamp(2.4rem,6vw,4.6rem)] font-light uppercase leading-[0.95] tracking-[-0.02em] text-white">
                Interview
                <br />
                <span className="font-semibold">OS</span>
                <span className="ml-3 inline-block h-2.5 w-2.5 translate-y-[-0.4rem] rounded-full bg-primary align-middle" />
              </h1>
              <p className="mt-4 text-[11px] font-medium uppercase tracking-[0.32em] text-white/40 sm:text-xs">
                AI Interviewer · Build 2026.1
              </p>
            </motion.div>

            <motion.p
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.9, delay: 0.25 }}
              className="hidden max-w-[15rem] text-right text-[11px] font-medium uppercase leading-relaxed tracking-[0.18em] text-white/35 sm:block"
            >
              It asks, it listens,
              <br />
              it decides what
              <br />
              to ask you next
            </motion.p>
          </div>

          {/* Middle — the actual pitch and the CTAs. Kept low and centred so the
              robot reads above it rather than behind the text. */}
          <motion.div
            initial={{ opacity: 0, y: 22 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.35, ease: [0.16, 1, 0.3, 1] }}
            className="mx-auto mt-auto max-w-2xl text-center"
          >
            <p className="text-balance text-lg leading-relaxed text-white/70 sm:text-xl">
              A mock interview that pushes back — cross-questions your answers, reads your
              resume, measures how you actually speak, and scores you out of a hundred.
            </p>

            <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
              <Link
                href="/register"
                className="group inline-flex items-center gap-2 rounded-full bg-white px-8 py-3.5 text-sm font-semibold text-[#07070b] transition-all hover:bg-white/90"
              >
                Start your mock interview
                <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
              </Link>
              <Link
                href="/demo"
                className="inline-flex items-center gap-2 rounded-full border border-white/20 px-8 py-3.5 text-sm font-medium text-white/75 transition-all hover:border-white/50 hover:text-white"
              >
                View a sample report
                <ChevronRight className="h-4 w-4" />
              </Link>
            </div>
          </motion.div>

          {/* Bottom row */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.9, delay: 0.5 }}
            className="mt-14 flex flex-wrap items-end justify-between gap-4 border-t border-white/10 pt-6"
          >
            <span className="text-[10px] font-medium uppercase tracking-[0.3em] text-white/35 sm:text-[11px]">
              Cognizant · TCS · Infosys · Wipro · Accenture
            </span>
            <span className="text-[10px] font-medium uppercase tracking-[0.3em] text-white/35 sm:text-[11px]">
              12 companies · 24 tracks
            </span>
          </motion.div>
        </div>
      </section>


      {/* ── The proof section ────────────────────────────────────────────────
          The single strongest thing this product does, given a whole viewport and
          shown as the real artefact rather than described in a feature card.

          Everyone else's landing page claims "AI feedback". Nobody shows a
          candidate their own sentence with the hesitations marked in it. That
          image does the persuading — the copy just points at it. */}
      <section className="relative z-10 overflow-hidden bg-[#07070b] py-28">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0"
          style={{ background: 'radial-gradient(60% 50% at 50% 0%, rgba(0,138,230,0.12) 0%, transparent 70%)' }}
        />
        <div className="relative mx-auto max-w-4xl px-8">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: '-80px' }}
            transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
            className="text-center"
          >
            <p className="text-[11px] font-semibold uppercase tracking-[0.3em] text-white/35">
              01 — What nobody tells you
            </p>
            <h2 className="mt-5 text-balance text-[clamp(1.9rem,4.4vw,3.2rem)] font-semibold leading-[1.05] tracking-[-0.02em] text-white">
              You won&apos;t fail because you didn&apos;t know the answer.
              <br className="hidden sm:block" />
              <span className="text-white/45"> You&apos;ll fail because of how you said it.</span>
            </h2>
          </motion.div>

          {/* The artefact. */}
          <motion.div
            initial={{ opacity: 0, y: 26 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: '-60px' }}
            transition={{ duration: 0.7, delay: 0.12, ease: [0.16, 1, 0.3, 1] }}
            className="mt-12 rounded-2xl border border-white/10 bg-white/[0.03] p-6 backdrop-blur-sm sm:p-8"
          >
            <p className="mb-5 text-[10px] font-semibold uppercase tracking-[0.22em] text-white/30">
              Your exact words
            </p>

            <p className="flex flex-wrap items-center gap-x-2 gap-y-3 text-lg leading-relaxed text-white/80 sm:text-xl">
              <span>I think</span>
              <Filler>um</Filler>
              <span>the main thing is</span>
              <Pause s={3} />
              <Filler>like</Filler>
              <Filler>you know</Filler>
              <span>it just works</span>
              <Pause s={4} />
            </p>

            <div className="mt-8 grid grid-cols-2 gap-6 border-t border-white/10 pt-6 sm:grid-cols-4">
              {[
                { v: '12', l: 'pauses' },
                { v: '29s', l: 'of silence' },
                { v: '10', l: 'filler words' },
                { v: '125', l: 'words / min' },
              ].map((m) => (
                <div key={m.l}>
                  <p className="text-2xl font-semibold tabular-nums text-white sm:text-3xl">{m.v}</p>
                  <p className="mt-1 text-[11px] uppercase tracking-wider text-white/35">{m.l}</p>
                </div>
              ))}
            </div>
          </motion.div>

          <motion.p
            initial={{ opacity: 0 }}
            whileInView={{ opacity: 1 }}
            viewport={{ once: true }}
            transition={{ duration: 0.6, delay: 0.3 }}
            className="mt-8 text-center text-sm text-white/45"
          >
            Measured from your own answer, then replayed back to you — with the answer you
            should have given, written next to it.
          </motion.p>
        </div>
      </section>

      {/* ── Stats ──────────────────────────────────────────────────────────── */}
      <section className="relative z-10 border-y border-border/50 bg-surface/30 py-12">
        <div className="mx-auto max-w-5xl px-8">
          <motion.div
            className="grid grid-cols-2 gap-8 sm:grid-cols-4"
            variants={containerVariants}
            initial="hidden"
            whileInView="visible"
            viewport={{ once: true }}
          >
            {STATS.map(({ label, value }) => (
              <motion.div key={label} variants={itemVariants} className="text-center">
                <p className="gradient-text-blue text-3xl font-bold">{value}</p>
                <p className="mt-1 text-sm text-muted-foreground">{label}</p>
              </motion.div>
            ))}
          </motion.div>
        </div>
      </section>

      {/* ── Features ───────────────────────────────────────────────────────── */}
      <section id="features" className="relative z-10 mx-auto max-w-7xl px-8 py-24">
        <motion.div
          className="mb-16 text-center"
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
        >
          <p className="section-label mb-3">Platform Features</p>
          <h2 className="text-4xl font-bold">
            Built Different.{' '}
            <span className="gradient-text">Interviews, Not Quizzes.</span>
          </h2>
          <p className="mx-auto mt-4 max-w-2xl text-muted-foreground">
            Most interview tools are just Q&amp;A databases. InterviewOS is a simulation engine that
            reproduces the full experience of a real technical interview round.
          </p>
        </motion.div>

        <motion.div
          className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
          variants={containerVariants}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true }}
        >
          {FEATURES.map(({ icon: Icon, title, description, color, iconColor }) => (
            <motion.div
              key={title}
              variants={itemVariants}
              className="glass-hover group relative cursor-default overflow-hidden rounded-xl p-6"
            >
              <div className={`absolute inset-0 bg-gradient-to-br ${color} opacity-0 transition-opacity duration-300 group-hover:opacity-100`} />
              <div className="relative">
                <div className={`mb-4 inline-flex h-10 w-10 items-center justify-center rounded-lg bg-muted ${iconColor}`}>
                  <Icon className="h-5 w-5" />
                </div>
                <h3 className="mb-2 text-base font-semibold">{title}</h3>
                <p className="text-sm leading-relaxed text-muted-foreground">{description}</p>
              </div>
            </motion.div>
          ))}
        </motion.div>
      </section>

      {/* ── Rounds / Modes ─────────────────────────────────────────────────── */}
      <section id="rounds" className="relative z-10 mx-auto max-w-7xl px-8 py-12">
        <motion.div
          className="mb-12 text-center"
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
        >
          <p className="section-label mb-3">Every Round in One Place</p>
          <h2 className="text-4xl font-bold">Practice the whole placement process</h2>
          <p className="mx-auto mt-4 max-w-2xl text-muted-foreground">
            From the technical panel to the group discussion, the aptitude quiz and the HR round —
            all in one platform, all scored.
          </p>
        </motion.div>

        <motion.div
          className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
          variants={containerVariants}
          initial="hidden"
          whileInView="visible"
          viewport={{ once: true }}
        >
          {MODES.map(({ icon: Icon, title, text }) => (
            <motion.div key={title} variants={itemVariants} className="glass rounded-xl border border-border/50 p-6">
              <div className="mb-4 inline-flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <Icon className="h-5 w-5" />
              </div>
              <h3 className="mb-2 text-base font-semibold">{title}</h3>
              <p className="text-sm leading-relaxed text-muted-foreground">{text}</p>
            </motion.div>
          ))}
        </motion.div>
      </section>

      {/* ── Interviewer personas ───────────────────────────────────────────── */}
      <section className="relative z-10 mx-auto max-w-5xl px-8 py-16">
        <div className="glass rounded-2xl border border-border/50 p-10">
          <div className="mb-8 text-center">
            <p className="section-label mb-3">Meet Your Panel</p>
            <h2 className="text-3xl font-bold">Interviewers with real personalities</h2>
            <p className="mx-auto mt-3 max-w-xl text-sm text-muted-foreground">
              Choose the panel style you want to rehearse against — from a warm HR chat to a
              no-nonsense senior technical grill.
            </p>
          </div>
          <div className="grid gap-4 sm:grid-cols-3">
            {PERSONAS.map((p) => (
              <div key={p.name} className="flex items-center gap-4 rounded-xl border border-border/50 bg-surface p-5">
                <PersonaAvatar name={p.name} from={p.from} to={p.to} />
                <div>
                  <p className="font-semibold">{p.name}</p>
                  <p className="text-sm text-muted-foreground">{p.role}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Companies ──────────────────────────────────────────────────────── */}
      <section id="companies" className="relative z-10 mx-auto max-w-5xl px-8 py-16 text-center">
        <p className="section-label mb-8">Interview Tracks Available</p>
        <div className="flex flex-wrap items-center justify-center gap-4">
          {COMPANIES.map((company) => (
            <div
              key={company}
              className="rounded-lg border border-border bg-surface px-6 py-3 text-sm font-medium text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
            >
              {company}
            </div>
          ))}
        </div>
      </section>

      {/* ── Technology / Models ────────────────────────────────────────────── */}
      <section id="tech" className="relative z-10 mx-auto max-w-5xl px-8 py-16">
        <div className="mb-10 text-center">
          <p className="section-label mb-3">Under the Hood</p>
          <h2 className="text-3xl font-bold">Powered by frontier AI models</h2>
          <p className="mx-auto mt-3 max-w-xl text-sm text-muted-foreground">
            A resilient multi-model pipeline keeps interviews flowing even under load, with
            automatic fallback between providers.
          </p>
        </div>
        <div className="grid gap-4 sm:grid-cols-3">
          {[
            { icon: Cpu, title: 'Claude Sonnet 5', text: 'Primary reasoning model driving question generation, cross-questions and scoring.' },
            { icon: Cpu, title: 'GLM-4.5 fallback', text: 'Automatic fallback provider so sessions stay reliable when the primary is busy.' },
            { icon: ShieldCheck, title: 'Private by design', text: 'Camera & mic analysis runs on-device only. Nothing is recorded, uploaded or stored.' },
          ].map(({ icon: Icon, title, text }) => (
            <div key={title} className="glass rounded-xl border border-border/50 p-6">
              <div className="mb-4 inline-flex h-10 w-10 items-center justify-center rounded-lg bg-accent-violet/10 text-accent-violet">
                <Icon className="h-5 w-5" />
              </div>
              <h3 className="mb-2 text-base font-semibold">{title}</h3>
              <p className="text-sm leading-relaxed text-muted-foreground">{text}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── CTA ────────────────────────────────────────────────────────────── */}
      <section className="relative z-10 mx-auto max-w-4xl px-8 py-24 text-center">
        <div className="glass glow relative overflow-hidden rounded-2xl border border-primary/20 p-12">
          <div className="pointer-events-none absolute inset-0 bg-gradient-radial from-primary/10 via-transparent to-transparent" />
          <div className="relative">
            <h2 className="text-4xl font-bold">
              Your Interview. Your Terms.
              <br />
              <span className="gradient-text">Start Today.</span>
            </h2>
            <p className="mx-auto mt-4 max-w-xl text-muted-foreground">
              Pick your company and program, add your resume, and see exactly where you stand
              before the real interview does.
            </p>
            <Link
              href="/register"
              className="group mt-8 inline-flex items-center gap-2 rounded-xl bg-primary px-10 py-4 text-base font-semibold text-primary-foreground shadow-glow transition-all hover:bg-primary/90 hover:shadow-glow-lg"
            >
              Start Your Mock Interview
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
            </Link>
          </div>
        </div>
      </section>

      {/* ── Developer ──────────────────────────────────────────────────────── */}
      <section id="developer" className="relative z-10 border-t border-border/50 py-24">
        <div className="mx-auto max-w-5xl px-8">
          <div className="mb-12 text-center">
            <p className="section-label mb-3">The Developer</p>
            <h2 className="text-3xl font-bold">Built by one engineer</h2>
          </div>

          <div className="glass relative overflow-hidden rounded-2xl border border-border/50 p-8 md:p-12">
            <div className="pointer-events-none absolute inset-0 bg-gradient-radial from-primary/[0.07] via-transparent to-transparent" />

            <div className="relative grid items-center gap-10 md:grid-cols-[auto,1fr]">
              {/* Portrait. object-top keeps the face framed as the container
                  narrows on mobile — object-cover alone would crop upward. */}
              <div className="mx-auto w-full max-w-[15rem] md:mx-0">
                <div className="relative aspect-[4/5] overflow-hidden rounded-2xl border border-border bg-secondary/40 shadow-xl">
                  {/* Local asset in /public. Plain <img> for the same reason as
                      the profile page: one image code path, and next/image's
                      loader needs configuration to work on Cloudflare Pages. */}
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src="/img/developer.jpg"
                    alt="Sparsh Sharma, developer of InterviewOS"
                    width={900}
                    height={1349}
                    loading="lazy"
                    decoding="async"
                    className="h-full w-full object-cover object-top"
                  />
                </div>
              </div>

              <div>
                <h3 className="text-2xl font-bold tracking-[-0.01em]">Sparsh Sharma</h3>
                <p className="mt-1 text-sm font-semibold text-primary">
                  Creator &amp; Full-Stack Developer — InterviewOS
                </p>

                <p className="mt-5 text-sm leading-relaxed text-muted-foreground">
                  InterviewOS was designed and built end to end by one developer — the adaptive
                  interview engine, the answer-scoring pipeline, the group-discussion simulation,
                  the coding evaluator and every screen you have just scrolled through.
                </p>
                <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
                  It exists because preparing for a Cognizant or TCS interview usually means
                  reading someone else&apos;s question list and hoping it comes up. This does the
                  opposite: it puts you in the room, pushes back when an answer is thin, and tells
                  you plainly where you stand.
                </p>

                <div className="mt-7 flex flex-wrap gap-2">
                  {[
                    'Next.js 15 · React 19',
                    'FastAPI · PostgreSQL',
                    'Claude Sonnet 5',
                    'Redis · Docker',
                  ].map((tag) => (
                    <span
                      key={tag}
                      className="rounded-full border border-border/70 bg-secondary/50 px-3 py-1 text-xs font-medium text-muted-foreground"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Footer ─────────────────────────────────────────────────────────── */}
      <footer className="relative z-10 border-t border-border/50 py-8">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-8 text-sm text-muted-foreground">
          <div className="flex items-center gap-2">
            <Code2 className="h-4 w-4 text-primary" />
            <span className="font-medium">InterviewOS</span>
          </div>
          <p>© 2026 InterviewOS. Built for real offers.</p>
        </div>
      </footer>
    </div>
  );
}
