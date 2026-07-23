/**
 * @module frontend/src/lib/api/browser
 * Browser-side ApiClient factory and singleton for Client Components.
 *
 * The singleton re-reads the Supabase session token on every request, so it
 * handles token refresh transparently without needing to recreate the client.
 *
 * @example
 * // In a Client Component or TanStack Query function:
 * import { getBrowserApiClient } from '@/lib/api';
 *
 * const api = getBrowserApiClient();
 * const { data } = await api.get<Session[]>('/api/v1/interview/sessions');
 *
 * @example
 * // With TanStack Query:
 * export function useInterviewSessions() {
 *   return useQuery({
 *     queryKey: ['interview', 'sessions'],
 *     queryFn: () => getBrowserApiClient().get('/api/v1/interview/sessions').then(r => r.data),
 *   });
 * }
 */

import { createBrowserClient } from '@supabase/ssr';
import { ApiClient } from './client';
import { createLoggingInterceptor } from './interceptors';
import type { ApiClientConfig } from './types';

/**
 * Creates a new ApiClient instance configured for browser use.
 * Prefer getBrowserApiClient() for singleton access in most cases.
 * Use this factory only when you need a separate instance with custom config.
 */
export function createBrowserApiClient(
  overrides?: Partial<ApiClientConfig>,
): ApiClient {
  // createBrowserClient is internally memoized by @supabase/ssr
  const supabase = createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  );

  const tokenProvider = async (): Promise<string | null> => {
    const {
      data: { session },
    } = await supabase.auth.getSession();
    return session?.access_token ?? null;
  };

  return new ApiClient({
    baseUrl: process.env.NEXT_PUBLIC_API_URL!,
    tokenProvider,
    requestInterceptors: [createLoggingInterceptor()],
    ...overrides,
  });
}

// ─── Singleton ────────────────────────────────────────────────────────────────

let _singleton: ApiClient | null = null;

/**
 * Returns the shared ApiClient singleton for Client Components.
 *
 * The singleton is lazily created on first call and reused thereafter.
 * The tokenProvider is called on every request, so token refresh is handled
 * transparently — there is no stale token risk with the singleton pattern.
 *
 * Do NOT call this during SSR. In Server Components, use createServerApiClient().
 */
export function getBrowserApiClient(): ApiClient {
  if (!_singleton) {
    _singleton = createBrowserApiClient();
  }
  return _singleton;
}
