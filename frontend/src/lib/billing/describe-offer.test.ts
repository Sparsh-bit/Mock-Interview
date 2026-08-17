import { describe, expect, it } from 'vitest';

import { describeOffer } from './describe-offer';

/**
 * The Apply box's one job is to tell the candidate the code worked and roughly what it does.
 * Every case here is a way of getting that wrong that would reach a real person.
 */
describe('describeOffer', () => {
  it('names a percentage without inventing a rupee figure', () => {
    // The rupee saving differs on every item in the store, so quoting one here would be
    // wrong on all but one of them.
    expect(describeOffer({ is_free: false, kind: 'percent', value: 25 })).toBe('25% off');
    expect(describeOffer({ is_free: false, kind: 'percent', value: 100 })).toBe('100% off');
  });

  it('reads a fixed offer as the resulting price, not as a discount', () => {
    /*
     * THE MISREADING THIS EXISTS TO PREVENT. `value` on a fixed offer is the final price in
     * paise — 1900 means the item becomes ₹19. Treating it as an amount taken off would
     * advertise "₹19 off", which on a ₹19 item reads as free and is not.
     */
    expect(describeOffer({ is_free: false, kind: 'fixed', value: 1900 })).toBe(
      '₹19 with this code',
    );
    expect(describeOffer({ is_free: false, kind: 'fixed', value: 4900 })).toBe(
      '₹49 with this code',
    );
  });

  it('says free for a free code', () => {
    expect(describeOffer({ is_free: true, kind: 'free', value: 0 })).toBe(
      'Free with this code',
    );
  });

  it('says free when a percentage discount lands under the ₹1 floor', () => {
    /*
     * Razorpay will not take an order below one rupee, so the server promotes such a
     * discount to a free grant. The candidate pays nothing, and `is_free` is how we are
     * told — describing it as "95% off" would be technically derived from `kind` and
     * wrong about what happens.
     */
    expect(describeOffer({ is_free: true, kind: 'percent', value: 95 })).toBe(
      'Free with this code',
    );
  });

  it('confirms an unshaped code rather than inventing a discount', () => {
    // A code the server accepted but described with an empty kind. It is valid, so the box
    // must not imply failure; it is unknown, so the box must not imply a saving.
    expect(describeOffer({ is_free: false, kind: '', value: 0 })).toBe('Code applied');
  });

  it('never renders NaN, whatever the value is', () => {
    for (const offer of [
      { is_free: false, kind: 'fixed' as const, value: 0 },
      { is_free: false, kind: 'percent' as const, value: 0 },
    ]) {
      expect(describeOffer(offer)).not.toContain('NaN');
    }
  });
});
