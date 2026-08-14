'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { getBrowserApiClient } from '@/lib/api';

/**
 * The store, the balance and the appeal — hooks/useBilling.ts
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
  is_banned: boolean;
  ban_reason: string | null;
  appeal_submitted: boolean;
}

export interface StoreItem {
  id: string;
  feature: string;
  quantity: number;
  price_rupees: number;
  price_paise: number;
  name: string;
  tagline: string;
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
    mutationFn: async (args: { itemId: string; code?: string; captchaToken?: string }) => {
      const res = await getBrowserApiClient().post('/api/v1/billing/checkout', {
        item_id: args.itemId,
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
 * Ask for a suspended account to be reviewed.
 *
 * Deliberately does not unban anything — only an admin can. This records the request, and
 * the balance query is invalidated so the UI switches to "review requested" rather than
 * leaving the form up inviting a second submission.
 */
export function useAppeal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (message: string) => {
      const res = await getBrowserApiClient().post('/api/v1/billing/appeal', { message });
      return res.data as { status: string };
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
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['billing', 'balance'] });
      void qc.invalidateQueries({ queryKey: ['billing', 'payments'] });
    },
  });
}

/** Every payment on this account, newest first. Read off the credit ledger. */
export function usePayments() {
  return useQuery({
    queryKey: ['billing', 'payments'],
    queryFn: async () => {
      const res = await getBrowserApiClient().get('/api/v1/billing/payments');
      return (res.data as { payments: PaymentRecord[] }).payments;
    },
  });
}

export interface PaymentRecord {
  id: string;
  at: string;
  /** The Razorpay payment id — the number their support and ours both index by. */
  receipt: string;
  item_id: string;
  item_name: string;
  feature: string;
  quantity: number;
  amount_paise: number;
  amount_rupees: number;
  offer: string;
  kind: string;
  paid: boolean;
}
