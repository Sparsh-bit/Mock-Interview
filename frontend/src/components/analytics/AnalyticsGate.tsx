'use client';

/**
 * The gate — components/analytics/AnalyticsGate.tsx
 *
 * The one place that turns analytics on, and the only one. Mounted inside `Providers`, it
 * watches two things — who is signed in, and what the consent ledger says — and pushes both
 * into the analytics client. Nothing else in the app is allowed to call `setConsent`.
 *
 * ## Why the consent query is not enabled until there is a user
 *
 * `GET /legal/consent` is authenticated. Firing it on the marketing pages would produce a
 * 401 per visitor, and — more to the point — a signed-out visitor has no consent to read, so
 * the honest state for them is `unknown`, which drops every event. Analytics is therefore
 * off on every public page by construction rather than by remembering not to instrument one.
 *
 * ## Why signing out tears it down
 *
 * The vendor stores a distinct id on the device. Leaving it in place after a sign-out means
 * the next person to use that browser inherits it, and their events are attributed to the
 * previous account — the same cross-account leak `useClearCacheOnAccountChange` exists to
 * stop in the query cache, except this copy leaves the machine.
 */

import { useEffect, useState } from 'react';

import { useAnalyticsConsent } from '@/hooks/useAnalyticsConsent';
import { analytics } from '@/lib/analytics';
import { createClient } from '@/lib/supabase/client';

export function AnalyticsGate() {
  const [userId, setUserId] = useState<string | null | undefined>(undefined);

  useEffect(() => {
    const supabase = createClient();
    void supabase.auth.getUser().then(({ data }) => setUserId(data.user?.id ?? null));
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      setUserId(session?.user?.id ?? null);
    });
    return () => subscription.unsubscribe();
  }, []);

  const { data: granted, isSuccess, isError } = useAnalyticsConsent({
    enabled: Boolean(userId),
  });

  useEffect(() => {
    // `undefined` is "we have not looked yet". Signed out, or still resolving, is `unknown`:
    // no sink, nothing sent, and worth retrying — as opposed to `denied`, which is settled.
    if (!userId) {
      analytics.setConsent('unknown', null);
      return;
    }
    if (isError) {
      // A FAILED READ IS TREATED AS NO CONSENT. The alternative — carrying on with whatever
      // was last known — means a withdrawal made on another device does not take effect
      // until the request happens to succeed, which is the one direction this must never
      // fail in.
      analytics.setConsent('unknown', userId);
      return;
    }
    if (!isSuccess) return;
    // `null` is "never asked", which is not consent.
    analytics.setConsent(granted === true ? 'granted' : 'denied', userId);
  }, [userId, granted, isSuccess, isError]);

  return null;
}

export default AnalyticsGate;
