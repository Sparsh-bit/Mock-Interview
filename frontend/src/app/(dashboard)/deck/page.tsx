'use client';

import { useEffect, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { FileWarning, Presentation, Upload } from 'lucide-react';
import { toast } from 'sonner';

import { AiAssessmentNotice } from '@/components/report/AiAssessmentNotice';
import { Paywall, paywallFromError, type PaywallInfo } from '@/components/billing/Paywall';
import { CreditMeter } from '@/components/billing/CreditMeter';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { PageHeader } from '@/components/ui/page-header';
import {
  useDeckReview,
  VISION_REASONS,
  type DeckCriterionScore,
  type DeckEvaluation,
} from '@/hooks/useDeckReview';
import { fadeUp, staggerContainer } from '@/lib/motion';
import { scoreBand, scoreBarTone, scoreInkTone } from '@/lib/score-bands';
import { cn } from '@/lib/utils';

/**
 * Deck review — app/(dashboard)/deck/page.tsx
 *
 * Upload a pitch deck, get it scored out of 100 against nine criteria.
 *
 * THE LIT ELEMENT IS THE SCORE, and before there is one it is the upload control. Exactly
 * one either way — DESIGN-LANGUAGE §1. The criteria table below it is on paper, because the
 * total is the thing the page is for and nine rows of detail are how it was reached.
 *
 * NO HEAT ANYWHERE ON THIS PAGE. Heat means difficulty and only difficulty (§2), and nothing
 * here is graded by difficulty — a criterion scoring 4/10 is not a *harder* criterion. The
 * colour comes from `lib/score-bands`, the same emerald-to-coral scale the report uses, so a
 * 62 here reads as the same quality of result as a 62 there.
 *
 * @lit-exclusive-views
 *
 * TWO ELEMENTS CARRY `.lit`, AND THEY ARE NEVER BOTH ON SCREEN. The upload card is lit only
 * while `result` is null (`!result && 'lit'`), and the score panel inside `Result` only
 * renders once `result` exists. So the page always has exactly one subject: before the
 * upload it is the control, afterwards it is the number. The alternative — leaving the
 * upload card lit under a scored result — would put the light on the thing the reader has
 * finished with.
 */

export const runtime = 'edge';

/** What the browser will let somebody pick. The server decides from the bytes regardless. */
const ACCEPT = [
  '.pptx',
  '.pdf',
  'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  'application/pdf',
].join(',');

/**
 * Client-side size ceiling, mirroring DECK_MAX_UPLOAD_SIZE_MB.
 *
 * A COURTESY, NOT A CONTROL. The server refuses over its own limit with a 413 whatever this
 * says; checking here saves somebody a 30 MB upload that was always going to be rejected.
 * If the two ever disagree the server wins, and the server's message is what gets shown.
 */
const MAX_MB = 25;

function ScoreRow({ row }: { row: DeckCriterionScore }) {
  const pct = row.max_score > 0 ? (row.score / row.max_score) * 100 : 0;
  return (
    <li className="space-y-1.5 py-2.5">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-[13px] text-foreground">
          {row.label}
          {row.measured && (
            /* Said plainly, because it changes how much to trust the number: this one was
               parsed out of the file, not judged by a model. */
            <span className="ml-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
              measured
            </span>
          )}
        </span>
        <span className="flex items-baseline gap-1.5 font-mono text-[13px] tabular-nums">
          <span className={scoreInkTone(pct)}>{row.score}</span>
          <span className="text-muted-foreground">/{row.max_score}</span>
          <span className="w-9 text-right text-[11px] text-muted-foreground">
            {row.weight}%
          </span>
        </span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted/40">
        <div
          className={cn('h-full rounded-full transition-[width] duration-500', scoreBarTone(pct))}
          style={{ width: `${pct}%` }}
        />
      </div>
    </li>
  );
}

function Result({ result }: { result: DeckEvaluation }) {
  const band = scoreBand(result.weighted_total);
  const visionNote = result.vision_unavailable_reason
    ? VISION_REASONS[result.vision_unavailable_reason]
      ?? 'The slides could not be looked at, so this score is based on the text and formatting.'
    : null;

  return (
    <motion.div variants={staggerContainer(0.08)} initial="hidden" animate="visible" className="space-y-5">
      {/* THE ONE LIT ELEMENT. */}
      <motion.div variants={fadeUp} className="lit rounded-2xl p-6 sm:p-7">
        <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-accent-teal-ink/70">
          {result.filename} · {result.slide_count} slides
        </p>
        <div className="mt-2 flex items-end gap-3">
          <span className={cn('font-mono text-5xl font-semibold tabular-nums', band.ink)}>
            {result.weighted_total.toFixed(1)}
          </span>
          <span className="pb-1.5 text-sm text-muted-foreground">/ 100</span>
          <span className={cn('mb-2 rounded-full px-2 py-0.5 text-[11px]', band.chip)}>
            {band.label}
          </span>
        </div>
        {result.summary && (
          <p className="mt-3 max-w-2xl text-sm leading-relaxed text-muted-foreground">
            {result.summary}
          </p>
        )}
      </motion.div>

      {/* HOW MUCH THE MODEL COULD ACTUALLY SEE, said before the scores rather than after.
          A deck scored without its diagrams is a different claim from one scored with them,
          and the reader needs that before they read the presentation criterion. */}
      {visionNote && (
        <motion.div variants={fadeUp}>
          <Card variant="outline" className="flex gap-3 p-4">
            <FileWarning
              className="mt-0.5 h-4 w-4 flex-shrink-0 text-accent-amber-ink"
              strokeWidth={1.9}
            />
            <p className="text-[13px] leading-relaxed text-muted-foreground">{visionNote}</p>
          </Card>
        </motion.div>
      )}

      <motion.div variants={fadeUp}>
        <Card variant="outline" className="p-5">
          <h2 className="text-sm font-medium">The nine criteria</h2>
          <ul className="mt-1 divide-y divide-border/60">
            {result.scores.map((row) => (
              <ScoreRow key={row.key} row={row} />
            ))}
          </ul>
        </Card>
      </motion.div>

      {result.diagram_count > 0 && (
        <motion.div variants={fadeUp}>
          <Card variant="outline" className="p-5">
            <h2 className="text-sm font-medium">
              What the diagrams show
              <span className="ml-2 text-[11px] font-normal text-muted-foreground">
                {result.diagram_count} of {result.images_analysed} slides read
              </span>
            </h2>
            <p className="mt-2 text-[13px] leading-relaxed text-muted-foreground">
              {result.diagram_summary}
            </p>
          </Card>
        </motion.div>
      )}

      {(result.format_notes.length > 0 || result.format_skipped.length > 0) && (
        <motion.div variants={fadeUp}>
          <Card variant="outline" className="p-5">
            <h2 className="text-sm font-medium">Formatting</h2>
            <ul className="mt-2 space-y-1.5">
              {result.format_notes.map((note) => (
                <li key={note} className="text-[13px] leading-relaxed text-muted-foreground">
                  · {note}
                </li>
              ))}
            </ul>
            {result.format_skipped.map((note) => (
              <p key={note} className="mt-2 text-[12px] leading-relaxed text-muted-foreground/80">
                {note}
              </p>
            ))}
          </Card>
        </motion.div>
      )}

      <AiAssessmentNotice />
    </motion.div>
  );
}

export default function DeckReviewPage() {
  const review = useDeckReview();
  const [paywall, setPaywall] = useState<PaywallInfo | null>(null);
  /* False through the server render and the first client render — see the CreditMeter note. */
  const [mounted, setMounted] = useState(false);
  const [fileName, setFileName] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => setMounted(true), []);

  const result = review.data ?? null;

  function submit(file: File) {
    if (file.size > MAX_MB * 1024 * 1024) {
      toast.error(`That deck is over ${MAX_MB} MB. Compress the images or export it as a PDF.`);
      return;
    }
    setFileName(file.name);
    setPaywall(null);
    review.mutate(file, {
      onError: (error) => {
        /*
         * THE PAYWALL IS A 402 AND NOTHING ELSE. Every other failure is a message, because
         * they need different actions: a 415 means the wrong file, a 422 means an unreadable
         * one, a 428 means the disclosure has not been read. Collapsing them into one
         * "something went wrong" is what makes an upload feel broken rather than refused.
         */
        const wall = paywallFromError(error);
        if (wall) {
          setPaywall(wall);
          return;
        }
        const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data
          ?.detail;
        const message =
          typeof detail === 'string'
            ? detail
            : typeof (detail as { message?: string })?.message === 'string'
              ? (detail as { message: string }).message
              : 'That deck could not be reviewed.';
        toast.error(message);
      },
    });
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6 px-4 py-6 sm:px-6">
      <PageHeader
        eyebrow="Deck review"
        title="Score your pitch deck"
        description={
          'Upload the deck you would actually present. It is read, its slides are looked at, '
          + 'and it is scored out of 100 against nine criteria — the same way a panel would.'
        }
      />

      {/*
        * RENDERED ONLY AFTER MOUNT, AND THIS IS A HYDRATION FIX RATHER THAN A PREFERENCE.
        *
        * `CreditMeter` returns null while its balance query is loading and a Card once it
        * resolves — deliberately, so it never flashes a zero. That makes its output depend
        * on client-only state, so the server can emit nothing here while the client emits
        * a Card. Rendered directly, the mismatch was loud: React compared this page's
        * upload Card against the meter's own and threw a hydration error on the very first
        * page load in a browser.
        *
        * Gating on `mounted` makes the first client render provably identical to the
        * server's — both empty — so the meter appears on the pass after hydration instead
        * of during it. Wrapping it in an always-present element was tried first and only
        * narrowed the mismatch rather than removing it; this removes it, because the
        * question "is the tree the same shape" no longer has a client-only answer.
        *
        * The visible behaviour is unchanged: the meter already had no skeleton and already
        * appeared when its data arrived.
        */}
      {mounted && <CreditMeter />}

      {paywall ? (
        <Paywall info={paywall} onPurchased={() => setPaywall(null)} />
      ) : (
        <>
          {/* The upload control is lit only while there is no result — one lit thing per view. */}
          <Card
            variant="outline"
            className={cn('p-6', !result && 'lit')}
          >
            <div className="flex flex-col items-start gap-4 sm:flex-row sm:items-center">
              <div className="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-xl bg-accent-teal-soft">
                <Presentation className="h-5 w-5 text-accent-teal-ink" strokeWidth={1.9} />
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">
                  {fileName ?? 'Choose a .pptx or a PDF export'}
                </p>
                <p className="mt-0.5 text-[12px] text-muted-foreground">
                  Up to {MAX_MB} MB. Nothing is stored — the review is shown once and the file
                  is dropped.
                </p>
              </div>
              <Button
                onClick={() => inputRef.current?.click()}
                disabled={review.isPending}
                className="w-full sm:w-auto"
              >
                <Upload className="mr-2 h-4 w-4" strokeWidth={2} />
                {review.isPending
                  ? 'Reviewing…'
                  : result
                    ? 'Review another'
                    : 'Upload deck'}
              </Button>
            </div>

            <input
              ref={inputRef}
              type="file"
              accept={ACCEPT}
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                // Cleared so picking the SAME file again still fires a change event.
                event.target.value = '';
                if (file) submit(file);
              }}
            />

            {review.isPending && (
              <p className="mt-4 text-[12px] text-muted-foreground">
                Rendering the slides and reading them. This takes up to a minute for a long
                deck — the score is produced in one pass, so there is nothing to see until it
                lands.
              </p>
            )}
          </Card>

          {result && <Result result={result} />}
        </>
      )}
    </div>
  );
}
