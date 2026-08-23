/**
 * @module frontend/src/lib/api/errors
 * ApiError class and error normalization utilities.
 */

import type { ApiErrorCode } from './types';

// ─── ApiError ────────────────────────────────────────────────────────────────

/**
 * The single error class thrown by ApiClient on any failure.
 *
 * Every failure path — network, timeout, HTTP 4xx/5xx, parse — is normalized
 * into an ApiError so callers only need to catch one type.
 *
 * @example
 * try {
 *   const { data } = await api.get<User>('/api/v1/users/me');
 * } catch (err) {
 *   if (err instanceof ApiError && err.isAuthError) {
 *     router.push('/login');
 *   }
 * }
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: ApiErrorCode;
  readonly details: unknown;
  readonly requestId: string | undefined;
  /**
   * The application's OWN error code from the envelope, e.g. `ACCOUNT_BANNED`.
   *
   * SEPARATE FROM `code`, WHICH STAYS STATUS-DERIVED. `code` is a closed union mapped from
   * the HTTP status and existing call sites switch on it; widening it would change what
   * `FORBIDDEN` means for every consumer at once. This carries the richer server value
   * additively, so nothing that reads `code` today behaves differently.
   *
   * It exists because the envelope's `code` was being thrown away — the same oversight the
   * long comment in `normalizeError` describes for `details`, and with the same consequence:
   * the client could not tell one 403 from another, so a suspended account and an ordinary
   * permission failure rendered the identical dead-end screen.
   */
  readonly serverCode: string | undefined;

  constructor(
    status: number,
    code: ApiErrorCode,
    message: string,
    details?: unknown,
    requestId?: string,
    serverCode?: string,
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
    this.serverCode = serverCode;
    // Restore prototype chain in environments that transpile classes
    Object.setPrototypeOf(this, new.target.prototype);
  }

  // ─── Semantic getters ───────────────────────────────────────────────────

  /** HTTP 401 — token missing, expired, or invalid */
  get isAuthError(): boolean { return this.status === 401; }

  /** HTTP 403 — authenticated but not authorized */
  get isForbidden(): boolean { return this.status === 403; }

  /**
   * HTTP 402 — the plan allowance for this feature is spent.
   *
   * Distinct from `isForbidden` on purpose: this one has an offer attached. `details` carries
   * `{ feature, plan_id, used, allowance }` so the paywall can name what ran out without
   * parsing the message.
   */
  get isCreditsExhausted(): boolean { return this.status === 402; }

  /** The shape the server sends with a 402, or null for any other error. */
  get creditDetails(): { feature: string; plan_id: string; used: number; allowance: number } | null {
    if (!this.isCreditsExhausted) return null;
    const d = this.details as Record<string, unknown> | null | undefined;
    if (!d || typeof d.feature !== 'string') return null;
    return {
      feature: d.feature,
      plan_id: typeof d.plan_id === 'string' ? d.plan_id : 'free',
      used: typeof d.used === 'number' ? d.used : 0,
      allowance: typeof d.allowance === 'number' ? d.allowance : 0,
    };
  }

  /**
   * HTTP 403 with a way out — the account is suspended for suspected sharing.
   *
   * DISTINCT FROM `isForbidden` FOR THE SAME REASON `isCreditsExhausted` IS. A plain 403 is a
   * dead end and offers the user nothing; this one has an appeal attached, so the client must
   * route it somewhere completely different. Collapsing them is what produced the reported
   * bug: a suspended candidate saw the generic data-error card — "this is usually temporary,
   * wait a moment and try again", which is false, with a Try again button that could never
   * succeed and no link to the appeal the message told them to find.
   *
   * KEYED ON THE CODE, NOT THE MESSAGE. The sentence lives in one place server-side
   * (AccountBannedError) and will be reworded; a client matching on prose would silently stop
   * recognising suspensions the first time somebody improved the copy, and the symptom would
   * be the dead-end screen coming back with no code change to blame.
   *
   * `details.appealable` is checked too rather than assumed, so a future suspension that is
   * genuinely not appealable — an admin ban, a chargeback — does not get pointed at a form
   * that will refuse it.
   */
  get isAccountSuspended(): boolean {
    return this.status === 403 && this.serverCode === 'ACCOUNT_BANNED';
  }

  /** Whether a suspended account may ask for review. False for any other error. */
  get isAppealable(): boolean {
    if (!this.isAccountSuspended) return false;
    const d = this.details as Record<string, unknown> | null | undefined;
    // Absent means appealable: the server has sent `appealable: true` since this existed, and
    // hiding the only route out because a field went missing is the worse way to be wrong.
    return d?.appealable !== false;
  }

  /** HTTP 404 */
  get isNotFound(): boolean { return this.status === 404; }

  /** HTTP 422 — request body failed server-side validation */
  get isValidationError(): boolean { return this.status === 422; }

  /** HTTP 429 — rate limit exceeded */
  get isRateLimited(): boolean { return this.status === 429; }

  /** HTTP 5xx */
  get isServerError(): boolean { return this.status >= 500; }

  /** Network-level failure (offline, CORS, DNS) */
  get isNetworkError(): boolean { return this.code === 'NETWORK_ERROR'; }

  /** Request exceeded the configured timeout */
  get isTimeout(): boolean { return this.code === 'TIMEOUT'; }

  /** Request was cancelled via AbortSignal */
  get isAborted(): boolean { return this.code === 'ABORTED'; }
}

// ─── Error normalization ─────────────────────────────────────────────────────

/** Shape of error payloads returned by FastAPI */
/**
 * Both error shapes this backend can send.
 *
 * `detail` is FastAPI's own (a bare HTTPException, a 422 validation error). `error` is the
 * envelope every AppError goes through — see `_error_response` in core/exceptions.py — and
 * it is the one that carries the structured `details` a paywall or a ban screen renders
 * from. Declaring only the first is how the second went unread for every AppError.
 */
interface FastApiErrorPayload {
  code?: string;
  message?: string;
  detail?: unknown;
  error?: { code?: string; message?: string; details?: unknown };
  request_id?: string;
}

/**
 * Normalizes any thrown value into an ApiError.
 *
 * Handles:
 * - Already-normalized ApiError (pass-through)
 * - DOMException AbortError (user-cancelled or timed-out request)
 * - TypeError from fetch (network failure)
 * - Non-2xx Response objects (HTTP errors with server payloads)
 * - Unknown errors (catch-all)
 *
 * @param thrown - The value caught in a catch block
 * @param response - The Response object if available (for HTTP errors)
 */
export async function normalizeError(
  thrown: unknown,
  response?: Response,
): Promise<ApiError> {
  // Already normalized — fast path
  if (thrown instanceof ApiError) return thrown;

  // Timeout: fired by our internal AbortController
  // Note: Chrome throws DOMException with name 'TimeoutError' for AbortSignal.timeout()
  if (
    thrown instanceof DOMException &&
    (thrown.name === 'AbortError' || thrown.name === 'TimeoutError')
  ) {
    return new ApiError(0, 'ABORTED', 'Request was aborted');
  }

  // Network-level failure: fetch() throws TypeError for offline/CORS/DNS
  if (thrown instanceof TypeError) {
    return new ApiError(0, 'NETWORK_ERROR', `Network error: ${thrown.message}`);
  }

  // HTTP error — extract server-provided error detail from the response body
  if (response) {
    const requestId = response.headers.get('x-request-id') ?? undefined;
    let payload: FastApiErrorPayload = {};

    try {
      const contentType = response.headers.get('content-type') ?? '';
      if (contentType.includes('application/json')) {
        // Clone prevents body-already-read errors if the response is used downstream
        payload = (await response.clone().json()) as FastApiErrorPayload;
      }
    } catch {
      // Body parse failure — fall back to status text
    }

    /*
     * THIS BACKEND SENDS TWO ERROR SHAPES, AND ONLY ONE WAS BEING READ.
     *
     * FastAPI's own errors are `{detail: ...}`. But every AppError raised by this app goes
     * through `_error_response` in core/exceptions.py, which emits an envelope:
     *
     *     {"error": {"code": "...", "message": "...", "details": {...}}}
     *
     * Only `payload.detail` was read, so for the entire second shape the message fell back
     * to `response.statusText` and `details` came through as undefined.
     *
     * That silently broke every paywall. `consume` raises a 402 carrying
     * `{feature, trial_used}` in `details`, `paywallFromError` reads it to decide what to
     * show, and it was always null — so a candidate who had run out got a generic toast
     * instead of the top-up sheet. In the group discussion, where the same 402 arrives on
     * the first panel turn, that toast read "Panel could not respond", which looks like the
     * AI is broken rather than like the round needs paying for.
     *
     * The envelope is preferred when present because it is the richer, deliberate shape;
     * `detail` remains the fallback so genuine FastAPI errors (422 validation, and anything
     * raised as a bare HTTPException) are unaffected.
     */
    const envelope =
      payload.error && typeof payload.error === 'object'
        ? (payload.error as { code?: string; message?: string; details?: unknown })
        : null;

    // `||`, not `??`, on the last two. `response.statusText` is an EMPTY STRING rather than
    // undefined whenever the server does not set a reason phrase — which is always under
    // HTTP/2, where reason phrases were removed from the protocol. A nullish coalesce
    // therefore accepted "" and never reached the literal, so an unrecognised error body
    // produced an ApiError with a blank message and the UI showed an empty toast.
    const message =
      envelope?.message ||
      (typeof payload.detail === 'string' ? payload.detail : payload.message) ||
      response.statusText ||
      'Request failed';

    return new ApiError(
      response.status,
      statusToCode(response.status),
      message,
      envelope ? envelope.details : payload.detail,
      requestId,
      // The application's own code, when it sent one. This was being discarded, which is why
      // a suspended account was indistinguishable from any other 403 on the client.
      envelope?.code,
    );
  }

  // Unknown — wrap in a generic ApiError
  const message = thrown instanceof Error ? thrown.message : String(thrown);
  return new ApiError(0, 'UNKNOWN', message, thrown);
}

// ─── Internal helpers ────────────────────────────────────────────────────────

function statusToCode(status: number): ApiErrorCode {
  if (status === 401) return 'UNAUTHORIZED';
  if (status === 402) return 'CREDITS_EXHAUSTED';
  if (status === 403) return 'FORBIDDEN';
  if (status === 404) return 'NOT_FOUND';
  if (status === 422) return 'VALIDATION_ERROR';
  if (status === 429) return 'RATE_LIMITED';
  if (status >= 500) return 'SERVER_ERROR';
  return 'UNKNOWN';
}
