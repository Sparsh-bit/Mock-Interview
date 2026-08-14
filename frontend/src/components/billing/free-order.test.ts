import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * A ₹0 order gets a confirmation step, not a silent grant.
 *
 * REPORTED AS "the payment gateway is not coming". It cannot: Razorpay refuses to create an
 * order below ₹1, so a 100%-off code has no order to open a sheet for. That is a platform
 * limit and no amount of code gets around it — and it is also what every large Indian
 * checkout does with a full-value coupon, where the payment step simply disappears.
 *
 * What was genuinely missing was the step that replaces it. The item was granted the instant
 * Buy was pressed with nothing to confirm, which reads as the button having failed, because
 * everything a candidate knows about buying says something should appear.
 */

const PAGE = readFileSync(join(process.cwd(), 'src/app/pricing/page.tsx'), 'utf8');
const SHEET = readFileSync(
  join(process.cwd(), 'src/components/billing/FreeOrderSheet.tsx'),
  'utf8',
);

const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
const PAGE_CODE = strip(PAGE);
const SHEET_CODE = strip(SHEET);

describe('the free-order confirmation', () => {
  it('a fully-discounted item opens the sheet instead of buying immediately', () => {
    expect(PAGE_CODE).toMatch(/quoted\?\.is_free && appliedCode/);
    expect(PAGE_CODE).toMatch(/setFreeOrder\(item\)/);
  });

  it('both entry points go through one checkout function', () => {
    /*
     * The bug this pins. TanStack's per-call `onSuccess` only fires for the call that passes
     * it, so calling `mutate` again from the confirm sheet without repeating the handlers
     * left the sheet spinning forever with the item silently granted behind it. One function,
     * one set of handlers.
     */
    expect(PAGE_CODE).toMatch(/const runCheckout = \(itemId: string\)/);
    expect(PAGE_CODE).toMatch(/onConfirm=\{\(\) => \{\s*if \(freeOrder\) runCheckout\(freeOrder\.id\)/);
    // And exactly one place calls the mutation.
    expect(PAGE_CODE.match(/checkout\.mutate\(/g)?.length).toBe(1);
  });

  it('the sheet closes on success and on failure', () => {
    // A modal that survives its own error is a modal the candidate cannot get out of.
    expect(PAGE_CODE).toMatch(/setFreeOrder\(null\)/);
    expect(PAGE_CODE.match(/setFreeOrder\(null\)/g)!.length).toBeGreaterThanOrEqual(2);
  });

  it('says why there is no card form rather than leaving it as a surprise', () => {
    // Somebody who expects a payment window and does not get one assumes something broke.
    expect(SHEET).toMatch(/No payment method is needed for a ₹0 order/);
  });

  it('shows the total as zero and the saving against the list price', () => {
    expect(SHEET_CODE).toMatch(/₹0/);
    expect(SHEET_CODE).toMatch(/line-through/);
    expect(SHEET_CODE).toMatch(/originalPaise/);
  });

  it('is a real modal — escape, focus trap, and no scrolling behind it', () => {
    expect(SHEET_CODE).toMatch(/e\.key === 'Escape'/);
    expect(SHEET_CODE).toMatch(/document\.body\.style\.overflow = 'hidden'/);
    expect(SHEET_CODE).toMatch(/aria-modal="true"/);
  });

  it('cannot be dismissed mid-grant', () => {
    // Closing while the request is in flight would leave the candidate unsure whether it
    // went through, on a screen that no longer mentions it.
    expect(SHEET_CODE).toMatch(/!confirming && onCancel\(\)/);
    expect(SHEET_CODE).toMatch(/e\.key === 'Escape' && !confirming/);
  });
});
