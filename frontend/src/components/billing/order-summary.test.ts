import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * Every order gets a summary before anything is charged — order-summary.test.ts
 *
 * THIS BEGAN AS THE FREE-ORDER TEST, and the bug it was written for is still pinned below.
 * Reported as "the payment gateway is not coming": it cannot, because Razorpay refuses to
 * create an order under ₹1, so a 100%-off code has no order to open a sheet for. That is a
 * platform limit. What was genuinely missing was the step that replaces it — the item was
 * granted the instant Buy was pressed, with nothing to confirm, which reads as the button
 * having failed because everything a candidate knows about buying says something should
 * appear.
 *
 * The same argument then turned out to apply to a PAID order, which went straight to a card
 * form carrying an amount and no statement of what was being bought or whether the code had
 * come off. So the sheet is now the invoice for both, and the gateway is what varies behind
 * it. These tests moved with it.
 *
 * THE INVARIANT THAT MATTERS MOST IS THE SINGLE `checkout.mutate`. TanStack's per-call
 * `onSuccess` fires only for the call that passes it, so a second `mutate` from the confirm
 * sheet without repeating the handlers left the sheet spinning forever while the item was
 * silently granted behind it. One function, one set of handlers, both paths.
 */

const PAGE = readFileSync(join(process.cwd(), 'src/app/pricing/page.tsx'), 'utf8');
const SHEET = readFileSync(
  join(process.cwd(), 'src/components/billing/OrderSummarySheet.tsx'),
  'utf8',
);

const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
const PAGE_CODE = strip(PAGE);
const SHEET_CODE = strip(SHEET);

describe('the confirmation step', () => {
  it('pressing Buy opens the summary rather than checking out immediately', () => {
    // The old code only did this for a ₹0 total and handed everything else straight to the
    // gateway. Both paths now stop here first.
    expect(PAGE_CODE).toMatch(/const buy = \(itemId: string\) => \{/);
    expect(PAGE_CODE).toMatch(/setPendingOrder\(item\);/);
  });

  it('nothing checks out until the summary is confirmed', () => {
    // `buy` must not call runCheckout at all — if it does, the summary is decorative and the
    // candidate is charged before seeing what they are buying.
    const at = PAGE_CODE.indexOf('const buy = (itemId: string)');
    const body = PAGE_CODE.slice(at, PAGE_CODE.indexOf('\n  };', at));
    expect(body).not.toMatch(/runCheckout\(/);
  });

  it('confirming is what checks out', () => {
    expect(PAGE_CODE).toMatch(
      /onConfirm=\{\(\) => \{\s*if \(pendingOrder\) runCheckout\(pendingOrder\.id\);/,
    );
  });

  it('there is exactly ONE checkout.mutate in the page', () => {
    // The bug this guards is real and was expensive: a second, un-handled mutate left the
    // sheet spinning while the item was granted behind it.
    expect((PAGE_CODE.match(/checkout\.mutate\(/g) ?? []).length).toBe(1);
  });

  it('the checkout call is extracted so both paths share its handlers', () => {
    expect(PAGE_CODE).toMatch(/const runCheckout = \(itemId: string\)/);
  });

  it('the sheet is closed on both outcomes', () => {
    // Left open, a granted order sits behind a modal that will not go away; left open on
    // error, the candidate cannot get back to the page to try again.
    expect((PAGE_CODE.match(/setPendingOrder\(null\)/g) ?? []).length).toBeGreaterThanOrEqual(2);
  });
});

describe('the invoice tells the truth about the money', () => {
  it('the total comes from the server, not from arithmetic in the sheet', () => {
    // A summary that computed its own discount would be a second implementation of what money
    // costs, on the one screen that promises it.
    expect(SHEET_CODE).toMatch(/chargedPaise/);
    expect(PAGE_CODE).toMatch(/chargedPaise=\{/);
  });

  it('the struck-through price is the item\'s own, never the quote\'s', () => {
    // It read `quoted.original_paise` once — the price of whatever item the Apply box happened
    // to validate against — so the sheet struck through ₹19 while granting the ₹199 five-pack.
    expect(PAGE_CODE).toMatch(/originalPaise=\{pendingOrder\?\.price_paise \?\? 0\}/);
  });

  it('an item the code does not cover falls back to its list price', () => {
    // `covered` is the server's answer to "does this code reach this item". Ignoring it would
    // put a discounted total on an invoice the till is about to refuse.
    expect(PAGE_CODE).toMatch(/priceFor\(pendingOrder\.id\)\?\.covered/);
  });

  it('no saving is claimed when nothing came off', () => {
    // Striking through a price that did not change is a discount claimed where none was given.
    //
    // TIGHTENED AFTER A MUTATION SURVIVED IT. This asserted `/savedRupees > 0/` anywhere in the
    // file, which the struck-through class ternary also satisfies — so removing the guard from
    // the DISCOUNT ROW itself left the test green while the invoice showed a "−₹0" line under
    // a code that took nothing off. The row's own condition is what has to be pinned.
    expect(SHEET_CODE).toMatch(/\{code && savedRupees > 0 && \(/);
  });

  it('the total and the saving are derived from the same two numbers', () => {
    expect(SHEET_CODE).toMatch(/const listRupees = Math\.round\(originalPaise \/ 100\)/);
    expect(SHEET_CODE).toMatch(/const totalRupees = Math\.round\(chargedPaise \/ 100\)/);
    expect(SHEET_CODE).toMatch(/listRupees - totalRupees/);
  });
});

describe('a zero-rupee order is handled as a platform limit, not an error', () => {
  it('the sheet knows when there is nothing to pay', () => {
    expect(SHEET_CODE).toMatch(/const isFree = chargedPaise <= 0;/);
  });

  it('it says the payment window is skipped rather than leaving it a surprise', () => {
    expect(SHEET).toMatch(/payment window is skipped/);
  });

  it('a granted order does not try to open the gateway', () => {
    // Razorpay cannot open below ₹1; calling it would show a payment form for ₹0.
    expect(PAGE_CODE).toMatch(/if \(order\.granted\)/);
  });
});

describe('the sheet is a real modal', () => {
  it('escape closes it and focus is trapped and returned', () => {
    expect(SHEET_CODE).toMatch(/'Escape'/);
    expect(SHEET_CODE).toMatch(/aria-modal="true"/);
    expect(SHEET_CODE).toMatch(/previouslyFocused\?\.focus\?\.\(\)/);
  });

  it('the page behind it does not scroll', () => {
    expect(SHEET_CODE).toMatch(/document\.body\.style\.overflow = 'hidden'/);
  });

  it('it cannot be dismissed while the order is in flight', () => {
    expect(SHEET_CODE).toMatch(/!confirming && onCancel\(\)/);
  });
});
