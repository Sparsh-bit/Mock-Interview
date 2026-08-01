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
import { buttonVariants } from '@/components/ui/button';
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

const STATS = [
  { label: 'Interview Rounds', value: '6+' },
  { label: 'Fresher Topics Covered', value: '40+' },
  { label: 'Company Tracks', value: '50+' },
  { label: 'Question Bank', value: '2,000+' },
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
      <nav className="relative z-10 mx-auto flex max-w-7xl items-center justify-between px-8 py-6">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary">
            <Code2 className="h-4 w-4 text-primary-foreground" />
          </div>
          <span className="text-lg font-bold tracking-tight">InterviewOS</span>
        </div>

        <div className="hidden items-center gap-8 text-sm text-muted-foreground md:flex">
          <Link href="#features" className="transition-colors hover:text-foreground">Features</Link>
          <Link href="#rounds" className="transition-colors hover:text-foreground">Rounds</Link>
          <Link href="#companies" className="transition-colors hover:text-foreground">Companies</Link>
          <Link href="#tech" className="transition-colors hover:text-foreground">Technology</Link>
        </div>

        <div className="flex items-center gap-3">
          <Link href="/login" className="text-sm text-muted-foreground transition-colors hover:text-foreground">
            Sign in
          </Link>
          <Link href="/register" className={cn(buttonVariants({ size: 'sm' }))}>
            Get Started
            <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </div>
      </nav>

      {/* ── Hero ───────────────────────────────────────────────────────────── */}
      <section className="relative z-10 mx-auto grid max-w-7xl items-center gap-10 px-8 pb-28 pt-16 lg:grid-cols-[1.05fr_1fr]">
        <motion.div
          className="text-center lg:text-left"
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: 'easeOut' }}
        >
          <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-primary/30 bg-primary/10 px-4 py-1.5 text-xs font-medium text-primary">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
            Cognizant Digital Nurture • Java FSE / GenC / GenC Next
          </div>

          <h1 className="mx-auto max-w-3xl text-5xl font-bold tracking-tight sm:text-6xl lg:mx-0 lg:text-7xl">
            The most realistic{' '}
            <span className="gradient-text">AI mock interview</span> for freshers
          </h1>

          <p className="mx-auto mt-7 max-w-xl text-lg text-muted-foreground lg:mx-0">
            Pick your company and program, add your resume, and step into a fluent, voice-first
            interview that adapts to your answers — then get a full readiness report scored at the end.
          </p>

          <div className="mt-9 flex flex-col items-center justify-center gap-4 sm:flex-row lg:justify-start">
            <Link
              href="/register"
              className="group inline-flex items-center gap-2 rounded-xl bg-primary px-8 py-4 text-base font-semibold text-primary-foreground shadow-glow transition-all hover:bg-primary/90 hover:shadow-glow-lg"
            >
              Start Your Mock Interview
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
            </Link>
            <Link
              href="/demo"
              className="inline-flex items-center gap-2 rounded-xl border border-border px-8 py-4 text-base font-medium text-muted-foreground transition-all hover:border-primary/40 hover:text-foreground"
            >
              View Sample Report
              <ChevronRight className="h-4 w-4" />
            </Link>
          </div>
        </motion.div>

        {/* The robot. Second in the DOM so the headline and CTA are painted and
            readable before a ~2MB scene has finished downloading — and so a
            screen reader reaches the actual content first. */}
        <motion.div
          initial={{ opacity: 0, scale: 0.94 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.9, ease: [0.16, 1, 0.3, 1], delay: 0.15 }}
          className="relative order-last h-[420px] w-full sm:h-[520px] lg:h-[680px]"
        >
          {/* Glow behind the model so it sits in the page rather than on it. */}
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 blur-3xl"
            style={{
              background:
                'radial-gradient(45% 45% at 55% 50%, rgba(0,138,230,0.22) 0%, transparent 70%)',
            }}
          />
          <SplineHero className="h-full w-full" zoom={1.9} />
        </motion.div>

        {/* Hero visual — plan approval + voice interview mock */}
        <motion.div
          className="mx-auto mt-20 max-w-4xl"
          initial={{ opacity: 0, y: 40 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.2, ease: 'easeOut' }}
        >
          <div className="glass overflow-hidden rounded-2xl border border-border/50 shadow-card">
            <div className="flex items-center gap-2 border-b border-border/50 bg-surface/50 px-4 py-3">
              <div className="h-3 w-3 rounded-full bg-red-500/60" />
              <div className="h-3 w-3 rounded-full bg-yellow-500/60" />
              <div className="h-3 w-3 rounded-full bg-green-500/60" />
              <span className="ml-3 text-xs text-muted-foreground">Cognizant GenC — Live Interview</span>
              <div className="ml-auto flex items-center gap-2">
                <div className="h-2 w-2 animate-pulse rounded-full bg-green-400" />
                <span className="text-xs font-medium text-green-400">Live</span>
              </div>
            </div>

            <div className="grid min-h-[280px] grid-cols-2 divide-x divide-border/50">
              {/* Question panel */}
              <div className="space-y-4 p-6 text-left">
                <div className="mb-2 flex items-center gap-2">
                  <span className="badge-medium">Warm-up</span>
                  <span className="text-xs text-muted-foreground">Introduction</span>
                </div>
                <p className="text-sm font-medium leading-relaxed text-foreground">
                  To start, tell me a little about yourself and walk me through the project
                  you&apos;re most proud of from your resume.
                </p>
                <div className="pt-2">
                  <p className="mb-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                    Planned topics
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {['Introduction', 'Java Collections', 'Spring Boot', 'SQL', 'HR'].map((k) => (
                      <span key={k} className="badge-outline">{k}</span>
                    ))}
                  </div>
                </div>
              </div>

              {/* Answer panel — voice-first */}
              <div className="flex flex-col items-center justify-center gap-4 p-6">
                <div className="relative flex h-20 w-20 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-glow">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-30" />
                  <Mic className="relative h-8 w-8" />
                </div>
                <p className="text-xs font-medium text-muted-foreground">Listening… speak your answer</p>
                <div className="w-full rounded-lg border border-border bg-surface p-3 text-left">
                  <p className="text-sm leading-relaxed text-foreground/90">
                    Sure — I&apos;m a final-year CS student. My favourite project was a Spring Boot
                    inventory API where I…
                    <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-primary align-middle" />
                  </p>
                </div>
              </div>
            </div>
          </div>
        </motion.div>
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
