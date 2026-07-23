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
  Zap,
} from 'lucide-react';
import { buttonVariants } from '@/components/ui/button';
import { cn } from '@/lib/utils';

const FEATURES = [
  {
    icon: Brain,
    title: 'Adaptive AI Interviewer',
    description:
      'Questions get harder when you answer well and easier when you struggle. Just like a real technical interview.',
    color: 'from-blue-500/20 to-blue-600/5',
    iconColor: 'text-blue-600',
  },
  {
    icon: FileText,
    title: 'Resume-Personalized Sessions',
    description:
      'Upload your resume and get interviews tailored to YOUR experience. Java in your resume? Expect deep Java questions.',
    color: 'from-purple-500/20 to-purple-600/5',
    iconColor: 'text-accent-violet',
  },
  {
    icon: Zap,
    title: 'Real-Time Evaluation',
    description:
      'Get scored after every single answer — technical accuracy, communication clarity, completeness, and confidence.',
    color: 'from-yellow-500/20 to-yellow-600/5',
    iconColor: 'text-amber-600',
  },
  {
    icon: Mic,
    title: 'Voice Interview Mode',
    description:
      'Practice speaking your answers aloud. Whisper transcription converts speech to text for full evaluation.',
    color: 'from-green-500/20 to-green-600/5',
    iconColor: 'text-emerald-600',
  },
  {
    icon: TrendingUp,
    title: 'Detailed Performance Reports',
    description:
      'After each session, get an interview-readiness assessment, topic-by-topic scores, and an exact improvement roadmap.',
    color: 'from-red-500/20 to-red-600/5',
    iconColor: 'text-red-600',
  },
  {
    icon: Target,
    title: 'Bluffing Detection',
    description:
      'The AI can detect when you sound confident but are factually wrong — and it challenges you. No easy passes.',
    color: 'from-orange-500/20 to-orange-600/5',
    iconColor: 'text-orange-600',
  },
];

const STATS = [
  { label: 'Mock Sessions Completed', value: '12,400+' },
  { label: 'Average Score Improvement', value: '38%' },
  { label: 'Companies Covered', value: '50+' },
  { label: 'Questions in Knowledge Base', value: '2,000+' },
];

const COMPANIES = [
  'Cognizant', 'TCS', 'Infosys', 'Wipro', 'Capgemini', 'Accenture',
];

const containerVariants: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { staggerChildren: 0.08 } },
};

const itemVariants: Variants = {
  hidden: { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.4, ease: 'easeOut' } },
};

export default function LandingPage() {
  return (
    <div className="hero-wash relative min-h-screen overflow-hidden bg-background">
      {/* Background grid */}
      <div className="pointer-events-none absolute inset-0 grid-bg opacity-100" />

      {/* ── Navbar ─────────────────────────────────────────────────────────── */}
      <nav className="relative z-10 flex items-center justify-between px-8 py-6 max-w-7xl mx-auto">
        <div className="flex items-center gap-2">
          <div className="h-8 w-8 rounded-lg bg-primary flex items-center justify-center">
            <Code2 className="h-4 w-4 text-primary-foreground" />
          </div>
          <span className="text-lg font-bold tracking-tight">InterviewOS</span>
        </div>

        <div className="hidden md:flex items-center gap-8 text-sm text-muted-foreground">
          <Link href="#features" className="hover:text-foreground transition-colors">Features</Link>
          <Link href="#companies" className="hover:text-foreground transition-colors">Companies</Link>
          <Link href="#how-it-works" className="hover:text-foreground transition-colors">How It Works</Link>
        </div>

        <div className="flex items-center gap-3">
          <Link
            href="/login"
            className="text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            Sign in
          </Link>
          <Link href="/register" className={cn(buttonVariants({ size: 'sm' }))}>
            Get Started Free
            <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </div>
      </nav>

      {/* ── Hero ───────────────────────────────────────────────────────────── */}
      <section className="relative z-10 mx-auto max-w-5xl px-8 pt-20 pb-32 text-center">
        <motion.div
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: 'easeOut' }}
        >
          {/* Tag */}
          <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-primary/30 bg-primary/10 px-4 py-1.5 text-xs font-medium text-primary">
            <span className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse" />
            Cognizant Digital Nurture • Java FSE Track Now Live
          </div>

          {/* Headline */}
          <h1 className="mx-auto max-w-4xl text-5xl font-bold tracking-tight sm:text-7xl">
            Ace Your Technical Interview with{' '}
            <span className="gradient-text">AI That Thinks Like a Recruiter</span>
          </h1>

          <p className="mx-auto mt-8 max-w-2xl text-lg text-muted-foreground">
            Practice Cognizant, TCS, Infosys, and Wipro interviews with an AI interviewer
            that adapts in real time — probing deeper when you&apos;re strong, simplifying
            when you struggle, and detecting when you&apos;re bluffing.
          </p>

          <div className="mt-10 flex flex-col sm:flex-row items-center justify-center gap-4">
            <Link
              href="/register"
              className="group inline-flex items-center gap-2 rounded-xl bg-primary px-8 py-4 text-base font-semibold text-primary-foreground shadow-glow transition-all hover:shadow-glow-lg hover:bg-primary/90"
            >
              Start Free Mock Interview
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

        {/* Hero visual — mock interview UI */}
        <motion.div
          className="mt-20 mx-auto max-w-4xl"
          initial={{ opacity: 0, y: 40 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, delay: 0.2, ease: 'easeOut' }}
        >
          <div className="glass rounded-2xl border border-border/50 overflow-hidden shadow-card">
            {/* Window chrome */}
            <div className="flex items-center gap-2 border-b border-border/50 bg-surface/50 px-4 py-3">
              <div className="h-3 w-3 rounded-full bg-red-500/60" />
              <div className="h-3 w-3 rounded-full bg-yellow-500/60" />
              <div className="h-3 w-3 rounded-full bg-green-500/60" />
              <span className="ml-3 text-xs text-muted-foreground">
                Cognizant Java FSE — Question 4/20
              </span>
              <div className="ml-auto flex items-center gap-2">
                <div className="h-2 w-2 rounded-full bg-green-400 animate-pulse" />
                <span className="text-xs text-green-400 font-medium">Live</span>
              </div>
            </div>

            {/* Interview UI mock */}
            <div className="grid grid-cols-2 divide-x divide-border/50 min-h-[280px]">
              {/* Question panel */}
              <div className="p-6 space-y-4">
                <div className="flex items-center gap-2 mb-4">
                  <span className="badge-medium">Medium</span>
                  <span className="text-xs text-muted-foreground">Java Collections • 2:45 remaining</span>
                </div>
                <div className="h-1.5 w-full bg-muted rounded-full overflow-hidden">
                  <div className="h-full w-[40%] bg-primary rounded-full" />
                </div>
                <p className="text-sm font-medium text-foreground leading-relaxed">
                  Explain the internal implementation of{' '}
                  <code className="text-primary">HashMap</code> in Java. What happens
                  when two keys hash to the same bucket?
                </p>
                <div className="pt-2 space-y-2">
                  <p className="text-xs text-muted-foreground font-medium uppercase tracking-wider">Evaluating:</p>
                  <div className="flex flex-wrap gap-1.5">
                    {['Hash function', 'Collision handling', 'Load factor', 'Resizing'].map(k => (
                      <span key={k} className="badge-outline">{k}</span>
                    ))}
                  </div>
                </div>
              </div>

              {/* Answer panel */}
              <div className="p-6 flex flex-col">
                <p className="text-sm text-muted-foreground mb-3 font-medium">Your Answer</p>
                <div className="flex-1 rounded-lg border border-border bg-surface p-3">
                  <p className="text-sm text-foreground/90 leading-relaxed">
                    HashMap uses an array of linked lists (buckets). The{' '}
                    <code className="text-primary text-xs">hashCode()</code> determines the bucket index.
                    When collision occurs, Java 8 uses a balanced tree instead of linked list
                    when bucket size exceeds 8...
                  </p>
                  <span className="inline-block h-4 w-0.5 bg-primary animate-pulse mt-1" />
                </div>

                {/* Live score */}
                <div className="mt-4 grid grid-cols-3 gap-3">
                  {[
                    { label: 'Technical', value: '8.5', color: 'text-emerald-600' },
                    { label: 'Clarity', value: '7.0', color: 'text-blue-600' },
                    { label: 'Depth', value: '—', color: 'text-muted-foreground' },
                  ].map(({ label, value, color }) => (
                    <div key={label} className="rounded-lg bg-surface-elevated p-2 text-center">
                      <p className={`text-sm font-bold ${color}`}>{value}</p>
                      <p className="text-[10px] text-muted-foreground">{label}</p>
                    </div>
                  ))}
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
              <motion.div
                key={label}
                variants={itemVariants}
                className="text-center"
              >
                <p className="text-3xl font-bold gradient-text-blue">{value}</p>
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
          <p className="mt-4 text-muted-foreground max-w-2xl mx-auto">
            Most interview tools are just Q&A databases. InterviewOS is a simulation engine
            that reproduces the full experience of a real technical interview round.
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
              className="glass-hover group relative rounded-xl p-6 overflow-hidden cursor-default"
            >
              <div className={`absolute inset-0 bg-gradient-to-br ${color} opacity-0 group-hover:opacity-100 transition-opacity duration-300`} />
              <div className="relative">
                <div className={`mb-4 inline-flex items-center justify-center h-10 w-10 rounded-lg bg-muted ${iconColor}`}>
                  <Icon className="h-5 w-5" />
                </div>
                <h3 className="text-base font-semibold mb-2">{title}</h3>
                <p className="text-sm text-muted-foreground leading-relaxed">{description}</p>
              </div>
            </motion.div>
          ))}
        </motion.div>
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

      {/* ── CTA ────────────────────────────────────────────────────────────── */}
      <section className="relative z-10 mx-auto max-w-4xl px-8 py-24 text-center">
        <div className="glass rounded-2xl border border-primary/20 p-12 relative overflow-hidden glow">
          <div className="pointer-events-none absolute inset-0 bg-gradient-radial from-primary/10 via-transparent to-transparent" />
          <div className="relative">
            <h2 className="text-4xl font-bold">
              Your Interview. Your Terms.
              <br />
              <span className="gradient-text">Start Today — Free.</span>
            </h2>
            <p className="mt-4 text-muted-foreground max-w-xl mx-auto">
              No credit card required. Start with the Cognizant Java FSE track
              and see exactly where you stand.
            </p>
            <Link
              href="/register"
              className="group mt-8 inline-flex items-center gap-2 rounded-xl bg-primary px-10 py-4 text-base font-semibold text-primary-foreground shadow-glow transition-all hover:shadow-glow-lg hover:bg-primary/90"
            >
              Start Free Mock Interview
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
            </Link>
          </div>
        </div>
      </section>

      {/* ── Footer ─────────────────────────────────────────────────────────── */}
      <footer className="relative z-10 border-t border-border/50 py-8">
        <div className="mx-auto max-w-7xl px-8 flex items-center justify-between text-sm text-muted-foreground">
          <div className="flex items-center gap-2">
            <Code2 className="h-4 w-4 text-primary" />
            <span className="font-medium">InterviewOS</span>
          </div>
          <p>© 2025 InterviewOS. Built for real offers.</p>
        </div>
      </footer>
    </div>
  );
}
