import { describe, expect, it } from 'vitest';

import { ApiError, normalizeError } from './errors';

/**
 * The backend sends TWO error shapes and only one was being read.
 *
 * FastAPI's own errors are `{detail: ...}`. Everything raised as an AppError goes through
 * `_error_response` in core/exceptions.py and comes out as
 * `{error: {code, message, details}}`.
 *
 * normalizeError read only `payload.detail`, so for the entire second shape the message
 * fell back to `response.statusText` and `details` arrived as undefined. That silently
 * disabled every paywall: `consume` raises a 402 carrying `{feature, trial_used}`, the
 * paywall reads it to decide what to offer, and it was always null — so a candidate who
 * had run out got a generic toast instead of the top-up sheet.
 *
 * In the group discussion it was worse than generic. The same 402 arrives on the first
 * panel turn, so the fallback toast read "Panel could not respond", which looks like the
 * AI is broken rather than like the round needs paying for. That is how it was reported.
 */

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

describe('normalizeError reads both backend error shapes', () => {
  it('keeps the structured details from the AppError envelope', async () => {
    const err = await normalizeError(
      new Error('x'),
      jsonResponse(402, {
        error: {
          code: 'CREDITS_EXHAUSTED',
          message: 'You have used your free mock interview. Buy another to continue.',
          details: { feature: 'interview', trial_used: true },
        },
      }),
    );
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(402);
    expect(err.message).toContain('free mock interview');
    // The bug: this was undefined, so every paywall fell through to a toast.
    expect(err.creditDetails).toEqual({
      feature: 'interview',
      plan_id: 'free',
      used: 0,
      allowance: 0,
    });
  });

  it('routes a 402 to the credits-exhausted code rather than to forbidden', async () => {
    const err = await normalizeError(
      new Error('x'),
      jsonResponse(402, { error: { code: 'CREDITS_EXHAUSTED', message: 'no', details: {} } }),
    );
    expect(err.code).toBe('CREDITS_EXHAUSTED');
    expect(err.isCreditsExhausted).toBe(true);
    expect(err.isForbidden).toBe(false);
  });

  it('surfaces a ban as forbidden with its appeal flag intact', async () => {
    // A ban must NOT look like a paywall — more money does not fix it, and routing it to
    // the store would be both wrong and insulting.
    const err = await normalizeError(
      new Error('x'),
      jsonResponse(403, {
        error: {
          code: 'ACCOUNT_BANNED',
          message: 'This account is suspended.',
          details: { reason: 'two networks', appealable: true },
        },
      }),
    );
    expect(err.isForbidden).toBe(true);
    expect(err.isCreditsExhausted).toBe(false);
    expect((err.details as { appealable?: boolean }).appealable).toBe(true);
  });

  it('still reads plain FastAPI errors', async () => {
    // The fallback must keep working — bare HTTPExceptions and 422s use this shape.
    const err = await normalizeError(
      new Error('x'),
      jsonResponse(404, { detail: 'Item not found' }),
    );
    expect(err.message).toBe('Item not found');
    expect(err.status).toBe(404);
  });

  it('falls back to the status text when the body carries neither shape', async () => {
    const err = await normalizeError(new Error('x'), jsonResponse(500, { nonsense: true }));
    expect(err.status).toBe(500);
    expect(err.message).toBeTruthy();
  });
});
