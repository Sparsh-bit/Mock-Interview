/**
 * @module frontend/src/lib/api/retry
 * Exponential backoff retry strategy with full jitter.
 *
 * Algorithm: https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/
 * Full jitter prevents retry thundering herds in multi-client scenarios.
 */

import type { RetryConfig } from './types';
import { ApiError } from './errors';

// ─── Defaults ────────────────────────────────────────────────────────────────

export const DEFAULT_RETRY_CONFIG = {
  maxAttempts: 3,
  initialDelayMs: 500,
  maxDelayMs: 10_000,
  backoffFactor: 2,
  retryableStatusCodes: [429, 502, 503, 504],
} as const satisfies Required<RetryConfig>;

// ─── Config helpers ──────────────────────────────────────────────────────────

/**
 * Merges a partial RetryConfig override with a base config.
 * Returns false if retry is explicitly disabled.
 */
export function mergeRetryConfig(
  override?: RetryConfig | false,
  base: Required<RetryConfig> = DEFAULT_RETRY_CONFIG,
): Required<RetryConfig> | false {
  if (override === false) return false;
  if (override === undefined) return base;
  return { ...base, ...override };
}

// ─── Retry decision ───────────────────────────────────────────────────────────

/**
 * Determines whether a failed request should be retried.
 *
 * Retry policy:
 * - Never retry aborted requests (user-cancelled)
 * - Never retry 4xx errors except those in retryableStatusCodes (e.g., 429)
 * - Always retry network blips, once
 * - Always retry timeouts, up to maxAttempts
 * - Always retry retryableStatusCodes (429, 502–504)
 * - Respect the maxAttempts ceiling unconditionally
 */
/**
 * HTTP methods that are safe to replay. Everything else may have already been
 * applied server-side even though we never saw the response.
 */
const IDEMPOTENT_METHODS = new Set(['GET', 'HEAD', 'OPTIONS', 'PUT', 'DELETE']);

export function shouldRetry(
  error: unknown,
  attempt: number,
  config: Required<RetryConfig>,
  method?: string,
): boolean {
  if (attempt >= config.maxAttempts) return false;

  // Never replay a non-idempotent request that timed out or 5xx'd. The server
  // may still be working on the first one — and for our AI endpoints (report
  // generation, interview plans) each replay starts a fresh, separately BILLED
  // model call. Retrying a slow report was silently costing multiples of one
  // report. A 429 is still safe: it means the request was rejected, not run.
  if (
    method &&
    !IDEMPOTENT_METHODS.has(method.toUpperCase()) &&
    error instanceof ApiError &&
    error.status !== 429
  ) {
    return false;
  }

  if (error instanceof ApiError) {
    // Never retry user-cancelled requests
    if (error.isAborted) return false;

    // Status-code override list (e.g., 429, 503)
    if (config.retryableStatusCodes.includes(error.status)) return true;

    // One retry for transient network issues
    if (error.isNetworkError) return attempt < 1;

    // Timeout is retryable up to the attempt ceiling
    if (error.isTimeout) return true;

    // All other 4xx errors are terminal (bad request, auth, not found, etc.)
    if (error.status >= 400 && error.status < 500) return false;

    // 5xx server errors are retryable unless excluded above
    if (error.status >= 500) return true;
  }

  return false;
}

// ─── Delay calculation ───────────────────────────────────────────────────────

/**
 * Calculates the next retry delay using full-jitter exponential backoff.
 *
 * If the response includes a Retry-After header (seconds), that value
 * takes precedence — capped at maxDelayMs.
 */
export function calculateDelay(
  attempt: number,
  config: Required<RetryConfig>,
  retryAfterHeader?: string | null,
): number {
  // Respect server-specified delay
  if (retryAfterHeader) {
    const serverDelay = parseFloat(retryAfterHeader);
    if (!Number.isNaN(serverDelay) && serverDelay > 0) {
      return Math.min(serverDelay * 1_000, config.maxDelayMs);
    }
  }

  // Full jitter: random value in [0, min(cap, maxDelay)]
  const exponentialCap = Math.min(
    config.maxDelayMs,
    config.initialDelayMs * Math.pow(config.backoffFactor, attempt),
  );
  return Math.random() * exponentialCap;
}

// ─── Sleep ───────────────────────────────────────────────────────────────────

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
