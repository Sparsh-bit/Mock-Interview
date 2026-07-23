/**
 * @module frontend/src/lib/api/server
 * Server-side ApiClient factory for Server Components and Server Actions.
 *
 * RULES:
 * 1. NEVER import this file in Client Components — it is marked server-only.
 * 2. NEVER call createServerApiClient() at module scope — cookies() is
 *    request-scoped and must be called inside the render/action function.
 * 3. For Client Components, use getBrowserApiClient() from browser.ts instead.
 *
 * @example
 * // app/dashboard/page.tsx — Server Component
 * export default async function DashboardPage() {
 *   const api = createServerApiClient();
 *   const { data: user } = await api.get<User>('/api/v1/users/me');
 *   return <Dashboard user={user} />;
 * }
 *
 * @example
 * // app/actions/interview.ts — Server Action
 * 'use server';
 * export async function startInterview(trackId: string) {
 *   const api = createServerApiClient();
 *   return api.post('/api/v1/interview/start', { trackId });
 * }
 */

import 'server-only';

import { cookies } from 'next/headers';
import { createServerClient } from '@supabase/ssr';
import { ApiClient } from './client';
import { createLoggingInterceptor } from './interceptors';
import type { ApiClientConfig } from './types';

/**
 * Creates a request-scoped ApiClient for Server Components and Server Actions.
 *
 * Token is read from the Supabase session cookie attached to the current request.
 * The client uses the INTERNAL_API_URL env var when available (same-network, lower
 * latency), falling back to NEXT_PUBLIC_API_URL for environments without a VPC.
 *
 * @param overrides - Optional partial config to override defaults for this instance.
 */
export function createServerApiClient(
  overrides?: Partial<ApiClientConfig>,
): ApiClient {
  const tokenProvider = async (): Promise<string | null> => {
    const cookieStore = await cookies();

    const supabase = createServerClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL!,
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
      {
        cookies: {
          getAll: () => cookieStore.getAll(),
          // Server Components cannot set cookies.
          // Server Actions CAN — but we handle that in middleware, not here.
          setAll: () => {},
        },
      },
    );

    const {
      data: { session },
    } = await supabase.auth.getSession();

    return session?.access_token ?? null;
  };

  return new ApiClient({
    // Prefer INTERNAL_API_URL (private network) on the server for lower latency.
    // Falls back to the public URL for environments without a private network.
    baseUrl: process.env.INTERNAL_API_URL ?? process.env.NEXT_PUBLIC_API_URL!,
    tokenProvider,
    requestInterceptors: [createLoggingInterceptor()],
    ...overrides,
  });
}
