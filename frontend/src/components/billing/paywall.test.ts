import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * The paywall sells the thing they were stopped on — paywall.test.ts
 *
 * THREE THINGS WERE WRONG WITH IT AND TWO WERE VISIBLE TO EVERY BLOCKED CANDIDATE.
 *
 *   "You have used all 0 mock interviews on the Free plan." Once interviews and group
 *   discussions went paid their trial allowance became 0, so the heading told somebody who had
 *   used nothing that they had used all of it. Untrue, and slightly insulting.
 *
 *   "Your allowance resets each month." There is no monthly reset and there never was. That
 *   sentence tells a blocked candidate to wait for something that will not happen — the worst
 *   possible outcome, because they neither buy nor come back to anything different.
 *
 *   "Take a free quiz instead", offered beside the buy button. Somebody who came to sit a mock
 *   interview has not been helped by a quiz, and putting it at the moment of purchase is an
 *   invitation to do the free thing instead of the thing they came for.
 *
 * And the structural one: the only route forward was a link to /pricing — leave, browse six
 * products, find the one you were already trying to use, come back. Every step is a place to
 * stop, and that gap is the whole funnel.
 */

const PAYWALL = readFileSync(
  join(process.cwd(), 'src/components/billing/Paywall.tsx'),
  'utf8',
);
const PANEL = readFileSync(
  join(process.cwd(), 'src/components/billing/BuyPanel.tsx'),
  'utf8',
);

const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
const PAYWALL_CODE = strip(PAYWALL);
const PANEL_CODE = strip(PANEL);

describe('it does not say false things to a blocked candidate', () => {
  it('never claims a monthly reset', () => {
    // The product has no monthly reset. Purchases do not expire and nothing refills.
    expect(PAYWALL_CODE).not.toMatch(/resets each month|resets monthly|每/i);
  });

  it('does not tell somebody with no allowance that they used it all', () => {
    // The zero case gets its own sentence rather than interpolating a 0 into "you have used
    // all N".
    expect(PAYWALL_CODE).toMatch(/neverHadAny/);
    expect(PAYWALL_CODE).toMatch(/info\.allowance <= 0/);
  });

  it('still shows the real number when there is one', () => {
    // It is checkable against what they remember doing, which is why it was there.
    expect(PAYWALL_CODE).toMatch(/\$\{info\.allowance\}/);
  });
});

describe('it does not send them to do something else', () => {
  it('offers no free-quiz alternative', () => {
    expect(PAYWALL_CODE).not.toMatch(/\/quiz/);
    expect(PAYWALL_CODE).not.toMatch(/free quiz/i);
  });

  it('keeps a way to the full store for anyone who wants a different product', () => {
    // Removing the quiz link must not remove the escape hatch to the bundles.
    expect(PAYWALL_CODE).toMatch(/href="\/pricing"/);
  });
});

describe('the purchase happens on the page they were stopped on', () => {
  it('the paywall embeds the buy panel for the blocked feature', () => {
    expect(PAYWALL_CODE).toMatch(/<BuyPanel feature=\{info\.feature\}/);
  });

  it('buying clears the wall so they can carry on', () => {
    // The wall exists because the SERVER refused with a 402. Once an item lands, that refusal
    // is stale.
    expect(PAYWALL_CODE).toMatch(/onPurchased/);
    expect(PANEL_CODE).toMatch(/onPurchased\?\.\(\)/);
  });

  it('nothing auto-starts after a purchase', () => {
    // Buying and starting are two decisions and the second is the candidate's. An interview
    // that began itself the moment a payment cleared would spend it without being asked.
    expect(PANEL_CODE).not.toMatch(/autostart|startInterview|beginSession/i);
  });
});

describe('the panel does not become a second implementation of what money costs', () => {
  it('prices come from the server-priced catalogue', () => {
    expect(PANEL_CODE).toMatch(/q\.prices/);
    expect(PANEL_CODE).toMatch(/charged_paise/);
  });

  it('it honours the code scope like the store does', () => {
    // An item the code does not reach keeps its full price, here as everywhere else.
    expect(PANEL_CODE).toMatch(/p\.covered/);
  });

  it('it computes no discount of its own', () => {
    // No percentage arithmetic anywhere in the panel.
    expect(PANEL_CODE).not.toMatch(/\/\s*100\s*\)\s*\*|\*\s*\(1\s*-/);
  });

  it('only a server-checked code is sent with a purchase', () => {
    // `appliedCode` is set from the quote's success handler, never straight from the input, so
    // a half-typed code cannot ride along with a checkout.
    expect(PANEL_CODE).toMatch(/checkout\.mutate\(\s*\{ itemId, code: appliedCode/);
  });

  it('an order confirmed at zero is not sent to the gateway', () => {
    expect(PANEL_CODE).toMatch(/if \(order\.granted\)/);
  });

  it('the payment is verified server-side rather than trusted from the browser', () => {
    expect(PANEL_CODE).toMatch(/verify\.mutate\(proof/);
  });
});
