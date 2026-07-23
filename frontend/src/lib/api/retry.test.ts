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
