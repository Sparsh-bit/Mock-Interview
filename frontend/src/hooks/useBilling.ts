'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { getBrowserApiClient } from '@/lib/api';

/**
 * Plan, balance and checkout — hooks/useBilling.ts
 *
 * THIS IS FOR DISPLAY, NOT FOR ENFORCEMENT. Everything here reads what the server already
 * decided; nothing here decides anything. The balance tells the UI how many interviews to
 * show as remaining and when to put the upgrade sheet in front of somebody BEFORE they start
 * something — but a client that ignores all of it still cannot exceed its allowance, because
 * `consume` re-checks under a row lock inside each metered endpoint's own transaction.
 *
 * That separation is the point. A paywall that is also the enforcement is one `curl` away
 * from not existing.
 */

export interface FeatureBalance {
  feature: string;
  /** Plural, human-readable: "mock interviews". Comes from the server so the copy cannot drift. */
  label: string;
  used: number;
  allowance: number;
  remaining: number;
  unlimited: boolean;
}

export interface Balance {
  plan_id: string;
  plan_name: string;
  period_start: string;
  period_end: string;
  features: FeatureBalance[];
}

export interface Plan {
  id: string;
  name: string;
  price_rupees: number;
  price_paise: number;
  tagline: string;
  allowances: Record<string, number>;
  highlights: string[];
  is_free: boolean;
}

/**
 * What this user is on and what they have left.
 *
 * `staleTime` is short because the number changes as a direct result of things the user just
 * did — finishing an interview should not leave "2 remaining" on screen. Refetched on window
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
    // `enabled` exists for the PUBLIC pricing page, which renders for logged-out visitors.
    // /billing/me is authenticated, so asking without a session is a guaranteed 401 — a
    // console error on the one page whose job is to look trustworthy to somebody about to
    // enter card details. Defaults to on, so every authenticated caller is unaffected.
    enabled: options?.enabled ?? true,
  });
}

/** The catalogue. Public, and it never changes within a session. */
export function usePlans() {
  return useQuery({
    queryKey: ['billing', 'plans'],
    queryFn: async () => {
      const res = await getBrowserApiClient().get('/api/v1/billing/plans');
      return res.data as Plan[];
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
  plan_id: string;
  /** The PUBLIC key id. The secret never leaves the server. */
  key_id: string;
}

/**
 * Open a Razorpay order.
 *
 * Sends only the plan ID. The amount is resolved server-side from the plan — a
 * client-supplied price is the oldest bug in online payments, and Razorpay would happily
 * accept ₹1 for Pro if we let the browser name the figure.
 *
 * Invalidates the balance on success so the new allowance appears without a reload. That is
 * optimistic about webhook timing — the plan only actually changes when Razorpay's webhook
 * lands — so the refetch may briefly still show the old plan. Correct, if slightly behind, is
 * the right failure here: showing Pro before the payment is confirmed would be the other way.
 */
export function useCheckout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (planId: string) => {
      const res = await getBrowserApiClient().post('/api/v1/billing/checkout', {
        plan_id: planId,
      });
      return res.data as CheckoutOrder;
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['billing', 'balance'] });
    },
  });
}
