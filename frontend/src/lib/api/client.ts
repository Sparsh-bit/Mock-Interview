/**
 * @module frontend/src/lib/api/client
 * Core ApiClient class — the single fetch abstraction for the entire application.
 *
 * Features:
 * - Server Component and Client Component compatible
 * - Automatic token injection via pluggable TokenProvider
 * - Per-request and global timeouts via AbortController
 * - Exponential backoff retry with full jitter
 * - Composable request/response/error interceptor pipelines
 * - Typed responses via generics
 * - Normalized errors (all failures produce ApiError)
 * - FormData support (removes Content-Type for multipart boundary)
 * - Next.js cache/revalidation options forwarded to fetch
 */

import type {
  ApiClientConfig,
  ApiResponse,
  HttpMethod,
  PreparedRequest,
  RequestConfig,
  RetryConfig,
} from './types';
import { ApiError, normalizeError } from './errors';
import {
  DEFAULT_RETRY_CONFIG,
  calculateDelay,
  mergeRetryConfig,
  shouldRetry,
  sleep,
} from './retry';
import { createAuthInterceptor, createRequestIdInterceptor } from './interceptors';

const DEFAULT_TIMEOUT_MS = 30_000;

export class ApiClient {
  private readonly baseUrl: string;
  private readonly defaultTimeout: number;
  private readonly defaultRetry: Required<RetryConfig> | false;
  private readonly defaultHeaders: Record<string, string>;
  private readonly requestInterceptors: NonNullable<ApiClientConfig['requestInterceptors']>;
  private readonly responseInterceptors: NonNullable<ApiClientConfig['responseInterceptors']>;
  private readonly errorInterceptors: NonNullable<ApiClientConfig['errorInterceptors']>;

  constructor(config: ApiClientConfig) {
    this.baseUrl = config.baseUrl.replace(/\/$/, '');
    this.defaultTimeout = config.defaultTimeout ?? DEFAULT_TIMEOUT_MS;

    this.defaultRetry =
      config.defaultRetry === false
        ? false
        : { ...DEFAULT_RETRY_CONFIG, ...(config.defaultRetry ?? {}) };

    this.defaultHeaders = {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      ...config.defaultHeaders,
    };

    // Built-in interceptors always run first, then consumer-provided ones
    const builtIns: NonNullable<ApiClientConfig['requestInterceptors']> = [
      createRequestIdInterceptor(),
      ...(config.tokenProvider ? [createAuthInterceptor(config.tokenProvider)] : []),
    ];

    this.requestInterceptors = [...builtIns, ...(config.requestInterceptors ?? [])];
    this.responseInterceptors = config.responseInterceptors ?? [];
    this.errorInterceptors = config.errorInterceptors ?? [];
  }

  // ─── Public HTTP methods ──────────────────────────────────────────────────

  get<T>(path: string, config?: Omit<RequestConfig, 'body'>): Promise<ApiResponse<T>> {
    return this.request<T>('GET', path, config);
  }

  post<T>(path: string, body?: unknown, config?: RequestConfig): Promise<ApiResponse<T>> {
    return this.request<T>('POST', path, { ...config, body });
  }

  put<T>(path: string, body?: unknown, config?: RequestConfig): Promise<ApiResponse<T>> {
    return this.request<T>('PUT', path, { ...config, body });
  }

  patch<T>(path: string, body?: unknown, config?: RequestConfig): Promise<ApiResponse<T>> {
    return this.request<T>('PATCH', path, { ...config, body });
  }

  delete<T>(path: string, config?: Omit<RequestConfig, 'body'>): Promise<ApiResponse<T>> {
    return this.request<T>('DELETE', path, config);
  }

  // ─── Core request pipeline ────────────────────────────────────────────────

  private async request<T>(
    method: HttpMethod,
    path: string,
    config: RequestConfig = {},
  ): Promise<ApiResponse<T>> {
    const {
      body,
      headers = {},
      params,
      timeout = this.defaultTimeout,
      retry: retryOverride,
      signal: externalSignal,
      next,
      cache,
      skipAuth,
    } = config;

    const url = this.buildUrl(path, params);
    const mergedHeaders: Record<string, string> = { ...this.defaultHeaders, ...headers };

    // FormData sets its own Content-Type with the multipart boundary
    if (body instanceof FormData) {
      delete mergedHeaders['Content-Type'];
    }

    const init: RequestInit & { headers: Record<string, string>; extraOptions?: Record<string, unknown> } = {
      method,
      headers: mergedHeaders,
      ...(body !== undefined && {
        body: body instanceof FormData ? body : JSON.stringify(body),
      }),
      ...(next !== undefined && { next }),
      ...(cache !== undefined && { cache }),
      ...(skipAuth && { extraOptions: { skipAuth: true } }),
    };

    let prepared: PreparedRequest = { url, init };

    // Run request interceptor pipeline sequentially
    for (const interceptor of this.requestInterceptors) {
      prepared = await interceptor(prepared);
    }

    const effectiveRetry = mergeRetryConfig(retryOverride, this.defaultRetry || undefined);

    return this.executeWithRetry<T>(prepared, effectiveRetry, timeout, externalSignal, 0);
  }

  // ─── Retry-aware execution loop ───────────────────────────────────────────

  private async executeWithRetry<T>(
    prepared: PreparedRequest,
    retryConfig: Required<RetryConfig> | false,
    timeout: number,
    externalSignal: AbortSignal | undefined,
    attempt: number,
  ): Promise<ApiResponse<T>> {
    const timeoutController = new AbortController();
    const timeoutId = setTimeout(
      () => timeoutController.abort(new DOMException('Timeout', 'TimeoutError')),
      timeout,
    );

    // Merge the internal timeout signal with any external signal
    const signal = externalSignal
      ? mergeSignals(timeoutController.signal, externalSignal)
      : timeoutController.signal;

    let rawResponse: Response | undefined;

    try {
      rawResponse = await fetch(prepared.url, { ...prepared.init, signal });
      clearTimeout(timeoutId);

      // Run response interceptor pipeline
      let processedResponse = rawResponse;
      for (const interceptor of this.responseInterceptors) {
        processedResponse = await interceptor(processedResponse, prepared);
      }

      if (!processedResponse.ok) {
        throw await normalizeError(new Error('HTTP Error'), processedResponse);
      }

      const data = await parseBody<T>(processedResponse);
      return {
        data,
        status: processedResponse.status,
        ok: true,
        headers: processedResponse.headers,
      };
    } catch (thrown) {
      clearTimeout(timeoutId);

      // Reclassify our internal AbortError as TIMEOUT so callers can distinguish
      // a timeout from a user-initiated cancel via externalSignal
      let error = await normalizeError(thrown, rawResponse);
      if (
        error.code === 'ABORTED' &&
        timeoutController.signal.aborted &&
        !externalSignal?.aborted
      ) {
        error = new ApiError(0, 'TIMEOUT', `Request timed out after ${timeout}ms`);
      }

      // Run error interceptor pipeline
      let processedError: unknown = error;
      for (const interceptor of this.errorInterceptors) {
        processedError = await interceptor(processedError, prepared);
      }

      // Re-normalize in case an interceptor returned a plain Error
      const finalError =
        processedError instanceof ApiError
          ? processedError
          : await normalizeError(processedError);

      // Retry decision
      if (retryConfig && shouldRetry(finalError, attempt, retryConfig)) {
        const retryAfter = rawResponse?.headers.get('Retry-After');
        const delay = calculateDelay(attempt, retryConfig, retryAfter);
        await sleep(delay);
        return this.executeWithRetry<T>(
          prepared,
          retryConfig,
          timeout,
          externalSignal,
          attempt + 1,
        );
      }

      throw finalError;
    }
  }

  // ─── URL construction ─────────────────────────────────────────────────────

  private buildUrl(
    path: string,
    params?: Record<string, string | number | boolean | null | undefined>,
  ): string {
    const normalizedPath = path.startsWith('/') ? path : `/${path}`;
    const fullUrl = `${this.baseUrl}${normalizedPath}`;

    if (!params) return fullUrl;

    const qs = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== null && value !== undefined) {
        qs.set(key, String(value));
      }
    }

    const queryString = qs.toString();
    return queryString ? `${fullUrl}?${queryString}` : fullUrl;
  }
}

// ─── Module-private helpers ───────────────────────────────────────────────────

async function parseBody<T>(response: Response): Promise<T> {
  // 204 No Content or explicit empty body — return undefined (typed as T)
  if (
    response.status === 204 ||
    response.headers.get('content-length') === '0'
  ) {
    return undefined as T;
  }

  const contentType = response.headers.get('content-type') ?? '';

  try {
    if (contentType.includes('application/json')) return (await response.json()) as T;
    if (contentType.startsWith('text/')) return (await response.text()) as T;
    return (await response.blob()) as T;
  } catch (err) {
    throw new ApiError(
      response.status,
      'PARSE_ERROR',
      'Failed to parse response body',
      err,
    );
  }
}

/**
 * Creates a composite AbortSignal that fires when ANY of the input signals abort.
 * Used to merge the internal timeout signal with any caller-provided signal.
 */
function mergeSignals(...signals: AbortSignal[]): AbortSignal {
  const controller = new AbortController();

  for (const signal of signals) {
    if (signal.aborted) {
      controller.abort(signal.reason);
      return controller.signal;
    }
    signal.addEventListener(
      'abort',
      () => controller.abort(signal.reason),
      { once: true },
    );
  }

  return controller.signal;
}
