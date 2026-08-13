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

  constructor(
    status: number,
    code: ApiErrorCode,
    message: string,
    details?: unknown,
    requestId?: string,
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
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
interface FastApiErrorPayload {
  code?: string;
  message?: string;
  detail?: unknown;
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

    const message =
      typeof payload.detail === 'string'
        ? payload.detail
        : payload.message ?? response.statusText ?? 'Request failed';

    return new ApiError(
      response.status,
      statusToCode(response.status),
      message,
      payload.detail,
      requestId,
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
