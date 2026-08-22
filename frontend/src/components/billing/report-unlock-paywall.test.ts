import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * The drive report paywall, as wired — components/billing/report-unlock-paywall.test.ts
 *
 * WHY THIS IS A SOURCE-TEXT TEST. Vitest runs in the `node` environment in this workspace
 * (see frontend/vitest.config.ts), so a component that renders framer-motion cannot be
 * mounted at all. The decisions worth pinning here are not values a pure function returns —
 * they are structural facts about how the screen is wired, and every one of them has a
 * specific way of going wrong that would cost money or cost a student their report:
 *
 *   · the paywall replacing the report rather than being threaded through it,
 *   · the withheld sections not being referenced anywhere on the locked screen,
 *   · one checkout call site rather than two — the bug free-order.test.ts already pins on the
 *     pricing page, where a second `mutate` left the confirm sheet spinning forever with the
 *     item silently granted behind it,
 *   · the clock being read after mount rather than during render,
 *   · and somebody who has already paid never being shown the price a second time.
 *
 * The behavioural half — what locks, what fails open, what the countdown says — is in
 * src/lib/billing/report-unlock.test.ts against real functions.
 */

const ROOT = process.cwd();
const PAYWALL = readFileSync(
  join(ROOT, 'src/components/billing/ReportUnlockPaywall.tsx'),
  'utf8',
);
const REPORT_PAGE = readFileSync(
  join(ROOT, 'src/app/(dashboard)/report/[id]/page.tsx'),
  'utf8',
);

/** Comments quote the withheld field names to explain themselves; code must not use them. */
const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
const PAYWALL_CODE = strip(PAYWALL);
const PAGE_CODE = strip(REPORT_PAGE);

describe('the report page gates delivery', () => {
  it('decides with the one shared predicate rather than its own check', () => {
    expect(PAGE_CODE).toMatch(/readReportLock\(report\)/);
    expect(PAGE_CODE).toMatch(/from '@\/lib\/billing\/report-unlock'/);
    // No second opinion. A locally re-derived "is this the drive" would disagree with the
    // server the first time a track was renamed, and would paywall the wrong candidate.
    expect(PAGE_CODE).not.toMatch(/cognizant/i);
    expect(PAGE_CODE).not.toMatch(/drive_report/);
  });

  it('returns the paywall before any part of the report is rendered', () => {
    /*
     * THE ORDERING IS THE GUARANTEE. Everything below the early return renders whatever
     * arrived in the response, so the paywall has to be a `return`, not a prop threaded
     * through a dozen sections — twelve chances to leak one of them, each of which would have
     * to stay correct forever.
     */
    const gate = PAGE_CODE.indexOf('readReportLock(report)');
    const paywall = PAGE_CODE.indexOf('<ReportUnlockPaywall');
    const firstReportField = PAGE_CODE.indexOf('report.executive_summary');
    expect(gate).toBeGreaterThan(-1);
    expect(paywall).toBeGreaterThan(gate);
    expect(firstReportField).toBeGreaterThan(paywall);
  });

  it('unlocking is a refetch, because the report was never not there', () => {
    // Gating delivery instead of generation is what makes this one line possible, and it is
    // also why a bug in the gate cannot destroy a report.
    expect(PAGE_CODE).toMatch(/onUnlocked=\{\(\) => void refetch\(\)\}/);
  });

  it('offers neither sharing nor the detailed analysis from a locked report', () => {
    // A share link to a locked report is a link to a paywall with somebody else's name on it,
    // and the analysis page is the per-question detail that has not been paid for.
    const gate = PAGE_CODE.indexOf('const lock = readReportLock(report)');
    const afterGate = PAGE_CODE.indexOf('const readiness =');
    const locked = PAGE_CODE.slice(gate, afterGate);
    expect(locked).toContain('<ReportUnlockPaywall');
    expect(locked).not.toContain('ShareMenu');
    expect(locked).not.toContain('Detailed Analysis');
  });
});

describe('the locked screen cannot show what was withheld', () => {
  it('never references a field the locked response does not carry', () => {
    /*
     * Belt and braces over the server's reduction. The teaser is the overall score and the
     * question count; if this component ever starts reading a dimension score it is either
     * reading `undefined` — a broken screen — or the server has started sending the thing
     * being sold.
     */
    for (const field of [
      'dimension_scores',
      'question_analysis',
      'improvement_roadmap',
      'topic_scores',
      'executive_summary',
      'readiness_level',
      'performance_percentile',
      'strengths',
      'weaknesses',
    ]) {
      expect(PAYWALL_CODE, `the paywall must not read ${field}`).not.toContain(field);
    }
  });

  it('shows the two teaser values and says the interview was free', () => {
    expect(PAYWALL_CODE).toMatch(/lock\.overallScore/);
    expect(PAYWALL_CODE).toMatch(/lock\.questionCount/);
    // The sentence that makes the ask reasonable. A paywall that opens with a price on a
    // product whose interview genuinely cost nothing reads as a bait-and-switch.
    expect(PAYWALL).toMatch(/The interview was free/);
  });
});

describe('the money path is the existing one', () => {
  it('prices through the shared quote and checkout hooks, never locally', () => {
    expect(PAYWALL_CODE).toMatch(/useQuote/);
    expect(PAYWALL_CODE).toMatch(/useCheckout/);
    expect(PAYWALL_CODE).toMatch(/useVerifyPayment/);
    // The browser sends an item id and a code. A price named by the page is the oldest bug in
    // online payments, and `amountPaise` below is display-only — Razorpay charges the order.
    expect(PAYWALL_CODE).toMatch(/itemId: lock\.itemId, code: appliedCode/);
  });

  it('quotes the coupon against the real item, so the exact total can be shown', () => {
    // The pricing page must quote with an empty item id because nothing has been chosen yet.
    // Here there is exactly one thing for sale, so `is_free` and the total are trustworthy.
    expect(PAYWALL_CODE).toMatch(/quote\.mutate\(\s*\{ itemId: lock\.itemId, code \}/);
  });

  it('sends only a code the server has already checked', () => {
    // `appliedCode` is set in the quote's onSuccess; the raw input never reaches checkout, so
    // a half-typed code cannot ride along with a purchase.
    expect(PAYWALL_CODE).toMatch(/setAppliedCode\(code\.toUpperCase\(\)\)/);
    expect(PAYWALL_CODE).not.toMatch(/code: codeInput/);
  });

  it('a full-value code confirms instead of opening a ₹0 payment sheet', () => {
    /*
     * Razorpay will not create an order below ₹1, so a 100%-off code has no order to open a
     * sheet for. That is a platform limit, and it is also what every large Indian checkout
     * does with a full-value coupon. FreeOrderSheet is the summary that takes its place.
     */
    expect(PAYWALL_CODE).toMatch(/quoted\?\.is_free && appliedCode/);
    expect(PAYWALL_CODE).toMatch(/setFreeOrderOpen\(true\)/);
    expect(PAYWALL_CODE).toMatch(/<FreeOrderSheet/);
    // And the granted branch closes it rather than leaving a modal over a fresh report.
    expect(PAYWALL_CODE).toMatch(/order\.granted[\s\S]{0,200}setFreeOrderOpen\(false\)/);
  });

  it('both entry points go through one checkout function', () => {
    // The bug this pins is on record: TanStack's per-call `onSuccess` fires only for the call
    // that passed it, so a second `mutate` from the confirm sheet left the sheet spinning
    // forever with the item silently granted behind it.
    expect(PAYWALL_CODE).toMatch(/const runCheckout = \(\)/);
    expect(PAYWALL_CODE).toMatch(/onConfirm=\{runCheckout\}/);
    expect(PAYWALL_CODE.match(/checkout\.mutate\(/g)?.length).toBe(1);
  });

  it('asks for the captcha before the button, and only when the offer wants one', () => {
    expect(PAYWALL_CODE).toMatch(/quoted\?\.requires_captcha && <Turnstile/);
  });
});

describe('somebody who has paid is never asked again', () => {
  it('switches to a confirmation state instead of re-rendering the price', () => {
    /*
     * Entitlement is granted by Razorpay's webhook, and `/billing/verify` is a second
     * independent path because a webhook can be late, blocked or misrouted. So a refetch
     * straight after payment can legitimately come back still locked — the one moment on this
     * screen where somebody has been charged and has nothing. It must not read as a failure,
     * and it must not show a price.
     */
    expect(PAYWALL_CODE).toMatch(/setPaidAwaitingUnlock\(true\)/);
    expect(PAYWALL_CODE).toMatch(/paidAwaitingUnlock \?/);
    const branch = PAYWALL_CODE.slice(
      PAYWALL_CODE.indexOf('paidAwaitingUnlock ?'),
      PAYWALL_CODE.indexOf(') : ('),
    );
    expect(branch).not.toMatch(/rupees\(/);
    expect(branch).not.toMatch(/Unlock my report/);
  });

  it('points at the receipt, and says a failed payment is listed too', () => {
    // The owner asked for both: a receipt the candidate can find, and failed attempts visible
    // rather than silent. PaymentHistory already renders both off the credit ledger.
    expect(PAYWALL).toMatch(/payment history/);
    expect(PAYWALL).toMatch(/fails is listed there too/);
  });
});

describe('the countdown is urgency copy and nothing else', () => {
  it('reads the clock after mount, never during render', () => {
    // Reading Date.now() during render compares an edge render at one instant against a
    // browser render at another, and that mismatch would land inside the one component on the
    // product that is asking somebody for money.
    expect(PAYWALL_CODE).toMatch(/useState<number \| null>\(null\)/);
    expect(PAYWALL_CODE).toMatch(/now === null \? null : formatCountdown\(countdown\(now,/);
    const render = PAYWALL_CODE.slice(PAYWALL_CODE.indexOf('return ('));
    expect(render).not.toContain('Date.now()');
  });

  it('nothing but copy is conditional on the deadline', () => {
    /*
     * THE RULE, INHERITED FROM lib/interview/drive.ts. When the deadline passes the chip
     * disappears and the paywall behaves identically: same price, same coupon field, same
     * unlock, same locked report. So `ticking` may only ever gate a sentence — never a price,
     * a button, or whether the gate applies.
     */
    // Every place `ticking` is used AS A CONDITION, and what it guards. Matching the
    // conditional forms rather than the bare identifier keeps the line that computes
    // `ticking` out of the sample — it sits next to the price derivation, which is a
    // neighbour, not a dependency.
    const gated = PAYWALL_CODE.match(/ticking\s*(\?|&&)[\s\S]{0,160}/g) ?? [];
    expect(gated.length).toBe(2);
    for (const use of gated) {
      expect(use).not.toMatch(/pricePaise|payPaise|charged_paise|disabled|readReportLock/);
    }
    // And the price the button shows is derived from the quote and the lock, not the clock.
    expect(PAYWALL_CODE).toMatch(
      /const payPaise = quoted && appliedCode \? quoted\.charged_paise : listPaise/,
    );
  });

  it('adds no new route, so there is no edge runtime to forget', () => {
    // A missing `export const runtime = 'edge'` has broken this project's Cloudflare Pages
    // build before — next build passes and the frontend silently stops deploying. The paywall
    // is a component on a route that already opts in; app/edge-runtime.test.ts covers the
    // route itself.
    expect(REPORT_PAGE).toMatch(/export const runtime = 'edge'/);
    expect(PAYWALL_CODE).not.toMatch(/export const runtime/);
  });
});
