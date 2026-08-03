'use client';

import { Fragment } from 'react';
import { tokenizeWithFillers, type PauseEvent } from '@/lib/speech/delivery';
import { cn } from '@/lib/utils';

interface DeliveryTranscriptProps {
  text: string;
  pauses?: PauseEvent[];
  /** Optional trailing live text (interim STT) shown greyed out. */
  interim?: string;
  /**
   * Type-level classes only — font size, colour, leading, weight.
   *
   * This component renders an INLINE <span> so it can sit inside a sentence in the
   * live interview. Box styles (border, padding, background, rounding) must go on
   * a wrapping element instead: on a multi-line inline element the browser paints
   * them once per line fragment, so a border is drawn through the middle of the
   * text and padding only applies to the first and last fragments.
   */
  className?: string;
  emptyLabel?: string;
}

/**
 * Renders a spoken transcript with delivery cues:
 *  - filler words ("uh", "um", "you know"…) highlighted in RED
 *  - pauses shown inline as a red "⏸ Ns" marker at the exact spot they occurred
 *
 * Shared across the interview, communication and group-discussion rounds so
 * delivery feedback looks and behaves identically everywhere.
 */
export function DeliveryTranscript({
  text,
  pauses = [],
  interim = '',
  className,
  emptyLabel = 'Your spoken answer will appear here…',
}: DeliveryTranscriptProps) {
  const tokens = tokenizeWithFillers(text);

  // Group pauses by the word index they precede, summing durations if several
  // landed at the same spot.
  const pauseByIndex = new Map<number, number>();
  for (const p of pauses) {
    pauseByIndex.set(p.wordIndex, (pauseByIndex.get(p.wordIndex) ?? 0) + p.seconds);
  }

  if (!text && !interim) {
    return <span className={cn('text-muted-foreground/50', className)}>{emptyLabel}</span>;
  }

  return (
    <span className={cn('leading-relaxed', className)}>
      {tokens.map((tok, i) => {
        const marker =
          tok.wordIndex >= 0 && pauseByIndex.has(tok.wordIndex) ? (
            <PauseMarker key={`p-${i}`} seconds={pauseByIndex.get(tok.wordIndex)!} />
          ) : null;

        if (tok.wordIndex === -1) {
          // whitespace
          return <Fragment key={i}>{tok.text}</Fragment>;
        }
        return (
          <Fragment key={i}>
            {marker}
            {/* Three severities, three treatments. Profanity was computed all
                along and rendered nowhere, so the one thing in a transcript that
                actually costs an offer was the only thing not marked. */}
            {tok.isUnprofessional ? (
              <span
                title="Unprofessional language — this goes in your report"
                className="rounded bg-destructive/15 px-0.5 font-semibold text-destructive decoration-destructive decoration-wavy underline underline-offset-4"
              >
                {tok.text}
              </span>
            ) : tok.isCasual ? (
              <span
                title="Casual — fine with friends, avoid in an interview"
                className="rounded bg-accent-amber/15 px-0.5 font-medium text-accent-amber-ink"
              >
                {tok.text}
              </span>
            ) : tok.isFiller ? (
              <span className="rounded bg-accent-coral/15 px-0.5 font-medium text-accent-coral-ink">
                {tok.text}
              </span>
            ) : (
              tok.text
            )}
          </Fragment>
        );
      })}
      {/* a pause registered after the final word */}
      {pauseByIndex.has(tokens.filter((t) => t.wordIndex >= 0).length) && (
        <PauseMarker seconds={pauseByIndex.get(tokens.filter((t) => t.wordIndex >= 0).length)!} />
      )}
      {interim && <span className="text-muted-foreground/60"> {interim}</span>}
    </span>
  );
}

function PauseMarker({ seconds }: { seconds: number }) {
  return (
    <span
      title={`Pause of ${seconds}s`}
      className="mx-1 inline-flex items-center gap-0.5 rounded-full border border-accent-coral/30 bg-accent-coral/10 px-1.5 py-0.5 align-middle text-[10px] font-semibold text-accent-coral-ink"
    >
      ⏸ {seconds}s
    </span>
  );
}
