/**
 * The promo banner is a working link, not just an image — promo-banner.test.ts
 *
 * The feature is three files that have to agree: the admin uploads an image against an offer,
 * the dashboard renders it, and clicking it lands on the box where the code is typed. Each half
 * is individually plausible while the whole thing is broken — a renamed anchor turns the banner
 * into a link that loads the pricing page and scrolls nowhere, and nothing errors.
 *
 * Source assertions because vitest runs in the `node` environment here (see vitest.config.ts):
 * there is no DOM, so a component that renders an <img> cannot be mounted at all. What matters
 * is checkable either way — where the link points, what shape the container is, and whether an
 * absent banner renders nothing.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

const SRC = join(__dirname, '..');
const BANNER = readFileSync(join(SRC, 'components/PromoBanner.tsx'), 'utf8');
const CONTROL = readFileSync(join(SRC, 'components/admin/OfferBannerControl.tsx'), 'utf8');
const PRICING = readFileSync(join(SRC, 'app/pricing/page.tsx'), 'utf8');
const DASHBOARD = readFileSync(join(SRC, 'app/(dashboard)/dashboard/page.tsx'), 'utf8');
const OFFERS_ADMIN = readFileSync(join(SRC, 'app/(dashboard)/admin/offers/page.tsx'), 'utf8');

/**
 * Source with comments removed.
 *
 * Needed because these files explain themselves at length, and prose ABOUT a value is not the
 * value. The first version of the hardcoding check below matched the docstring — which quotes
 * "2400x800" precisely to explain that the form must NOT hardcode it — so the test failed by
 * reading the documentation instead of the code.
 */
function code(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '');
}

describe('clicking the banner reaches the code box', () => {
  it('links to the pricing page anchor', () => {
    expect(BANNER).toContain('/pricing#apply-offer');
  });

  it('the pricing page actually has that anchor', () => {
    // THE HALF THAT BREAKS SILENTLY. Without this id the link still works, still navigates,
    // and simply does not scroll — indistinguishable from the banner being broken.
    expect(PRICING).toContain('id="apply-offer"');
  });

  it('the anchor is offset so its label is not hidden under the header', () => {
    // A bare anchor puts the target flush against the top of the viewport, tucking the
    // "Have a code?" label out of sight — the candidate arrives at an unlabelled input, which
    // defeats the point of scrolling to it.
    const at = PRICING.indexOf('id="apply-offer"');
    expect(PRICING.slice(at, at + 260)).toMatch(/scroll-mt-\d+/);
  });

  it('the anchor is on the container, not on the input itself', () => {
    // Scrolling to the input alone leaves the label above the fold.
    const at = PRICING.indexOf('id="apply-offer"');
    const afterAnchor = PRICING.slice(at, at + 600);
    expect(afterAnchor).toContain('Have a code?');
  });

  it('the link has an accessible name', () => {
    // An image inside a link with no name is announced as its URL, and the alt text is the
    // only thing that says what the offer is.
    expect(BANNER).toMatch(/aria-label=/);
  });
});

describe('the banner cannot break the dashboard layout', () => {
  it('renders nothing when there is no banner', () => {
    // The normal case, not a failure: most days there is no live public offer with an image.
    expect(BANNER).toMatch(/if \(!data\?\.image_url\) return null;/);
  });

  it('fixes the aspect ratio and covers, so a bad upload crops instead of distorting', () => {
    expect(BANNER).toContain('object-cover');
    expect(BANNER).toMatch(/aspect-\[3\/1\]/);
  });

  it('sets no fixed height anywhere', () => {
    // A fixed height is what makes a strip wrong at some viewport width. The ratio plus a
    // full-width container scales correctly from 320px to an ultrawide.
    expect(BANNER).not.toMatch(/\bh-\[\d+px\]/);
    expect(BANNER).not.toMatch(/\bh-\d+\b/);
  });

  it('does not retry or surface an error', () => {
    // This is decoration on somebody else's dashboard. A failed request must produce no
    // strip, not a retry storm or an error card above the task they came to do.
    expect(BANNER).toMatch(/retry: false/);
  });

  it('is rendered on the dashboard', () => {
    expect(DASHBOARD).toContain('<PromoBanner />');
  });
});

describe('the admin form states the requirement and cannot drift from the validator', () => {
  it('reads the spec from the server rather than hardcoding it', () => {
    // A form promising 2400x800 while the server accepts something else presents as the
    // upload mysteriously failing — and the person debugging it is the person who read the
    // form. One source, both sides.
    expect(CONTROL).toContain('/api/v1/admin/offers/banner-spec');
    expect(code(CONTROL)).not.toMatch(/2400\s*[×x]\s*800/);
  });

  it('shows the exact size, the ratio, the byte limit and the formats', () => {
    for (const field of [
      'recommended_width',
      'recommended_height',
      'aspect_label',
      'max_kb',
      'formats',
      'min_width',
    ]) {
      expect(CONTROL, `the form never shows ${field}`).toContain(field);
    }
  });

  it('surfaces the server message verbatim on a rejection', () => {
    // The server explains what to export instead. Replacing that with a generic string throws
    // away the only part of the response that says what to do next.
    expect(CONTROL).toMatch(/err instanceof ApiError && err\.message/);
  });

  it('previews at the real aspect ratio', () => {
    // A preview shaped differently to the container it will live in is not a preview.
    const at = CONTROL.indexOf('banner.image_url');
    expect(CONTROL.slice(at, at + 400)).toMatch(/aspect-\[3\/1\][^"]*object-cover/);
  });

  it('is only offered on a public offer', () => {
    // A banner advertises a code to every candidate. A private code shared with four friends
    // must not be posted product-wide — and the server filters on is_public when it decides
    // what to serve, so offering the upload elsewhere offers something that can never appear.
    expect(OFFERS_ADMIN).toMatch(/o\.is_public && <OfferBannerControl/);
  });

  it('clears the file input so re-picking the same file still fires', () => {
    // Exactly what somebody re-exporting an image at the corrected size does.
    expect(CONTROL).toMatch(/fileRef\.current\.value = ''/);
  });

  it('revokes the object URL it creates for the local dimension check', () => {
    // Held for the lifetime of the page it is a leak, and this component is used repeatedly
    // while iterating on an image.
    const revokes = CONTROL.match(/URL\.revokeObjectURL/g) ?? [];
    expect(revokes.length, 'both the load and the error path must revoke').toBeGreaterThanOrEqual(2);
  });
});
