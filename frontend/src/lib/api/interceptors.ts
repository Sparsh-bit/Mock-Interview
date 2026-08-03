/**
 * @module frontend/src/lib/api/interceptors
 * Built-in interceptor factories for the ApiClient pipeline.
 *
 * All interceptors are pure functions that accept a PreparedRequest and
 * return a (possibly modified) PreparedRequest. They are composable —
 * register as many as needed via ApiClientConfig.requestInterceptors.
 */

import type { RequestInterceptor, TokenProvider, PreparedRequest } from './types';

// ─── Built-in interceptors (auto-registered by ApiClient) ────────────────────

/**
 * Injects the Authorization: Bearer <token> header using the provided
 * async token provider. Called before every request so tokens are always fresh.
 *
 * Automatically registered by ApiClient when tokenProvider is configured.
 * Do not register manually — it would double-inject the header.
 *
 * Skips auth injection when the request config sets skipAuth: true.
 */
export function createAuthInterceptor(tokenProvider: TokenProvider): RequestInterceptor {
  return async (request) => {
    // No casts needed: PreparedRequest.init already declares `extraOptions`.
    // Two `as any` used to sit here, casting away a type that was already
    // correct — which also meant a typo in `extraOptions` would have compiled.
    if (request.init.extraOptions?.skipAuth) {
      // Strip the marker before it reaches fetch(), which would otherwise
      // receive an option it does not understand.
      const { extraOptions: _drop, ...rest } = request.init;
      return { ...request, init: rest };
    }

    const token = await tokenProvider();
    if (!token) return request;

    return {
      ...request,
      init: {
        ...request.init,
        headers: {
          ...request.init.headers,
          Authorization: `Bearer ${token}`,
        },
      },
    };
  };
}

/**
 * Attaches a unique X-Request-ID header for end-to-end distributed tracing.
 * The backend stores this in audit_logs.request_id for correlation.
 *
 * Automatically registered by ApiClient — do not register manually.
 */
export function createRequestIdInterceptor(): RequestInterceptor {
  return (request) => ({
    ...request,
    init: {
      ...request.init,
      headers: {
        ...request.init.headers,
        'X-Request-ID': crypto.randomUUID(),
      },
    } as PreparedRequest['init'],
  });
}

// ─── Optional opt-in interceptors ────────────────────────────────────────────

/**
 * Development-only request logger.
 * Logs method + URL to console in development; no-op in production.
 *
 * Register manually in createServerApiClient / createBrowserApiClient:
 *   requestInterceptors: [createLoggingInterceptor()]
 */
export function createLoggingInterceptor(): RequestInterceptor {
  return (request) => {
    if (process.env.NODE_ENV === 'development') {
      const method = (request.init.method ?? 'GET').padEnd(6);
      console.debug(`→ [API] ${method} ${request.url}`);
    }
    return request;
  };
}

/**
 * Injects a static custom header into every request.
 * Useful for API versioning, tenant ID, or feature-flag overrides.
 *
 * @example
 * requestInterceptors: [createHeaderInterceptor('X-Api-Version', '2025-01')]
 */
export function createHeaderInterceptor(
  header: string,
  value: string,
): RequestInterceptor {
  return (request) => ({
    ...request,
    init: {
      ...request.init,
      headers: {
        ...request.init.headers,
        [header]: value,
      },
    },
  });
}
