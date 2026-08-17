/**
 * What a promo code says it does, before an item is chosen.
 *
 * The Apply box validates a code without naming an item — there is no item yet — so the
 * server answers with the OFFER (`kind` and `value`) and zeroes for the money, because a
 * price needs something to be the price of. Everything here therefore describes the code,
 * never a rupee total: the total is computed at checkout against the item actually picked.
 *
 * This is deliberately not "₹X off". Saying a figure the candidate then does not see on the
 * receipt is worse than saying nothing, and for a percentage code the figure is different on
 * every item in the store.
 */

export interface OfferShape {
  is_free: boolean;
  kind: 'percent' | 'fixed' | 'free' | '';
  value: number;
}

export function describeOffer(offer: OfferShape): string {
  // `is_free` is checked first and independently of `kind`. The server sets it for a `free`
  // code AND for any discount that lands under Razorpay's one-rupee floor, which becomes a
  // free grant rather than an order the gateway would reject. A 95%-off code on a ₹19 drill
  // is one of those, and telling that candidate "95% off" when they will be charged nothing
  // is a worse description than "free".
  if (offer.is_free || offer.kind === 'free') {
    return 'Free with this code';
  }

  if (offer.kind === 'percent') {
    return `${offer.value}% off`;
  }

  if (offer.kind === 'fixed') {
    // `value` on a fixed offer is the FINAL PRICE in paise, not the amount taken off —
    // that is how the offer row stores it, and reading it as a discount would advertise
    // ₹49 off a ₹49 item as free. Phrased as the resulting price for the same reason.
    return `₹${Math.round(offer.value / 100)} with this code`;
  }

  // An empty kind means the server validated the code but told us nothing about its shape.
  // The code is good, so the box should confirm it; inventing a discount would not.
  return 'Code applied';
}
