'use client';

import type { CSSProperties, ReactNode } from 'react';

import { cn } from '@/lib/utils';

/**
 * THE SIX BEATS — components/marketing/film-beats.tsx
 *
 * One component per round, each a small piece of the real interface rebuilt in DOM rather
 * than screenshotted. They live in their own file because MkFilm.tsx is about the mechanism
 * — sticky, scrub, takeover, rail — and mixing six mock-ups into it would bury that in
 * markup.
 *
 * ── THE RULE EVERY BEAT FOLLOWS ──────────────────────────────────────────────────────────
 * A beat shows one thing happening and it is a thing the software actually does. Nothing here
 * is illustrative. The follow-up card in beat 1 is the shape the orchestrator returns; the
 * flag in beat 3 is the verdict the coding evaluator emits and the wording is its wording;
 * the four figures in beat 4 came off a real session; the ring in beat 6 is the report's own
 * geometry. DESIGN-RULES puts it as: an icon next to a paragraph is a claim, the artefact is
 * evidence — and a beat that invents a screen the product does not have is worse than either,
 * because the first person to sign up finds out.
 *
 * ── HOW THE MOTION IS DRIVEN ─────────────────────────────────────────────────────────────
 * Entirely by CSS, with `--d` on each element setting its delay. No JavaScript timers, no
 * per-frame work, and nothing that needs to know how far the page has scrolled. MkFilm
 * re-keys the active beat's wrapper, React mounts a fresh subtree, and the animations run
 * from frame zero. A beat you scroll back to plays again — correctly, because you are
 * re-entering it, not resuming it.
 *
 * The stagger is deliberately slow (roughly 0.35s between the elements that matter) so that
 * the beat's argument arrives in order: the question, then the weak answer, then the
 * cross-question. Landed all at once it is a screenshot; landed in sequence it is the
 * product behaving.
 */

/* Small helper: `--d` is the animation delay in seconds, set inline. */
const d = (seconds: number) => ({ '--d': `${seconds}s` }) as CSSProperties;

/** The fake window title bar every beat opens with. */
function Chrome({ title, right }: { title: string; right?: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-[rgb(59_43_28/0.1)] px-4 py-2.5">
      <span className="mk-num text-[10px] uppercase tracking-[0.14em] text-[var(--mk-muted)]">
        {title}
      </span>
      {right}
    </div>
  );
}

/** A cream card floating on the dark stage. */
function Card({
  className,
  style,
  children,
}: {
  className?: string;
  style?: CSSProperties;
  children: ReactNode;
}) {
  return (
    <div className={cn('mk-fcard', className)} style={style}>
      {children}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   01 · INTERVIEW
   The whole product in twelve seconds: a real question, an answer that sounds
   right, and the follow-up that finds out whether it was. The follow-up slides
   in from the right while everything else rose from below — being interrupted
   has a direction, and it is not the direction the conversation was going.
   ────────────────────────────────────────────────────────────────────────── */
export function InterviewBeat() {
  return (
    <Card className="w-[min(560px,92%)]">
      <Chrome
        title="Cognizant · Java FSE"
        right={
          <span className="mk-num text-[10px] text-[var(--mk-muted)]">Q4 / 12</span>
        }
      />
      <div className="space-y-3 p-4">
        <div className="mk-in" style={d(0.05)}>
          <p className="mk-flabel">Interviewer</p>
          <p className="text-[0.9375rem] leading-[1.5] text-[var(--mk-ink)]">
            Two threads write to the same <span className="mk-fmono">HashMap</span>. What
            actually goes wrong?
          </p>
        </div>

        <div className="mk-in rounded-[10px] bg-[rgb(59_43_28/0.05)] p-3" style={d(0.5)}>
          <p className="mk-flabel">You</p>
          <p className="text-[0.9375rem] leading-[1.5] text-[var(--mk-body)]">
            It&rsquo;s not thread-safe, so you&rsquo;d use{' '}
            <span className="mk-fmono">ConcurrentHashMap</span>.
          </p>
        </div>

        <div
          className="mk-in-r rounded-[10px] border-l-2 border-[var(--mk-gold)] bg-[var(--mk-gold-soft)] p-3"
          style={d(1.05)}
        >
          <p className="mk-flabel" style={{ color: 'var(--mk-gold-ink)' }}>
            Follow-up
          </p>
          <p className="text-[0.9375rem] leading-[1.5] text-[var(--mk-ink)]">
            That&rsquo;s the fix. What goes wrong <em className="not-italic font-semibold">without</em> it?
            Name the failure.
          </p>
        </div>
      </div>
    </Card>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   02 · GROUP DISCUSSION
   Three panelists with opinions, and the moment the beat exists for: one of them
   turns and names you. Silence in a GD is not neutral and the software does not
   treat it as neutral, so neither does the beat.
   ────────────────────────────────────────────────────────────────────────── */
const PANEL = [
  { initials: 'AR', name: 'Arjun', line: 'Review is about accountability, not typos.' },
  { initials: 'RH', name: 'Rhea', line: 'That assumes the reviewer reads it at all.' },
  { initials: 'KV', name: 'Kavya', line: 'Ours catches more than the humans did.' },
];

export function GdBeat() {
  return (
    <Card className="w-[min(560px,92%)]">
      <Chrome
        title="Group discussion"
        right={<span className="mk-num text-[10px] text-[var(--mk-muted)]">07:12 left</span>}
      />
      <div className="space-y-2.5 p-4">
        <p className="mk-in mk-flabel" style={d(0.05)}>
          Topic — should AI code review replace human review?
        </p>

        {PANEL.map((p, i) => (
          <div
            key={p.name}
            className="mk-in flex items-start gap-3 rounded-[10px] px-2.5 py-2"
            style={{
              ...d(0.35 + i * 0.3),
              background: i === 1 ? 'var(--mk-gold-soft)' : 'transparent',
            }}
          >
            <span className="mk-favatar">{p.initials}</span>
            <span className="min-w-0">
              <span className="mk-flabel">{p.name}</span>
              <span className="block text-[0.875rem] leading-[1.45] text-[var(--mk-body)]">
                {p.line}
              </span>
            </span>
            {i === 1 && (
              <span className="mk-wave ml-auto mt-1 flex shrink-0 items-end gap-[2px]">
                {[0, 1, 2, 3, 4].map((b) => (
                  <i key={b} style={{ '--b': b } as CSSProperties} />
                ))}
              </span>
            )}
          </div>
        ))}

        <div
          className="mk-in-r rounded-[10px] border-l-2 border-[var(--mk-bad)] bg-[var(--mk-bad-bg)] p-3"
          style={d(1.5)}
        >
          <p className="mk-flabel" style={{ color: 'var(--mk-bad)' }}>
            Rhea, to you
          </p>
          <p className="text-[0.9375rem] leading-[1.5] text-[var(--mk-ink)]">
            You&rsquo;ve been quiet for four minutes. Do you agree with Arjun or not?
          </p>
        </div>
      </div>
    </Card>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   03 · CODING
   Three green verdicts and then a fourth panel that is not green. The surprise is
   the beat: a page that only ever shows you passing is a page selling a toy.
   ────────────────────────────────────────────────────────────────────────── */
const CODE = [
  'public int[] twoSum(int[] nums, int target) {',
  '    Map<Integer, Integer> seen = new HashMap<>();',
  '    for (int i = 0; i < nums.length; i++) {',
  '        int need = target - nums[i];',
  '        if (seen.containsKey(need))',
  '            return new int[] { seen.get(need), i };',
  '        seen.put(nums[i], i);',
  '    }',
  '    return new int[0];',
  '}',
];

const VERDICTS = [
  { label: 'Correctness', value: '8 / 8 tests', good: true },
  { label: 'Complexity', value: 'O(n) time, O(n) space', good: true },
  { label: 'Approach', value: 'Optimal', good: true },
];

export function CodingBeat() {
  return (
    <Card className="w-[min(600px,92%)]">
      <Chrome
        title="Coding round · twoSum.java"
        right={<span className="mk-num text-[10px] text-[var(--mk-muted)]">Java 17</span>}
      />
      <div className="p-4">
        <pre className="mk-fcode">
          {CODE.map((line, i) => (
            <span key={i} className="mk-in block" style={d(0.05 + i * 0.045)}>
              {line || ' '}
            </span>
          ))}
        </pre>

        <div className="mt-3 space-y-1.5">
          {VERDICTS.map((v, i) => (
            <div
              key={v.label}
              className="mk-in flex items-center justify-between gap-3 text-[0.8125rem]"
              style={d(0.65 + i * 0.13)}
            >
              <span className="text-[var(--mk-muted)]">{v.label}</span>
              <span
                className="mk-num rounded-full px-2 py-0.5 text-[11px] font-semibold"
                style={{ background: 'var(--mk-good-bg)', color: 'var(--mk-good)' }}
              >
                {v.value}
              </span>
            </div>
          ))}
        </div>

        <div
          className="mk-in mt-3 rounded-[10px] border border-dashed p-3"
          style={{
            ...d(1.15),
            borderColor: 'var(--mk-bad)',
            background: 'var(--mk-bad-bg)',
          }}
        >
          <p className="mk-flabel" style={{ color: 'var(--mk-bad)' }}>
            Flagged
          </p>
          <p className="text-[0.875rem] leading-[1.45] text-[var(--mk-ink)]">
            Optimal on the first attempt with no iteration — this may be AI-written.
          </p>
        </div>
      </div>
    </Card>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   04 · COMMUNICATION
   The invisible failure, made a number. Fillers get a box drawn around them
   rather than a highlight faded in: a drawn mark is somebody marking your paper,
   a fade is a stylesheet.
   ────────────────────────────────────────────────────────────────────────── */
const DELIVERY = [
  { n: '12', label: 'pauses', tone: 'var(--mk-gold-ink)' },
  { n: '29s', label: 'silent', tone: 'var(--mk-bad)' },
  { n: '10', label: 'fillers', tone: 'var(--mk-bad)' },
  { n: '125', label: 'wpm', tone: 'var(--mk-good)' },
];

export function CommunicationBeat() {
  return (
    <Card className="w-[min(600px,92%)]">
      <Chrome
        title="Communication · spoken"
        right={<span className="mk-num text-[10px] text-[var(--mk-muted)]">02:41</span>}
      />
      <div className="p-4">
        <p className="mk-flabel">What the panel heard</p>
        <p className="mt-1.5 text-[1.0625rem] leading-[1.9] text-[var(--mk-ink)]">
          I think{' '}
          <span className="mk-fill" style={d(0.35)}>
            um
          </span>{' '}
          the main thing is{' '}
          <span className="mk-pause" style={d(0.7)}>
            3s
          </span>{' '}
          <span className="mk-fill" style={d(1.0)}>
            like
          </span>{' '}
          <span className="mk-fill" style={d(1.2)}>
            you know
          </span>{' '}
          it just works{' '}
          <span className="mk-pause" style={d(1.5)}>
            4s
          </span>
        </p>

        <div className="mk-in mt-4 h-px bg-[rgb(59_43_28/0.12)]" style={d(1.75)} />

        <dl className="mt-3 grid grid-cols-4 gap-2">
          {DELIVERY.map((s, i) => (
            <div key={s.label} className="mk-in" style={d(1.9 + i * 0.1)}>
              <dt className="mk-num text-[1.5rem] leading-none" style={{ color: s.tone }}>
                {s.n}
              </dt>
              <dd className="mt-1 text-[11px] text-[var(--mk-muted)]">{s.label}</dd>
            </div>
          ))}
        </dl>
      </div>
    </Card>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   05 · QUIZ
   The cheapest surface in the product and the only one that is free without
   limit, so the beat is the shortest: a question, a wrong answer, a right one.
   ────────────────────────────────────────────────────────────────────────── */
const OPTIONS = [
  { text: 'HashMap', state: 'idle' },
  { text: 'LinkedHashMap', state: 'right' },
  { text: 'TreeMap', state: 'wrong' },
  { text: 'Hashtable', state: 'idle' },
] as const;

export function QuizBeat() {
  return (
    <Card className="w-[min(520px,92%)]">
      <Chrome
        title="Quiz · Java · medium"
        right={<span className="mk-num text-[10px] text-[var(--mk-gold-ink)]">00:14</span>}
      />
      <div className="p-4">
        <p className="mk-in text-[1rem] leading-[1.45] text-[var(--mk-ink)]" style={d(0.05)}>
          Which map keeps insertion order <em className="not-italic">and</em> allows one null
          key?
        </p>

        <ul className="mt-3 space-y-1.5">
          {OPTIONS.map((o, i) => (
            <li
              key={o.text}
              className={cn(
                'mk-in mk-fopt',
                o.state === 'right' && 'mk-fopt-right',
                o.state === 'wrong' && 'mk-fopt-wrong',
              )}
              style={d(0.3 + i * 0.12)}
            >
              <span className="mk-num text-[11px] text-[var(--mk-muted)]">
                {String.fromCharCode(65 + i)}
              </span>
              <span className="mk-fmono text-[0.875rem]">{o.text}</span>
            </li>
          ))}
        </ul>

        <p className="mk-in mt-3 text-[0.8125rem] text-[var(--mk-muted)]" style={d(1.5)}>
          Fresh questions for your target company, or the curated bank.{' '}
          <span className="font-semibold text-[var(--mk-ink)]">Never charged.</span>
        </p>
      </div>
    </Card>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   06 · REPORT
   The last beat, and the only one that resolves. Everything before it opened a
   question; this closes them with a number, four competencies and the topic to
   fix first — which is what the visitor actually came to find out.
   ────────────────────────────────────────────────────────────────────────── */
const COMPETENCIES = [
  { label: 'Technical accuracy', pct: 78 },
  { label: 'Answer completeness', pct: 61 },
  { label: 'Communication clarity', pct: 83 },
  { label: 'Confidence & composure', pct: 57 },
];

export function ReportBeat() {
  /* r=34 gives a 213.6px circumference; the dash offset animates from full to 26% of it,
     which is the 74 the ring reads. Written as arithmetic rather than a magic number so a
     different score is one edit. */
  const R = 34;
  const C = 2 * Math.PI * R;

  return (
    <Card className="w-[min(600px,92%)]">
      <Chrome
        title="Report · Cognizant GenC"
        right={<span className="mk-num text-[10px] text-[var(--mk-muted)]">12 questions</span>}
      />
      <div className="flex flex-col items-center gap-5 p-5 sm:flex-row sm:items-start">
        <div className="mk-in relative shrink-0" style={d(0.1)}>
          <svg width="104" height="104" viewBox="0 0 84 84" aria-hidden>
            <circle cx="42" cy="42" r={R} fill="none" stroke="rgb(59 43 28 / 0.1)" strokeWidth="7" />
            <circle
              className="mk-ring"
              cx="42"
              cy="42"
              r={R}
              fill="none"
              stroke="var(--mk-gold)"
              strokeWidth="7"
              strokeLinecap="round"
              transform="rotate(-90 42 42)"
              style={
                {
                  strokeDasharray: C,
                  '--from': C,
                  '--to': C * (1 - 0.74),
                } as CSSProperties
              }
            />
          </svg>
          <span className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="mk-num text-[1.75rem] leading-none text-[var(--mk-ink)]">74</span>
            <span className="text-[10px] text-[var(--mk-muted)]">out of 100</span>
          </span>
        </div>

        <div className="w-full space-y-2.5">
          {COMPETENCIES.map((c, i) => (
            <div key={c.label} className="mk-in" style={d(0.5 + i * 0.14)}>
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-[0.8125rem] text-[var(--mk-body)]">{c.label}</span>
                <span className="mk-num text-[0.8125rem] text-[var(--mk-ink)]">{c.pct}</span>
              </div>
              <div className="mt-1 h-[3px] overflow-hidden rounded-full bg-[rgb(59_43_28/0.1)]">
                <span
                  className="mk-fbar block h-full rounded-full bg-[var(--mk-ink)]"
                  style={{ ...d(0.6 + i * 0.14), '--w': `${c.pct}%` } as CSSProperties}
                />
              </div>
            </div>
          ))}

          <div className="mk-in flex flex-wrap gap-1.5 pt-1.5" style={d(1.25)}>
            {['Close to ready', 'Fix JPA first · 20 hrs', 'Shareable PDF'].map((chip) => (
              <span key={chip} className="mk-fchip">
                {chip}
              </span>
            ))}
          </div>
        </div>
      </div>
    </Card>
  );
}
