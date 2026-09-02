'use client';

import { useMutation } from '@tanstack/react-query';

import { getBrowserApiClient } from '@/lib/api';

/**
 * The deck review — hooks/useDeckReview.ts
 *
 * One mutation, no query. The server stores nothing, so there is nothing to read back and
 * nothing to invalidate: the result lives in this hook's state for as long as the page is
 * open and then it is gone. That is deliberate on the server's side — see api/v1/deck.py —
 * and it is why there is no `['deck']` cache key here.
 */

export interface DeckCriterionScore {
  key: string;
  label: string;
  score: number;
  max_score: number;
  weight: number;
  /** True when a parser measured this rather than the model judging it. */
  measured: boolean;
}

export interface DeckEvaluation {
  filename: string;
  slide_count: number;
  /** Percentage, 0-100. */
  weighted_total: number;
  scores: DeckCriterionScore[];
  summary: string;
  format_notes: string[];
  format_skipped: string[];
  diagram_summary: string;
  diagram_count: number;
  /** Slides the model actually looked at. 0 means it scored on text alone. */
  images_analysed: number;
  vision_unavailable_reason: string | null;
}

/** What the server could not do, said in a way a candidate can act on. */
export const VISION_REASONS: Record<string, string> = {
  libreoffice_missing:
    'The slides could not be rendered on the server, so the diagrams were not looked at. '
    + 'Export the deck as a PDF and upload that for the full visual review.',
  no_vision_provider:
    'Visual review is not switched on for this deployment, so the score is based on the '
    + 'text and the formatting.',
  vision_disabled:
    'Visual review is switched off, so the score is based on the text and the formatting.',
  render_timeout:
    'The slides took too long to render, so the diagrams were not looked at. A smaller '
    + 'deck, or a PDF export, will get the full review.',
  conversion_failed:
    'The slides could not be converted for the visual review. A PDF export usually works.',
  rasterize_failed: 'The slides could not be rendered, so the diagrams were not looked at.',
  no_pages_rendered: 'No slides could be rendered, so the diagrams were not looked at.',
  pymupdf_missing: 'Visual review is unavailable on this deployment.',
  unsupported_kind: 'Visual review is not available for this file type.',
};

export function useDeckReview() {
  return useMutation({
    mutationFn: async (file: File) => {
      const api = getBrowserApiClient();
      const form = new FormData();
      form.append('file', file);
      /*
       * GENEROUS, because the response is the whole evaluation rather than an
       * acknowledgement. The request renders the slides (a LibreOffice subprocess, bounded
       * by DECK_RENDER_TIMEOUT_S at 90s), then makes two model calls. A client that gives
       * up first turns a completed, CHARGED review into an error the candidate cannot act
       * on — and the charge is committed by then, because the work succeeded.
       */
      const res = await api.post('/api/v1/deck/review', form, { timeout: 240_000 });
      return res.data as DeckEvaluation;
    },
  });
}
