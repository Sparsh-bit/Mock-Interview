/**
 * @module frontend/src/lib/api/types
 * Core type definitions for the API client abstraction.
 *
 * This file has zero intra-module imports so it can be imported safely
 * by any other file in this module without risk of circular dependencies.
 */

// ─── HTTP primitives ─────────────────────────────────────────────────────────

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

// ─── Error codes ─────────────────────────────────────────────────────────────

/**
 * Normalized error codes for all failure scenarios.
 * These codes are stable across backend and provider changes — callers
 * should branch on code, not on HTTP status, for robust error handling.
 */
export type ApiErrorCode =
  | 'NETWORK_ERROR'    // fetch threw TypeError (offline, DNS, CORS)
  | 'TIMEOUT'          // AbortController timeout fired before response
  | 'ABORTED'          // External AbortSignal cancelled the request
  | 'PARSE_ERROR'      // Response body could not be parsed as expected type
  | 'UNAUTHORIZED'     // HTTP 401
  | 'FORBIDDEN'        // HTTP 403
  | 'NOT_FOUND'        // HTTP 404
  | 'VALIDATION_ERROR' // HTTP 422
  | 'RATE_LIMITED'     // HTTP 429
  | 'SERVER_ERROR'     // HTTP 5xx
  | 'UNKNOWN';         // Catch-all for unclassified errors

// ─── Retry configuration ─────────────────────────────────────────────────────

export interface RetryConfig {
  /**
   * Total number of attempts including the first request.
   * A value of 3 means: 1 original + 2 retries.
   * @default 3
   */
  maxAttempts?: number;
  /**
   * Initial backoff delay in milliseconds before the first retry.
   * @default 500
   */
  initialDelayMs?: number;
  /**
   * Maximum backoff delay cap in milliseconds.
   * @default 10_000
   */
  maxDelayMs?: number;
  /**
   * Exponential backoff multiplier applied between retries.
   * @default 2
   */
  backoffFactor?: number;
  /**
   * HTTP status codes that trigger a retry attempt.
   * @default [429, 502, 503, 504]
   */
  retryableStatusCodes?: number[];
}

// ─── Per-request configuration ───────────────────────────────────────────────

export interface RequestConfig {
  /** Request body — serialized as JSON unless FormData */
  body?: unknown;
  /** Headers merged into the request (override defaults) */
  headers?: Record<string, string>;
  /**
   * Query parameters appended to the URL.
   * null and undefined values are omitted from the query string.
   */
  params?: Record<string, string | number | boolean | null | undefined>;
  /**
   * Timeout in milliseconds for this specific request.
   * Overrides ApiClientConfig.defaultTimeout.
   */
  timeout?: number;
  /**
   * Retry configuration for this specific request.
   * Pass false to disable retry for this request only.
   */
  retry?: RetryConfig | false;
  /**
   * External AbortSignal merged with the internal timeout signal.
   * Useful for cancelling requests when components unmount.
   */
  signal?: AbortSignal;
  /**
   * When true, the Authorization header is NOT injected for this request.
   * Use for public endpoints that don't require authentication.
   */
  skipAuth?: boolean;
  /**
   * Next.js App Router fetch options for ISR / on-demand revalidation.
   * Only has effect in Server Components and Server Actions.
   */
  next?: NextFetchRequestConfig;
  /** Standard fetch cache directive */
  cache?: RequestCache;
}

// ─── Interceptor pipeline types ──────────────────────────────────────────────

  /**
   * The canonical request shape that flows through the interceptor pipeline.
   * Interceptors receive and must return this exact structure.
   *
   * `Omit<RequestInit, 'headers'>` rather than a plain intersection. Intersecting
   * RequestInit with a stricter `headers` does not override the property, it
   * produces `(HeadersInit | undefined) & Record<string, string>` — a type that
   * is satisfiable but impossible to reconstruct by spreading, which is what
   * pushed two `as any` casts into the auth interceptor. Omitting first replaces
   * the property outright, so `{...init}` round-trips cleanly.
   */
  export interface PreparedRequest {
    url: string;
    init: Omit<RequestInit, 'headers'> & {
      headers: Record<string, string>;
      /** Internal, stripped before fetch(). Carries flags like `skipAuth`. */
      extraOptions?: Record<string, unknown>;
    };
  }

/** Normalized response wrapper returned by all ApiClient methods */
export interface ApiResponse<T = unknown> {
  data: T;
  status: number;
  ok: boolean;
  headers: Headers;
}

/**
 * Provides the bearer token for Authorization header injection.
 * May be async to support token refresh flows.
 * Return null to send the request without an Authorization header.
 */
export type TokenProvider = () => Promise<string | null> | string | null;

/**
 * Transforms the PreparedRequest before it is sent to the server.
 * Interceptors run in registration order.
 * Return the (optionally modified) PreparedRequest.
 */
export type RequestInterceptor = (
  request: PreparedRequest,
) => PreparedRequest | Promise<PreparedRequest>;

/**
 * Receives the raw Response object after a successful fetch, before parsing.
 * Useful for response logging, metrics collection, or header inspection.
 * Must return a Response (the same or a new one).
 */
export type ResponseInterceptor = (
  response: Response,
  request: PreparedRequest,
) => Response | Promise<Response>;

/**
 * Receives a normalized error before it is thrown to the caller.
 * Must return an error object — the client always re-throws the returned value.
 * Use for centralized error logging, Sentry capture, or token refresh recovery.
 */
export type ErrorInterceptor = (
  error: unknown,
  request: PreparedRequest,
) => unknown | Promise<unknown>;

// ─── Client configuration ────────────────────────────────────────────────────

export interface ApiClientConfig {
  /**
   * API base URL — no trailing slash.
   * Example: "https://api.interviewos.com" or "http://localhost:8000"
   */
  baseUrl: string;
  /**
   * Default timeout for all requests in milliseconds.
   * @default 30_000
   */
  defaultTimeout?: number;
  /**
   * Default retry configuration for all requests.
   * Pass false to disable retry globally for this client instance.
   */
  defaultRetry?: RetryConfig | false;
  /**
   * Headers merged into every request sent by this client.
   * Per-request headers in RequestConfig take precedence.
   */
  defaultHeaders?: Record<string, string>;
  /**
   * Async function providing the bearer token for authenticated requests.
   * Called before every request — always returns a fresh token.
   */
  tokenProvider?: TokenProvider;
  /** Additional request interceptors (appended after built-ins) */
  requestInterceptors?: RequestInterceptor[];
  /** Response interceptors (run in registration order) */
  responseInterceptors?: ResponseInterceptor[];
  /** Error interceptors (run in registration order before throwing) */
  errorInterceptors?: ErrorInterceptor[];
}
