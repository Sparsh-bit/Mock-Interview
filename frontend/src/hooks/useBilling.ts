'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { getBrowserApiClient } from '@/lib/api';
import { EVENTS, track } from '@/lib/analytics';
import type { PaymentsResponse } from '@/lib/billing/receipt';


/**
 * The store and the balance — hooks/useBilling.ts
 *
 * THIS IS FOR DISPLAY, NOT FOR ENFORCEMENT. Everything here reads what the server already
 * decided; nothing here decides anything. The balance tells the UI how many interviews to
 * show as remaining and when to put the store in front of somebody BEFORE they start
 * something — but a client that ignores all of it still cannot start what it has not paid
 * for, because `consume` re-checks under a row lock inside each metered endpoint's own
 * transaction.
 *
 * That separation is the point. A paywall that is also the enforcement is one `curl` away
 * from not existing.
 */

export interface FeatureBalance {
  feature: string;
  /** Plural, human-readable: "mock interviews". From the server so the copy cannot drift. */
  label: string;
  /** Trial allowance plus everything bought. */
  granted: number;
  used: number;
  remaining: number;
  /**
   * How many of `granted` came from the free trial rather than a purchase.
   *
   * Lets the client tell a FREE attempt from a paid one, which `granted` alone cannot —
   * "your free interview will be wasted" is true for somebody on the trial and simply wrong
   * for somebody who bought a five-pack. Served rather than assumed so the wording moves with
   * the allowance.
   */
  trial_allowance: number;
}

export interface Balance {
  features: FeatureBalance[];
  /** True once the account has consumed anything — drives "your free trial" copy. */
  trial_started: boolean;
  /** Operator account: not metered. Shown as unlimited rather than as a stuck countdown. */
  unlimited: boolean;
  /** Whether this account may see the admin pages. Never what grants access — the server
   *  gates every admin endpoint with its own dependency and returns 403 regardless. */
  is_admin: boolean;
}

export interface StoreItem {
  id: string;
  feature: string;
  quantity: number;
  price_rupees: number;
  price_paise: number;
  name: string;
  tagline: string;
  /**
   * How many of this feature a brand-new account gets free.
   *
   * SERVED RATHER THAN WRITTEN DOWN, because the page spent weeks advertising a free mock
   * interview and a free group discussion after both went paid — the free-tier strip was a
   * sentence typed into a component while plans.py said zero. A number that only exists on
   * the server cannot drift from the server.
   */
  trial_allowance: number;
  /** Plural, from the server, so the strip's wording moves with the catalogue. */
  feature_label: string;
  feature_label_singular: string;
}

/** One item's price under one applied code. See the backend's `_priced_catalogue`. */
export interface ItemPrice {
  item_id: string;
  feature: string;
  original_paise: number;
  charged_paise: number;
  is_free: boolean;
  /** False when the code's scope does not reach this item — it keeps its full price. */
  covered: boolean;
}

/**
 * What this account has left.
 *
 * `staleTime` is short because the number changes as a direct result of things the user just
 * did — finishing an interview should not leave "1 remaining" on screen. Refetched on window
 * focus for the same reason: a second tab is the most common way this goes stale.
 */
export function useBalance(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: ['billing', 'balance'],
    queryFn: async () => {
      const res = await getBrowserApiClient().get('/api/v1/billing/me');
      return res.data as Balance;
    },
    staleTime: 30_000,
    refetchOnWindowFocus: true,
    // `enabled` exists for the PUBLIC store page, which renders for logged-out visitors.
    // /billing/me is authenticated, so asking without a session is a guaranteed 401 — a
    // console error on the one page whose job is to look trustworthy to somebody about to
    // enter card details. Defaults to on, so every authenticated caller is unaffected.
    enabled: options?.enabled ?? true,
  });
}

/** The catalogue. Public, and it never changes within a session. */
export function useStoreItems() {
  return useQuery({
    queryKey: ['billing', 'items'],
    queryFn: async () => {
      const res = await getBrowserApiClient().get('/api/v1/billing/items');
      return res.data as StoreItem[];
    },
    staleTime: Infinity,
  });
}

/** Convenience: the balance for one feature, or null while loading. */
export function useFeatureBalance(feature: string): FeatureBalance | null {
  const { data } = useBalance();
  return data?.features.find((f) => f.feature === feature) ?? null;
}

export interface CheckoutOrder {
  order_id: string;
  amount_paise: number;
  currency: string;
  item_id: string;
  /** The PUBLIC key id. The secret never leaves the server. */
  key_id: string | null;
  /**
   * True when a 100%-off code granted the item outright and no payment happened.
   *
   * Razorpay has a ₹1 minimum, so a free item cannot be expressed as an order at all. The
   * caller must NOT open the checkout widget in this case — there is nothing to pay.
   */
  granted?: boolean;
  /** List price before the discount, so the UI can show what was saved. */
  original_paise?: number;
  /** The code that was applied, echoed back. */
  code?: string;
}

/**
 * Open a Razorpay order for one item.
 *
 * Sends only the item id. The amount is resolved server-side from the catalogue — a
 * client-supplied price is the oldest bug in online payments, and Razorpay would happily
 * accept ₹1 for five interviews if we let the browser name the figure.
 *
 * Invalidates the balance on success so new items appear without a reload. That is
 * optimistic about webhook timing — entitlement only actually changes when Razorpay's
 * webhook lands — so the refetch may briefly still show the old number. Correct but
 * slightly behind is the right failure here; showing the items before the payment is
 * confirmed would be the other way.
 */
export function useCheckout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (args: {
      itemId: string;
      code?: string;
      captchaToken?: string;
      /**
       * The interview session a report unlock is for.
       *
       * REQUIRED FOR THE UNLOCK TO DO ANYTHING. Report access is decided by finding a grant
       * whose session_id matches the report being opened, so a purchase that names no session
       * succeeds, takes the money, and leaves the report locked. Omitted for every other
       * item, where a credit belongs to the account rather than to one session.
       */
      sessionId?: string;
    }) => {
      const res = await getBrowserApiClient().post('/api/v1/billing/checkout', {
        item_id: args.itemId,
        session_id: args.sessionId ?? null,
        // The CODE, never a price. The server resolves the offer and computes the charge —
        // see services/billing/offers.py. A discount named by the browser is the same bug
        // as a price named by the browser.
        code: args.code ?? '',
        captcha_token: args.captchaToken ?? '',
      });
      return res.data as CheckoutOrder;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['billing', 'balance'] });
    },
  });
}


/**
 * Check a promo code against an item without committing to anything.
 *
 * Deliberately reuses the checkout endpoint's validation on the server rather than adding a
 * second one: two code paths that decide whether a code is valid will disagree, and the one
 * that disagrees in the candidate's favour is the one that costs money. This asks for the
 * price; `useCheckout` asks for the price AND acts on it.
 *
 * Errors carry a message the candidate can act on — "this offer has expired" rather than
 * "invalid code", which would send them hunting for a typo that is not there.
 */
export function useQuote() {
  return useMutation({
    mutationFn: async (args: { itemId: string; code: string }) => {
      const res = await getBrowserApiClient().post('/api/v1/billing/quote', {
        item_id: args.itemId,
        code: args.code,
      });
      return res.data as {
        item_id: string;
        original_paise: number;
        charged_paise: number;
        is_free: boolean;
        requires_captcha: boolean;
        label: string;
        /*
         * WHAT THE CODE IS, rather than what it costs on one particular item.
         *
         * Sent so the Apply box can say "25% off" before anything is chosen. The paise
         * figures above are ZERO when no item was named — there is no item to price
         * against — so any UI that divides them is dividing by zero. `kind` and `value`
         * are the offer itself and are true whatever the candidate ends up buying.
         *
         * `value` means different things per kind, deliberately, because the offer row
         * does: a percentage for `percent`, and for `fixed` the final price in paise, not
         * the amount taken off.
         */
        kind: 'percent' | 'fixed' | 'free' | '';
        value: number;
        /** Item ids this code covers. Empty means every item. */
        applies_to: string[];
        /**
         * EVERY ITEM'S REAL FIGURE UNDER THIS CODE, computed server-side in one request.
         *
         * Present only on the no-item quote — the one the Apply box sends — because that is
         * the question "what does this code do to the store". It is what lets every tile show
         * a live price without the browser doing discount arithmetic (a second implementation
         * of what money costs) or firing one request per tile (against a bucket of ten an
         * hour that /quote shares with /checkout).
         */
        prices?: ItemPrice[];
      };
    },
  });
}

/**
 * Confirm a payment from the browser, so the items arrive without waiting for the webhook.
 *
 * THE WEBHOOK IS STILL THE PRIMARY PATH. This is a second, independent one, and it exists
 * because a candidate paid and received nothing: a webhook can be pointed at the wrong URL,
 * signed with the wrong secret, blocked by a network, or simply late, and every one of those
 * looks the same to the person who has just been charged.
 *
 * NOTHING IS TRUSTED FROM HERE. The server checks Razorpay's signature over the ids, then
 * asks Razorpay directly whether the payment was captured and for how much, then checks that
 * amount against the item — and the ledger makes whichever of the two paths arrives second a
 * no-op. See POST /billing/verify.
 */
export function useVerifyPayment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (proof: {
      razorpay_payment_id: string;
      razorpay_order_id: string;
      razorpay_signature: string;
    }) => {
      const res = await getBrowserApiClient().post('/api/v1/billing/verify', proof);
      return res.data as { status: string; item_id?: string; quantity?: number };
    },
    onSuccess: (data) => {
      /*
       * PURCHASE AND REPEAT PURCHASE ARE ONE EVENT WITH A FLAG. `is_repeat` is read from the
       * payments cache BEFORE it is invalidated two lines down — after that, this purchase
       * is in the list and every purchase looks like a repeat.
       *
       * NO RAZORPAY IDS. `razorpay_payment_id` and `razorpay_order_id` identify a real
       * financial transaction and are the join key into the payment provider; the vendor has
       * no use for them, and a leak of the analytics export would otherwise be a leak of
       * somebody's payment references. `item_id` is a catalogue key from plans.py and
       * `price_paise` is what the server charged — neither says anything about the person.
       */
      const priorPayments =
        qc.getQueryData<{ payments?: unknown[] }>(['billing', 'payments'])?.payments?.length ??
        0;
      const item = qc
        .getQueryData<{ items?: StoreItem[] }>(['billing', 'items'])
        ?.items?.find((i) => i.id === data.item_id);
      track(EVENTS.PURCHASE, {
        ...(data.item_id ? { item_id: data.item_id } : {}),
        ...(data.quantity ? { quantity: data.quantity } : {}),
        ...(item ? { feature: item.feature, price_paise: item.price_paise } : {}),
        is_repeat: priorPayments > 0,
      });

      void qc.invalidateQueries({ queryKey: ['billing', 'balance'] });
      void qc.invalidateQueries({ queryKey: ['billing', 'payments'] });
    },
  });
}

/**
 * Every payment on this account, newest first. Read off the credit ledger.
 *
 * RETURNS THE WHOLE ENVELOPE, not just the rows. It used to unwrap `.payments` here, which
 * meant the payer's identity that the endpoint returns alongside them was thrown away at the
 * one place it could still be read — and a receipt that does not name who it was issued to is
 * a number on a page.
 *
 * BOTH SURFACES SHARE THIS ONE QUERY. The history list and the printable receipt at
 * /account/receipt/[paymentId] read the same cache entry, and the receipt selects from it with
 * `findPayment` rather than fetching one payment by id. That is deliberate: an endpoint taking
 * a payment id is an endpoint that can be handed somebody else's, and selecting out of a list
 * the server already scoped to the authenticated caller cannot show another account's payment
 * however the id is guessed. It also means the receipt can never disagree with the row it was
 * opened from, because there is only one copy of the answer.
 */
export function usePayments() {
  return useQuery({
    queryKey: ['billing', 'payments'],
    queryFn: async () => {
      const res = await getBrowserApiClient().get('/api/v1/billing/payments');
      return res.data as PaymentsResponse;
    },
  });
}

/*
 * The payment row and envelope shapes live in lib/billing/receipt.ts, next to the functions
 * that turn them into words. Re-exported here so a component importing a payment row does not
 * have to know which of the two modules holds the type, and so the previous import path keeps
 * working.
 */
export type { PaymentRecord, PaymentsResponse, Payer } from '@/lib/billing/receipt';
