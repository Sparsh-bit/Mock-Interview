'use client';

import {
  breadcrumbsIntegration,
  browserApiErrorsIntegration,
  captureException,
  dedupeIntegration,
  functionToStringIntegration,
  globalHandlersIntegration,
  httpContextIntegration,
  init,
  linkedErrorsIntegration,
} from '@sentry/browser';

import { scrubBreadcrumb, scrubEvent } from './scrub';

/**
 * Browser error tracking.
 *
 * WHY `@sentry/browser` AND NOT `@sentry/nextjs`.
 *
 * No page in this app declares `export const runtime = 'edge'` — there is a test,
 * `src/app/edge-runtime.test.ts`, that fails if one does — because the frontend deploys to
 * Cloudflare Workers through `@opennextjs/cloudflare`, which runs Next on the Node.js
 * runtime inside workerd. That is still not Node: `@sentry/nextjs` splits into a Node server
 * SDK and a Vercel Edge SDK, and neither targets workerd; Sentry ships a separate
 * `@sentry/cloudflare` for that runtime, wired through the adapter rather than Next. Adding
 * `@sentry/nextjs` here would install a build plugin and server instrumentation into
 * the one runtime it is not built for, on a deployment path CI cannot exercise.
 *
 * `@sentry/browser` is the same SDK core with none of that: it runs where the errors
 * actually are. The server side of this frontend is a thin rendering layer that calls
 * a FastAPI backend, and that backend reports through `app/core/observability.py` — so
 * the coverage gap is Next.js's own SSR frames, not application logic. Revisit if the
 * deployment ever moves to Node.
 *
 * The integration list is explicit rather than defaulted, because two of the defaults
 * are the leak. See the comments on each.
 */

let started = false;

export function initSentry(): boolean {
  if (started) return true;

  const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN?.trim();
  // No DSN is the normal state on a developer's machine and in CI. Silent, not a
  // warning — a warning on every page load teaches people to ignore warnings.
  if (!dsn) return false;

  init({
    dsn,
    environment: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT || 'production',
    release: process.env.APP_VERSION,

    // Sentry's own PII switch. With it on, the SDK attaches the request body, cookies
    // and the client IP by itself, before any hook of ours runs.
    sendDefaultPii: false,

    // Tracing off. It is a separate cost centre, its spans describe every fetch this
    // page makes, and nothing is asking for it yet. Turn it on deliberately, with its
    // own scrubbing review.
    tracesSampleRate: 0,

    /*
     * EXPLICIT, BECAUSE TWO DEFAULTS ARE THE PROBLEM.
     *
     * Omitted on purpose:
     *   `browserSessionIntegration` — sends a session record per pageview whether or
     *     not anything failed, which is analytics, not error tracking.
     *   `replayIntegration` — records the DOM. The DOM during an interview is the
     *     question and the answer being typed into it. Not installed at all, so no
     *     masking configuration has to be got right.
     *
     * `breadcrumbsIntegration` keeps `dom: false`: DOM breadcrumbs record the text
     * content of what was clicked, and on this app that is a question or an option.
     */
    defaultIntegrations: false,
    integrations: [
      functionToStringIntegration(),
      dedupeIntegration(),
      globalHandlersIntegration(),
      browserApiErrorsIntegration(),
      linkedErrorsIntegration(),
      httpContextIntegration(),
      breadcrumbsIntegration({ console: true, dom: false, fetch: true, history: true, xhr: true }),
    ],

    beforeSend: (event) => scrubEvent(event as unknown as Record<string, unknown>) as never,
    beforeBreadcrumb: (crumb) =>
      scrubBreadcrumb(crumb as unknown as Record<string, unknown>) as never,
  });

  started = true;
  return true;
}

/**
 * Report an error we caught ourselves — the app's error boundaries.
 *
 * A no-op when Sentry never started, so callers never have to check.
 */
export function reportError(error: unknown, context?: Record<string, string>): void {
  if (!started) return;
  captureException(error, context ? { tags: context } : undefined);
}
