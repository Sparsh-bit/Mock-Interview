import { describe, expect, it } from 'vitest';
import { ApiError } from './errors';
import { DEFAULT_RETRY_CONFIG, calculateDelay, mergeRetryConfig, shouldRetry } from './retry';

function makeError(overrides: Partial<{ status: number; code: string }> = {}): ApiError {
  const status = overrides.status ?? 500;
  const code = (overrides.code ?? 'SERVER_ERROR') as ApiError['code'];
  return new ApiError(status, code, 'test error');
}

describe('mergeRetryConfig', () => {
  it('returns false when retry is explicitly disabled', () => {
    expect(mergeRetryConfig(false)).toBe(false);
  });

  it('returns the base config when no override is given', () => {
    expect(mergeRetryConfig(undefined)).toEqual(DEFAULT_RETRY_CONFIG);
  });

  it('merges a partial override onto the base config', () => {
    const merged = mergeRetryConfig({ maxAttempts: 5 });
    expect(merged).toEqual({ ...DEFAULT_RETRY_CONFIG, maxAttempts: 5 });
  });
});

describe('shouldRetry', () => {
  const config = DEFAULT_RETRY_CONFIG;

  it('never retries once maxAttempts is reached', () => {
    const error = makeError({ status: 503 });
    expect(shouldRetry(error, config.maxAttempts, config)) .toBe(false);
  });

  it('never retries an aborted (user-cancelled) request', () => {
    const error = makeError({ code: 'ABORTED' });
    expect(shouldRetry(error, 0, config)).toBe(false);
  });

  it('retries explicitly configured retryable status codes (429)', () => {
    const error = makeError({ status: 429 });
    expect(shouldRetry(error, 0, config)).toBe(true);
  });

  it('retries a network error only once', () => {
    const error = makeError({ code: 'NETWORK_ERROR' });
    expect(shouldRetry(error, 0, config)).toBe(true);
    expect(shouldRetry(error, 1, config)).toBe(false);
  });

  it('retries timeouts up to the attempt ceiling', () => {
    const error = makeError({ code: 'TIMEOUT' });
    expect(shouldRetry(error, 0, config)).toBe(true);
    expect(shouldRetry(error, config.maxAttempts - 1, config)).toBe(true);
  });

  it('does not retry terminal 4xx errors (e.g. 404)', () => {
    const error = makeError({ status: 404 });
    expect(shouldRetry(error, 0, config)).toBe(false);
  });

  it('does not retry 401/403 auth errors', () => {
    expect(shouldRetry(makeError({ status: 401 }), 0, config)).toBe(false);
    expect(shouldRetry(makeError({ status: 403 }), 0, config)).toBe(false);
  });

  it('retries generic 5xx server errors', () => {
    const error = makeError({ status: 502 });
    expect(shouldRetry(error, 0, config)).toBe(true);
  });

  it('does not retry non-ApiError values', () => {
    expect(shouldRetry(new Error('plain error'), 0, config)).toBe(false);
  });
});

describe('calculateDelay', () => {
  const config = DEFAULT_RETRY_CONFIG;

  it('respects a valid Retry-After header, capped at maxDelayMs', () => {
    expect(calculateDelay(0, config, '2')).toBe(2000);
    expect(calculateDelay(0, config, '9999')).toBe(config.maxDelayMs);
  });

  it('ignores an invalid Retry-After header and falls back to jittered backoff', () => {
    const delay = calculateDelay(0, config, 'not-a-number');
    expect(delay).toBeGreaterThanOrEqual(0);
    expect(delay).toBeLessThanOrEqual(config.initialDelayMs);
  });

  it('produces a delay within the exponential-backoff-with-jitter bounds', () => {
    for (let attempt = 0; attempt < 5; attempt++) {
      const delay = calculateDelay(attempt, config);
      const cap = Math.min(config.maxDelayMs, config.initialDelayMs * config.backoffFactor ** attempt);
      expect(delay).toBeGreaterThanOrEqual(0);
      expect(delay).toBeLessThanOrEqual(cap);
    }
  });

  it('never exceeds maxDelayMs even at high attempt counts', () => {
    const delay = calculateDelay(20, config);
    expect(delay).toBeLessThanOrEqual(config.maxDelayMs);
  });
});

describe('shouldRetry — idempotency guard', () => {
  const config = DEFAULT_RETRY_CONFIG;

  // Replaying a non-idempotent request is not just wasteful here: the AI
  // endpoints (report generation, interview plans) start a fresh, separately
  // BILLED model call per attempt. A slow report that timed out client-side was
  // silently costing multiples of one report.
  it('never replays a POST that 5xx-ed', () => {
    expect(shouldRetry(makeError({ status: 500 }), 0, config, 'POST')).toBe(false);
  });

  it('never replays a POST that timed out', () => {
    const timeout = makeError({ status: 408, code: 'TIMEOUT' });
    expect(shouldRetry(timeout, 0, config, 'POST')).toBe(false);
  });

  it('is case-insensitive about the method', () => {
    expect(shouldRetry(makeError({ status: 503 }), 0, config, 'post')).toBe(false);
  });

  // 429 means the request was rejected before running, so replaying it cannot
  // double-charge — and backing off is the correct response.
  it('still retries a POST on 429, which was rejected rather than executed', () => {
    const rateLimited = makeError({ status: 429, code: 'RATE_LIMITED' });
    expect(shouldRetry(rateLimited, 0, config, 'POST')).toBe(true);
  });

  it('retries idempotent methods on 5xx', () => {
    for (const method of ['GET', 'HEAD', 'OPTIONS', 'PUT', 'DELETE']) {
      expect(shouldRetry(makeError({ status: 500 }), 0, config, method)).toBe(true);
    }
  });

  it('falls back to status-based behaviour when no method is supplied', () => {
    expect(shouldRetry(makeError({ status: 500 }), 0, config)).toBe(true);
  });

  it('still respects the attempt ceiling for idempotent methods', () => {
    expect(shouldRetry(makeError({ status: 500 }), config.maxAttempts, config, 'GET')).toBe(false);
  });
});
