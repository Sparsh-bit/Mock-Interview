import { describe, expect, it } from 'vitest';

import {
  REPORT_UNLOCK_DEADLINE_LABEL,
  REPORT_UNLOCK_ITEM_ID,
  REPORT_UNLOCK_OFFER_DEADLINE,
  REPORT_UNLOCK_PRICE_PAISE,
  countdown,
  formatCountdown,
  readReportLock,
  rupees,
} from './report-unlock';

/**
 * The drive report paywall, pinned.
 *
 * Vitest runs in the `node` environment in this workspace (no jsdom), so the paywall itself
 * cannot be mounted — but the paywall is markup. What can actually cost something is in the
 * module these tests cover, and it is asymmetric: showing the full report to somebody who has
 * not paid costs ₹49, and showing a paywall to somebody who owes nothing costs a student their
 * report on the morning of a placement drive. So most of this file is about the second one.
 */

/** The shape the server sends for a locked report, in full. */
const LOCKED = {
  locked: true,
  lock_price_paise: 4900,
  lock_item_id: 'report_unlock_1',
  offer_deadline: '2026-08-24T10:00:00+05:30',
  overall_score: 68,
  lock_question_count: 12,
};

describe('readReportLock — the locked case', () => {
  it('reads the whole contract off a locked response', () => {
    expect(readReportLock(LOCKED)).toEqual({
      itemId: 'report_unlock_1',
      pricePaise: 4900,
      deadline: Date.parse('2026-08-24T10:00:00+05:30'),
      overallScore: 68,
      questionCount: 12,
    });
  });

  it('₹49 is 4900 paise', () => {
    // Razorpay bills in paise and every price in this repo is an integer. A rupee figure
    // reaching this field would be a hundredfold undercharge.
    expect(REPORT_UNLOCK_PRICE_PAISE).toBe(4900);
    expect(rupees(REPORT_UNLOCK_PRICE_PAISE)).toBe('₹49');
  });

  it('the item id matches the one the server can resolve', () => {
    // Mirrors `REPORT_UNLOCK_ITEM.id` in backend/app/services/billing/plans.py. Wrong here
    // means a 404 at checkout — loud and immediate, which is the failure mode we want.
    expect(REPORT_UNLOCK_ITEM_ID).toBe('report_unlock_1');
  });

  it('prefers the item id the server names over the built-in one', () => {
    // So the item can move without a frontend deploy.
    expect(readReportLock({ ...LOCKED, lock_item_id: 'report_unlock_2' })?.itemId).toBe(
      'report_unlock_2',
    );
  });
});

describe('readReportLock — it fails open', () => {
  /*
   * EVERY CASE IN HERE MUST DELIVER THE REPORT. This is the contract: anything that is not
   * unambiguously a locked drive report is delivered in full, because a locked report for
   * somebody who owes nothing is the worst outcome this feature can produce and it lands on
   * students today.
   */
  it('delivers when there is no lock flag at all', () => {
    // Today's server, before the gate ships — and every report that is not this one drive.
    expect(readReportLock({ overall_score: 71, strengths: [] })).toBeNull();
  });

  it('delivers for nothing, null and non-objects', () => {
    expect(readReportLock(undefined)).toBeNull();
    expect(readReportLock(null)).toBeNull();
    expect(readReportLock('locked')).toBeNull();
    expect(readReportLock(42)).toBeNull();
    expect(readReportLock(true)).toBeNull();
  });

  it('delivers for every truthy value that is not the boolean true', () => {
    /*
     * THE ONE THAT MOTIVATED `=== true`. The string 'false' is truthy in JavaScript, so a
     * truthiness check would lock every report the moment any serialiser stringified a
     * boolean — and it would do it to reports that were never paywalled at all.
     */
    for (const locked of ['false', 'true', 1, '1', {}, [], 'yes']) {
      expect(readReportLock({ ...LOCKED, locked })).toBeNull();
    }
  });

  it('delivers when the flag is explicitly false or absent-ish', () => {
    for (const locked of [false, 0, '', null, undefined]) {
      expect(readReportLock({ ...LOCKED, locked })).toBeNull();
    }
  });

  it('delivers a report that never finished scoring, whatever the flag says', () => {
    /*
     * The one way this paywall could take money for nothing: an unscored report has no
     * dimension scores, no per-question analysis and no roadmap to sell — only an explanation
     * of what went wrong and a Generate-again button. Charging ₹49 to read a failure, to the
     * student whose report just failed, is not a trade-off worth having.
     */
    for (const reason of ['user_quota', 'service_limit', 'timeout', 'provider_unavailable']) {
      expect(readReportLock({ ...LOCKED, unscored_reason: reason })).toBeNull();
    }
    // A null or empty reason is a normal, fully scored report and still locks.
    expect(readReportLock({ ...LOCKED, unscored_reason: null })).not.toBeNull();
    expect(readReportLock({ ...LOCKED, unscored_reason: '' })).not.toBeNull();
  });

  it('delivers rather than throwing when reading the response throws', () => {
    // A getter that throws is not a case anyone plans for; it is a case that must not put a
    // paywall in front of a paid-for report. Three lines of try/catch against the class.
    const hostile = {
      get locked(): boolean {
        throw new Error('nope');
      },
    };
    expect(readReportLock(hostile)).toBeNull();
  });
});

describe('readReportLock — a locked response with holes in it', () => {
  /*
   * These all still lock, because the server said locked and only the server decides that.
   * What is being pinned is that the screen can always be RENDERED: never "₹NaN", never a
   * price below what Razorpay will accept, never a broken countdown.
   */
  it('falls back to ₹49 when the price is missing or unusable', () => {
    for (const lock_price_paise of [undefined, null, 0, -1, 'free', 99, 12.5, NaN, Infinity]) {
      const lock = readReportLock({ ...LOCKED, lock_price_paise });
      expect(lock?.pricePaise).toBe(REPORT_UNLOCK_PRICE_PAISE);
    }
  });

  it('rejects a price under Razorpay’s one-rupee floor', () => {
    // 99 paise is not a cheap unlock, it is an order the gateway refuses to create.
    expect(readReportLock({ ...LOCKED, lock_price_paise: 99 })?.pricePaise).toBe(4900);
    expect(readReportLock({ ...LOCKED, lock_price_paise: 100 })?.pricePaise).toBe(100);
  });

  it('falls back to the built-in deadline when the server’s is unparseable', () => {
    for (const offer_deadline of [undefined, null, '', 'soon', 12345, {}]) {
      expect(readReportLock({ ...LOCKED, offer_deadline })?.deadline).toBe(
        REPORT_UNLOCK_OFFER_DEADLINE,
      );
    }
  });

  it('omits a teaser value it was not given rather than inventing one', () => {
    const lock = readReportLock({ locked: true });
    expect(lock).not.toBeNull();
    expect(lock?.overallScore).toBeNull();
    expect(lock?.questionCount).toBeNull();
  });

  it('accepts a zero score and zero questions as real values', () => {
    // Somebody who answered nothing has a real report with a real zero in it. Treating 0 as
    // missing would blank the one number the teaser exists to show.
    const lock = readReportLock({ ...LOCKED, overall_score: 0, lock_question_count: 0 });
    expect(lock?.overallScore).toBe(0);
    expect(lock?.questionCount).toBe(0);
  });
});

describe('the lock carries no part of the report', () => {
  it('exposes only the flag, the price, the deadline and the two teaser values', () => {
    /*
     * THE SMALLNESS IS THE SECURITY PROPERTY. If a locked response ever starts carrying
     * dimension scores or per-question analysis, this test is where it should be noticed —
     * the point of gating delivery is that the withheld parts never reach the browser at all,
     * so there is nothing for a determined candidate to read out of the page.
     */
    const lock = readReportLock({
      ...LOCKED,
      dimension_scores: { technical_accuracy: 71 },
      question_analysis: [{ question: 'What is a HashMap?' }],
      improvement_roadmap: [{ topic: 'Collections' }],
      strengths: ['clear explanations'],
      executive_summary: 'A solid attempt.',
    });
    expect(Object.keys(lock ?? {}).sort()).toEqual([
      'deadline',
      'itemId',
      'overallScore',
      'pricePaise',
      'questionCount',
    ]);
  });
});

describe('rupees', () => {
  it('shows whole rupees without decimals', () => {
    expect(rupees(4900)).toBe('₹49');
    expect(rupees(100)).toBe('₹1');
    expect(rupees(0)).toBe('₹0');
  });

  it('shows the paise when a coupon produces them', () => {
    // A 15%-off code on ₹49 charges ₹41.65. Rounding that to "₹42" would print a figure the
    // card statement disagrees with, which is small enough to look like a bug and big enough
    // to be one.
    expect(rupees(4165)).toBe('₹41.65');
    expect(rupees(4750)).toBe('₹47.50');
  });
});

describe('the countdown is copy, and it goes quiet', () => {
  const deadline = Date.parse('2026-08-24T10:00:00+05:30');

  it('counts down to the drive slot in IST', () => {
    // 10 am IST on the 24th, not 10 am UTC. A naive parse would expire the copy five and a
    // half hours early — at 04:30 on the morning it matters most.
    expect(deadline).toBe(Date.parse('2026-08-24T04:30:00Z'));
    expect(REPORT_UNLOCK_OFFER_DEADLINE).toBe(deadline);
  });

  it('the label and the timestamp are the same fact', () => {
    // They are two literals on purpose (formatting a date differs between the Cloudflare edge
    // runtime and the browser, and that lands as a hydration mismatch inside the one sentence
    // that must never look broken). Two literals drift, so this is the pin.
    expect(REPORT_UNLOCK_DEADLINE_LABEL).toContain('24 August');
    expect(REPORT_UNLOCK_DEADLINE_LABEL).toContain('10 am');
  });

  it('breaks the remaining time into days, hours, minutes and seconds', () => {
    const now = deadline - (2 * 86_400 + 3 * 3_600 + 4 * 60 + 5) * 1_000;
    expect(countdown(now, deadline)).toEqual({ days: 2, hours: 3, minutes: 4, seconds: 5 });
  });

  it('returns null the instant the deadline passes, and stays null', () => {
    expect(countdown(deadline, deadline)).toBeNull();
    expect(countdown(deadline + 1, deadline)).toBeNull();
    expect(countdown(deadline + 86_400_000, deadline)).toBeNull();
  });

  it('returns null for a clock or a deadline that is not a number', () => {
    expect(countdown(NaN, deadline)).toBeNull();
    expect(countdown(Date.now(), NaN)).toBeNull();
  });

  it('drops units from the top and only shows seconds inside the last day', () => {
    // A ticking seconds digit next to "2d" draws the eye to the one number that cannot
    // matter yet; in the final hour it is the entire point of a countdown.
    expect(formatCountdown({ days: 2, hours: 3, minutes: 4, seconds: 5 })).toBe('2d 03h 04m');
    expect(formatCountdown({ days: 0, hours: 3, minutes: 4, seconds: 5 })).toBe('3h 04m 05s');
    expect(formatCountdown({ days: 0, hours: 0, minutes: 4, seconds: 5 })).toBe('4m 05s');
    expect(formatCountdown({ days: 0, hours: 0, minutes: 0, seconds: 5 })).toBe('0m 05s');
  });

  it('formats nothing once there is nothing left', () => {
    // The caller renders nothing for null. The paywall is byte-for-byte the same afterwards:
    // same price, same coupon field, same unlock. This is urgency copy, not a feature flag.
    expect(formatCountdown(null)).toBeNull();
    expect(formatCountdown(countdown(deadline + 1, deadline))).toBeNull();
  });
});
