'use client';

import { motion } from 'framer-motion';

import type { Interviewer, PanelLine } from '@/hooks/useInterviewPanel';
import { cn } from '@/lib/utils';

/**
 * The room, as a conversation — components/interview/PanelThread.tsx
 *
 * This is the left column of the interview: everything Anil and Priya have said this
 * question, in order, attributed, with the person currently speaking ringed so the text and
 * the voice are visibly the same person.
 *
 * IT IS A THREAD, NOT A QUESTION BOX. That is the change the redesign turns on. Previously
 * the page showed "the question" — one string, replaced each time — which is fine while an
 * interview is a questionnaire and wrong the moment it is a conversation. A DSA question now
 * arrives, the candidate writes code, the panel reads it back and says what is wrong with
 * it, and the candidate answers that. None of those are "the question"; all of them are the
 * exchange, and an exchange has to accumulate or the candidate cannot see what they are
 * replying to.
 *
 * PURELY PRESENTATIONAL. No state, no effects, no data fetching — it renders what it is
 * given. The speaking/queue logic lives in usePanelVoices and the sequencing in the page,
 * because those are genuinely intertwined with the microphone and cannot be pulled apart;
 * this can, and separating it is what keeps the page readable.
 */

export interface PanelThreadProps {
  lines: PanelLine[];
  /** Who is talking right now, from usePanelVoices. */
  speakingNow: string | null;
  /** Who is about to talk — the handover beat, and the audio fetch. */
  takingFloor: string | null;
  interviewers: Interviewer[] | undefined;
  /**
   * The bare question, shown ONLY when the panel produced nothing.
   *
   * The fallback that makes the panel safe to fail: provider down, budget spent, malformed
   * response — the candidate still gets their question and the interview continues. A
   * presentation failure must never cost somebody their interview.
   */
  fallbackQuestion?: string | null;
  /** True while the turn is being written and nobody can be heard yet. */
  pending: boolean;
}

function Dots() {
  return (
    <span className="flex gap-1" aria-hidden>
      {[0, 0.18, 0.36].map((d) => (
        <motion.span
          key={d}
          className="h-1.5 w-1.5 rounded-full bg-muted-foreground/60"
          animate={{ opacity: [0.25, 1, 0.25] }}
          transition={{ duration: 1.1, repeat: Infinity, delay: d }}
        />
      ))}
    </span>
  );
}

export function PanelThread({
  lines,
  speakingNow,
  takingFloor,
  interviewers,
  fallbackQuestion,
  pending,
}: PanelThreadProps) {
  const roleOf = (name: string) => interviewers?.find((iv) => iv.name === name)?.role;

  if (!lines.length) {
    // Nobody has spoken yet this question. Either the turn is still being written — in which
    // case saying so is honest and showing the words would put them seconds ahead of the
    // voice — or the panel failed and the bare question is all we have.
    return pending ? (
      <div className="flex items-center gap-2.5 py-2 text-sm text-muted-foreground">
        <Dots /> The panel is talking…
      </div>
    ) : fallbackQuestion ? (
      <h1 className="text-lg font-semibold leading-relaxed tracking-[-0.01em] sm:text-xl">
        {fallbackQuestion}
      </h1>
    ) : null;
  }

  return (
    <div className="space-y-3">
      {lines.map((line, i) => {
        const isLast = i === lines.length - 1;
        const speaking = speakingNow === line.speaker && isLast;
        return (
          <motion.div
            key={`${line.speaker}-${i}-${line.text.slice(0, 24)}`}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25 }}
            className={cn(
              'rounded-xl border px-4 py-3 transition-shadow',
              speaking
                ? 'border-primary/40 bg-primary/5 ring-1 ring-primary/30'
                : 'border-border/50 bg-surface/40',
            )}
          >
            <p className="mb-1 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              {line.speaker}
              {roleOf(line.speaker) && (
                <span className="font-normal normal-case tracking-normal opacity-70">
                  {roleOf(line.speaker)}
                </span>
              )}
              {/* The tone is shown only when it is a correction, and only then because that
                  is the one a candidate needs to recognise as it happens rather than read
                  about in a report a week later. Labelling every line with its mood would
                  announce the machinery. */}
              {line.tone === 'correcting' && (
                <span className="rounded-full bg-destructive/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-destructive">
                  correction
                </span>
              )}
            </p>
            <p className="text-[15px] leading-relaxed">{line.text}</p>
          </motion.div>
        );
      })}

      {/* Somebody is drawing breath. This covers the handover beat AND the audio fetch, so
          the gap before the next voice reads as a person taking the floor rather than as the
          page having stopped. */}
      {takingFloor && (
        <div className="flex items-center gap-2.5 px-1 py-1 text-xs text-muted-foreground">
          <Dots /> {takingFloor} is about to speak…
        </div>
      )}
    </div>
  );
}

export default PanelThread;
