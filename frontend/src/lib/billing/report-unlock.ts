/**
 * The report paywall, as pure functions — lib/billing/report-unlock.ts
 *
 * WHAT IS BEING SOLD AND WHAT IS NOT. Every FREE interview on this product is free the whole
 * way through — the questions, the panel, the voice, the follow-ups. Nothing about taking it
 * costs anything, and the paywall must keep saying so or it reads as a bait. What costs ₹49 is
 * the personalised report on a free interview: the four competency scores, the per-question
 * breakdown, the roadmap and the study resources. One session, one unlock.
 *
 * A PURCHASED INTERVIEW'S REPORT IS INCLUDED, ALWAYS. Somebody who paid for an interview has
 * already paid for its report; charging twice for one session would be indefensible. The
 * server decides which is which off the credit ledger — whether that session was drawn from
 * the free trial or from bought credit — and this module only ever reads the answer. See
 * backend/app/services/billing/report_access.py.
 *
 * GATE THE DELIVERY, NOT THE GENERATION — and this module is the browser half of that. The
 * report is generated and stored exactly as it always was; the server reduces the RESPONSE
 * when the session is locked, and this reads that reduced response. Nothing here can destroy
 * a report, because nothing here is involved in making one. Unlocking is a refetch.
 *
 * WHY THE LOGIC LIVES HERE AND NOT IN THE COMPONENT. Same reason as lib/interview/drive.ts,
 * and the same constraint: vitest runs in the `node` environment in this workspace (see
 * frontend/vitest.config.ts), so there is no DOM and a component that renders framer-motion
 * cannot be mounted in a test at all. The markup is not the part that can cost somebody
 * their report anyway. These are: whether a response is read as locked, what the price says,
 * and whether the countdown goes quiet or goes wrong. All three are pure functions over
 * values, so they live in a module with no React in it and are tested directly.
 *
 * IT FAILS OPEN, AND THAT IS THE MOST IMPORTANT SENTENCE IN THIS FILE. Read
 * `readReportLock` before changing anything here. A locked report shown to somebody who owes
 * nothing is the worst outcome available on this product and it lands on students who are
 * mid-placement-season today; a full report shown to somebody who has not paid costs ₹49.
 * Those are not comparable, so every ambiguous case resolves to "deliver".
 */

/**
 * The item id the unlock is bought as.
 *
 * MIRRORS `REPORT_UNLOCK_ITEM.id` in backend/app/services/billing/plans.py, and it is a
 * mirror rather than a decision: the server resolves the item from this id and prices it
 * from its own catalogue, so a wrong value here produces a 404 at checkout — loud, immediate,
 * and impossible to confuse with a wrong charge. The browser naming a PRICE would be the
 * dangerous version of this, and it never does; see `openCheckout`, which sends only ids.
 *
 * It is a fallback, not the primary source: `readReportLock` prefers whatever
 * `lock_item_id` the locked response names, so the server can move the item without a
 * frontend deploy. This constant is what keeps the button working if that field is absent.
 */
export const REPORT_UNLOCK_ITEM_ID = 'report_unlock_1';

/**
 * ₹49 in paise, because Razorpay bills in paise and every price in this repo is an integer.
 *
 * ALSO A FALLBACK, ALSO NOT A DECISION. The locked response carries `lock_price_paise` and that
 * figure wins whenever it is present and sane. This literal exists for one reason: a locked
 * screen must never be able to print "₹NaN" or "₹0" at the moment it is asking somebody for
 * money. Because the CHARGE is always resolved server-side from the item id — see
 * services/billing/offers.py, which is the only place a price is computed — a stale constant
 * here can misprint copy and can never mischarge a card. That asymmetry is why duplicating
 * the number is acceptable when duplicating a rule would not be.
 */
export const REPORT_UNLOCK_PRICE_PAISE = 4_900;

/*
 * THE OFFER DEADLINE IS URGENCY COPY. IT IS NOT A FEATURE FLAG.
 *
 * 10:00 on 24 August 2026, Asia/Kolkata — the drive's interview slot. When it passes, the
 * countdown goes quiet and the paywall behaves identically: same price, same coupon field,
 * same unlock, same locked report. Nothing branches on this timestamp except whether a
 * sentence is rendered.
 *
 * That rule is inherited deliberately from lib/interview/drive.ts, where the reasoning is
 * written out at length: a date that quietly changes behaviour is a once-a-year bug that
 * only ever fires on the day the product matters most, and the drifted state — a card
 * confidently advertising a deadline that has passed — tells a student nobody maintains
 * this. A phrase that goes quiet cannot do either.
 *
 * The offset is +05:30 because this is an Indian campus drive and "10 am on the 24th" means
 * 10 am where the candidate is sitting. A naive parse would expire the countdown five and a
 * half hours early, i.e. at 04:30 IST on the morning of the drive.
 *
 * EDIT THE LABEL AND THE TIMESTAMP TOGETHER OR NOT AT ALL. They are one fact in two forms,
 * kept as two literals rather than derived from each other because `toLocaleString` formats
 * differently on the Cloudflare edge runtime than in the browser, and that difference lands
 * as a hydration mismatch inside the one sentence that must never look broken.
 */
export const REPORT_UNLOCK_OFFER_DEADLINE = Date.parse('2026-08-24T10:00:00+05:30');
export const REPORT_UNLOCK_DEADLINE_LABEL = '10 am on 24 August';

/**
 * What the browser knows about a locked report.
 *
 * DELIBERATELY TINY, and the smallness is the security property rather than a style choice.
 * The locked response carries the lock flag, the price, the deadline and a two-value teaser
 * — the overall score and how many questions were asked — and nothing else. No dimension
 * scores, no per-question analysis, no roadmap, no study resources, no executive summary.
 * If a field is not on this interface it never reached the browser, so no amount of
 * dev-tools poking at a locked report reveals what was paid for.
 */
export interface ReportLock {
  /** The item to check out. Server-named where possible; see REPORT_UNLOCK_ITEM_ID. */
  itemId: string;
  /** What the unlock costs before any coupon, in paise. */
  pricePaise: number;
  /** When the urgency copy stops being true, as an epoch millisecond value. */
  deadline: number;
  /** Teaser: the one number they already know they want. Null if the server omitted it. */
  overallScore: number | null;
  /** Teaser: how much report is waiting. Null if the server omitted it. */
  questionCount: number | null;
}

/** A finite number, or null. Rejects NaN, Infinity, strings and booleans alike. */
function finiteNumber(raw: unknown): number | null {
  return typeof raw === 'number' && Number.isFinite(raw) ? raw : null;
}

/** A whole number of at least `min`, or null. */
function wholeAtLeast(raw: unknown, min: number): number | null {
  const n = finiteNumber(raw);
  if (n === null || !Number.isInteger(n) || n < min) return null;
  return n;
}

/**
 * The deadline from the response, or ours.
 *
 * Falls back rather than returning null because the countdown is copy and copy has to say
 * something or say nothing — there is no partial state worth modelling. A malformed
 * `offer_deadline` therefore shows the deadline this build was written against, which is the
 * same sentence every other client is showing.
 */
function parseDeadline(raw: unknown): number {
  if (typeof raw === 'string') {
    const parsed = Date.parse(raw);
    if (Number.isFinite(parsed)) return parsed;
  }
  return REPORT_UNLOCK_OFFER_DEADLINE;
}

/**
 * Read a report response as either "locked" or "deliver it".
 *
 * THE ONLY PLACE THE FRONTEND DECIDES A REPORT IS LOCKED. Both report screens call this and
 * neither one re-implements any part of it, because a second predicate is a second answer and
 * the two would disagree on exactly the responses that are hardest to reason about.
 *
 * IT DOES NOT DECIDE WHOSE REPORT IS PAYWALLED, and must never learn to. Whether a session was
 * a free interview or a bought one — and whether its report has already been unlocked — is
 * decided once, on the server, against the credit ledger. This function only reads the answer.
 * A browser-side guess at "was this one free" would paywall a report somebody had already paid
 * for the moment a track was renamed or a plan changed.
 *
 * WHY `=== true` AND NOT A TRUTHINESS CHECK. Everything that is not unambiguously the lock
 * flag must deliver the report: `undefined` (an older server, and every report on a
 * purchased interview), `null`, `0`, `''`, `'false'`, and — the one that motivated
 * writing it this way — the string `'false'`, which is truthy in JavaScript and would lock
 * every report the moment some serialiser stringified a boolean. Strict equality against
 * `true` has exactly one input that locks anything.
 *
 * WHY THE `try`. The contract for this paywall says that if the predicate throws, errors, or
 * cannot decide, the report is DELIVERED. A plain property read does not normally throw, but
 * "normally" is not a guarantee across a proxy, a getter, or a revoked object, and the cost
 * of being wrong is a student staring at a paywall for a report they were given for free.
 * Three lines of insurance against the whole class.
 */
export function readReportLock(report: unknown): ReportLock | null {
  try {
    if (!report || typeof report !== 'object') return null;
    const r = report as Record<string, unknown>;
    if (r.locked !== true) return null;

    /*
     * NEVER CHARGE FOR A REPORT THAT DID NOT FINISH SCORING.
     *
     * `unscored_reason` is set when generation ran out of quota, tripped a service limit,
     * timed out or could not reach the model — see the four cases the report page's
     * `UnscoredNotice` writes copy for. In every one of them the thing being sold does not
     * exist yet: there are no dimension scores, no per-question analysis and no roadmap to
     * unlock, only an explanation and a Generate-again button.
     *
     * Asking ₹49 for that is the one way this paywall could take money for nothing, and it
     * would happen at the worst possible moment — a student whose report failed to generate,
     * being asked to pay to read the failure. So an unscored response falls through to the
     * page below, which already explains what happened and offers the retry.
     *
     * The server should not be locking these in the first place. This is here because the
     * cost of the two sides disagreeing is somebody's money, and because the frontend is the
     * side that can see both fields at once.
     */
    if (typeof r.unscored_reason === 'string' && r.unscored_reason.trim() !== '') return null;

    const itemId = typeof r.lock_item_id === 'string' ? r.lock_item_id.trim() : '';

    return {
      itemId: itemId || REPORT_UNLOCK_ITEM_ID,
      // At least one rupee: Razorpay refuses an order below 100 paise, so a smaller figure
      // is not a cheap unlock, it is an unbuyable one. Falling back to the real price keeps
      // the button working instead of opening a sheet the gateway will reject.
      pricePaise: wholeAtLeast(r.lock_price_paise, 100) ?? REPORT_UNLOCK_PRICE_PAISE,
      deadline: parseDeadline(r.offer_deadline),
      overallScore: finiteNumber(r.overall_score),
      questionCount: wholeAtLeast(r.lock_question_count, 0),
    };
  } catch {
    // Fail open. See the docstring: an undecidable response is a delivered report.
    return null;
  }
}

/**
 * Paise as a rupee string.
 *
 * SHOWS THE PAISE WHEN THERE ARE ANY, unlike the `Math.round(paise / 100)` used on the
 * pricing page and in FreeOrderSheet. Those only ever render catalogue prices, which are
 * whole rupees by construction. This one also renders the total AFTER a coupon, and a
 * percentage code produces figures like 4750 paise — rounding that to "₹48" while charging
 * ₹47.50 is a page that misstates somebody's money by fifty paise, which is small enough to
 * look like a bug and big enough to be one.
 */
export function rupees(paise: number): string {
  const value = paise / 100;
  return Number.isInteger(value) ? `₹${value}` : `₹${value.toFixed(2)}`;
}

export interface Countdown {
  days: number;
  hours: number;
  minutes: number;
  seconds: number;
}

/**
 * How long is left, or null once there is none.
 *
 * `now` IS PASSED IN, NOT READ HERE, so the caller decides when the clock is read. That is
 * what lets the component read it in an effect after mount: the server-rendered HTML and the
 * first client render then agree on a paywall with no countdown in it, and only afterwards
 * does the countdown appear. Calling `Date.now()` during render would compare an edge render
 * at one instant with a browser render at another and put a hydration mismatch inside the
 * one component that is asking somebody to pay.
 *
 * NULL IS THE QUIET STATE AND CALLERS MUST RENDER NOTHING FOR IT. It covers the deadline
 * having passed, and a clock or deadline that is not a finite number at all. It does not mean
 * the offer ended — the price and the unlock are unchanged either side of the deadline.
 */
export function countdown(now: number, deadline: number): Countdown | null {
  if (!Number.isFinite(now) || !Number.isFinite(deadline)) return null;
  const remaining = deadline - now;
  if (remaining <= 0) return null;

  const totalSeconds = Math.floor(remaining / 1000);
  return {
    days: Math.floor(totalSeconds / 86_400),
    hours: Math.floor((totalSeconds % 86_400) / 3_600),
    minutes: Math.floor((totalSeconds % 3_600) / 60),
    seconds: totalSeconds % 60,
  };
}

/** Two digits, so the numbers stop jittering as they tick down. */
function pad(n: number): string {
  return n < 10 ? `0${n}` : `${n}`;
}

/**
 * The countdown as one short string, or null when there is nothing left to say.
 *
 * THE UNITS DROP OFF FROM THE TOP as the deadline approaches, and seconds only appear inside
 * the last day. A ticking seconds digit next to "2d" is noise — it draws the eye to the one
 * number that cannot matter at that distance — whereas in the final hours it is the entire
 * point of showing a countdown at all.
 */
export function formatCountdown(c: Countdown | null): string | null {
  if (!c) return null;
  if (c.days > 0) return `${c.days}d ${pad(c.hours)}h ${pad(c.minutes)}m`;
  if (c.hours > 0) return `${c.hours}h ${pad(c.minutes)}m ${pad(c.seconds)}s`;
  return `${c.minutes}m ${pad(c.seconds)}s`;
}
