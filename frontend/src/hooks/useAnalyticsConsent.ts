'use client';

/**
 * Reading and changing the analytics consent — hooks/useAnalyticsConsent.ts
 *
 * READ FROM THE SERVER, NEVER REMEMBERED IN THE BROWSER. The same rule and the same reason
 * as `useResumeConsent`: localStorage would survive a withdrawal made on another device and
 * would be wrong in the direction that matters — tracking somebody who has said stop. The
 * consent ledger is the only thing that knows.
 *
 * `null` MEANS NEVER ASKED, WHICH IS NOT CONSENT. It is kept distinct from an explicit
 * refusal so the settings toggle can tell "off because they said no" from "off because we
 * have not asked", and so a failed read behaves as denied rather than as granted.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { getBrowserApiClient } from '@/lib/api/browser';

/** The purpose string, matching `PURPOSE_ANALYTICS` in backend models/consent.py. */
export const ANALYTICS_PURPOSE = 'analytics';

interface ConsentRow {
  purpose: string;
  granted: boolean | null;
}

/**
 * Every consent on this account, as the server sees it.
 *
 * SHARES THE `['legal', 'consent']` QUERY KEY with `useResumeConsent`, deliberately: it is
 * the same endpoint returning the same list, and two cache entries for one response is two
 * chances for the page to show one answer while the server holds another. The two hooks
 * select different rows out of one fetch.
 */
export function useAnalyticsConsent(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: ['legal', 'consent'],
    // OFF UNTIL THERE IS SOMEBODY TO ASK ABOUT. This endpoint is authenticated, so on a
    // public page it is a 401 per visitor — and a signed-out visitor has no consent to
    // read, which makes `unknown` the honest state rather than a state to fetch.
    enabled: options?.enabled ?? true,
    queryFn: async () => {
      const api = getBrowserApiClient();
      const res = await api.get<{ consents: ConsentRow[] }>('/api/v1/legal/consent');
      return res.data.consents;
    },
    staleTime: 5 * 60 * 1000,
    select: (consents: ConsentRow[]) =>
      consents.find((c) => c.purpose === ANALYTICS_PURPOSE)?.granted ?? null,
  });
}

/**
 * Give or withdraw the analytics consent.
 *
 * ONE ENDPOINT FOR BOTH DIRECTIONS — `POST /legal/consent` with `granted: false` — because
 * §6(4) requires withdrawal to be as easy as giving. A separate withdrawal flow behind a
 * support ticket is the thing that rule exists to forbid.
 *
 * Invalidates the shared consent query on success, which is what makes `AnalyticsGate` tear
 * the sink down within one render of the switch being turned off.
 */
export function useSetAnalyticsConsent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (granted: boolean) => {
      const api = getBrowserApiClient();
      await api.post('/api/v1/legal/consent', {
        purpose: ANALYTICS_PURPOSE,
        granted,
      });
      return granted;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['legal', 'consent'] });
    },
  });
}
