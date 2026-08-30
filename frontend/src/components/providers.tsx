'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';
import { useEffect, useRef, useState } from 'react';

import { ApiError } from '@/lib/api';
import { initSentry } from '@/lib/observability/sentry';
import { createClient } from '@/lib/supabase/client';

// Some browser extensions (translate / save-page tools) inject content
// scripts that throw "Cannot find menu item with id ..." on every page —
// it's the extension's bug, not ours, but it pollutes the console. Suppress
// ONLY those exact messages so real errors are unaffected.
const EXTENSION_NOISE = /Cannot find menu item with id/i;

function useSilenceExtensionNoise() {
  useEffect(() => {
    const onRejection = (e: PromiseRejectionEvent) => {
      const msg = typeof e.reason === 'string' ? e.reason : e.reason?.message ?? '';
      if (EXTENSION_NOISE.test(msg)) {
        e.preventDefault();
        e.stopImmediatePropagation();
      }
    };
    const onError = (e: ErrorEvent) => {
      if (EXTENSION_NOISE.test(e.message ?? '')) {
        e.preventDefault();
        e.stopImmediatePropagation();
      }
    };
    window.addEventListener('unhandledrejection', onRejection, true);
    window.addEventListener('error', onError, true);
    return () => {
      window.removeEventListener('unhandledrejection', onRejection, true);
      window.removeEventListener('error', onError, true);
    };
  }, []);
}

/**
 * Throw away every cached query when the signed-in account changes.
 *
 * THE BUG THIS FIXES IS A CROSS-ACCOUNT DATA LEAK, and it is the most serious one this app
 * has had. Signing in as a second account showed the FIRST account's name, session history,
 * statistics, credit balance and admin navigation — reported as "I signed in as concilio and
 * it is opening the id sparsh", which looked like the two accounts had been merged in the
 * database. Nothing was merged. Nothing server-side was wrong at all.
 *
 * TanStack Query caches by query key, and none of the keys carry a user id: `['user-stats']`,
 * `['user-profile']`, `['user-sessions', limit]`, `['billing', 'balance']`. The QueryClient
 * is created once for the lifetime of the tab. So signing out and back in as somebody else
 * left every one of those entries in place, and each was served to the new account until it
 * happened to refetch — with `staleTime` at a minute, that is a minute of one person reading
 * another person's data, including whether they are an admin.
 *
 * WHY THE FIX IS HERE AND NOT IN THE QUERY KEYS. Adding a user id to every key would work
 * and would be wrong: it puts the burden on every hook, forever, and the failure mode for
 * forgetting is silent and is this. There are twenty query keys today and the next one added
 * would have to remember. Clearing at the identity boundary is one rule in one place that
 * cannot be forgotten, and it is correct for keys that do not exist yet.
 *
 * KEYED ON THE USER ID, NOT THE EVENT. Supabase fires `TOKEN_REFRESHED` and `SIGNED_IN`
 * routinely for the SAME user — on every tab focus, on every token refresh — and clearing the
 * cache on those would throw away good data constantly and re-fetch the whole dashboard. Only
 * a change of identity matters, so that is what is compared.
 */
function useClearCacheOnAccountChange(queryClient: QueryClient) {
  const seenUserId = useRef<string | null | undefined>(undefined);

  useEffect(() => {
    const supabase = createClient();

    const applyIdentity = (userId: string | null) => {
      // `undefined` is the first observation of the tab — there is nothing cached from
      // anybody else yet, so recording it is right and clearing would be a wasted refetch of
      // everything on every page load.
      if (seenUserId.current === undefined) {
        seenUserId.current = userId;
        return;
      }
      if (seenUserId.current === userId) return;

      seenUserId.current = userId;
      // `clear()`, not `invalidateQueries()`. Invalidating marks entries stale but KEEPS
      // them, and a stale entry is still rendered while its refetch is in flight — so the
      // new account would still see the previous one's name and numbers for as long as the
      // network takes. Removing them means the UI shows a loading state instead, which is
      // the only honest thing to show somebody whose data has not arrived yet.
      queryClient.clear();
    };

    void supabase.auth.getUser().then(({ data }) => applyIdentity(data.user?.id ?? null));

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      applyIdentity(session?.user?.id ?? null);
    });

    return () => subscription.unsubscribe();
  }, [queryClient]);
}

/**
 * Start error tracking, once per tab.
 *
 * In an effect rather than at module scope because this module is imported by the
 * server render too, and `@sentry/browser` installs global handlers on `window`.
 * `initSentry` is itself idempotent and a no-op without NEXT_PUBLIC_SENTRY_DSN, so
 * neither StrictMode's double-invoke nor an unconfigured environment does anything.
 */
function useErrorTracking() {
  useEffect(() => {
    initSentry();
  }, []);
}

export function Providers({ children }: { children: React.ReactNode }) {
  useErrorTracking();
  useSilenceExtensionNoise();
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 60 * 1000, // 1 minute
            gcTime: 5 * 60 * 1000, // 5 minutes
            // Retry once, but never for errors a retry can't fix (auth,
            // not-found, validation) -- those just double the failed
            // requests and delay showing the real error state.
            retry: (failureCount, error) => {
              if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
                return false;
              }
              return failureCount < 1;
            },
            refetchOnWindowFocus: false,
          },
          mutations: {
            retry: 0,
          },
        },
      })
  );

  useClearCacheOnAccountChange(queryClient);

  return (
    <QueryClientProvider client={queryClient}>
      {children}
      {process.env.NODE_ENV === 'development' && (
        <ReactQueryDevtools initialIsOpen={false} />
      )}
    </QueryClientProvider>
  );
}
