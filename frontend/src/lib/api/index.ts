/**
 * @module frontend/src/lib/api
 * Public API for the fetch client abstraction.
 *
 * Import everything from this barrel file — do not import from sub-modules directly.
 *
 * Usage:
 *   import { getBrowserApiClient, ApiError } from '@/lib/api';
 *   import { createServerApiClient } from '@/lib/api/server';
 */

// Core client class
export { ApiClient } from './client';

// Error class and normalization utility
export { ApiError, normalizeError } from './errors';

// Retry utilities (exposed for callers that implement custom retry logic)
export {
  DEFAULT_RETRY_CONFIG,
  shouldRetry,
  calculateDelay,
  mergeRetryConfig,
  sleep,
} from './retry';

// Interceptor factories
export {
  createAuthInterceptor,
  createRequestIdInterceptor,
  createLoggingInterceptor,
  createHeaderInterceptor,
} from './interceptors';

// Server-side factory — import only in Server Components and Server Actions directly from './server'
// Do NOT import in Client Components (enforced by server-only package)

// Browser-side factory and singleton — for Client Components
export { createBrowserApiClient, getBrowserApiClient } from './browser';

// TypeScript types
export type {
  HttpMethod,
  ApiErrorCode,
  RetryConfig,
  RequestConfig,
  PreparedRequest,
  ApiResponse,
  TokenProvider,
  RequestInterceptor,
  ResponseInterceptor,
  ErrorInterceptor,
  ApiClientConfig,
} from './types';
