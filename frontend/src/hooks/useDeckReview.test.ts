import { describe, expect, it } from 'vitest';

import { VISION_REASONS } from './useDeckReview';

/**
 * The deck review's client copy — useDeckReview.test.ts
 *
 * WHAT THIS PINS IS THE HONESTY OF A PARTIAL RESULT. The server scores a deck whose slides
 * it could not render, and says so with a machine reason. If the browser has no sentence for
 * that reason it falls back to a generic line, and a text-only score is then presented as a
 * complete one — the reader has no way to know the diagrams were never looked at.
 *
 * So every reason the server can emit must have copy here. The list is asserted against
 * `services/deck/render.py`'s own `unavailable_reason` values, which is the only place they
 * are produced.
 */

/** Every value `RenderResult.unavailable_reason` can take, plus the evaluator's own two. */
const SERVER_REASONS = [
  'vision_disabled',
  'no_vision_provider',
  'libreoffice_missing',
  'render_timeout',
  'conversion_failed',
  'rasterize_failed',
  'no_pages_rendered',
  'pymupdf_missing',
  'unsupported_kind',
];

describe('every reason the server can give has copy', () => {
  it.each(SERVER_REASONS)('%s is explained', (reason) => {
    expect(VISION_REASONS[reason], `${reason} has no sentence`).toBeTruthy();
  });

  it('tells the candidate what to do about the commonest one', () => {
    // A .pptx on a host without LibreOffice is the case that will actually happen, because
    // the Docker layer is opt-in. "Export as PDF" is a fix they can apply themselves.
    expect(VISION_REASONS.libreoffice_missing).toMatch(/PDF/);
  });

  it('never blames the candidate for a server limitation', () => {
    for (const [reason, copy] of Object.entries(VISION_REASONS)) {
      expect(copy, reason).not.toMatch(/\byou (?:failed|should have|must)\b/i);
    }
  });
});
