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
  key_id: string;
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
    mutationFn: async (itemId: string) => {
      const res = await getBrowserApiClient().post('/api/v1/billing/checkout', {
        item_id: itemId,
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
