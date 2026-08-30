/**
 * The PostHog adapter — lib/analytics/posthog.ts
 *
 * The only file that knows the vendor's name. `core.ts` takes a `SinkFactory`, so swapping
 * PostHog for something else is this file and one line in `index.ts`.
 *
 * ## Every default that had to be turned off, and what each one would have leaked
 *
 * PostHog's defaults are built for a marketing site. This is a product that holds resumes,
 * verbatim answers and employability judgements, so most of them are wrong here:
 *
 *   autocapture: false
 *       Autocapture records the TEXT CONTENT of clicked elements. In this product that
 *       includes question text, a candidate's own answer in a textarea's surroundings, panel
 *       dialogue, and the file name of an uploaded resume — which is very often the
 *       candidate's own name. This is the single most important line in the file.
 *
 *   capture_pageview: false
 *       URLs here carry identifiers: /report/<session id>/analysis, /r/<report id>,
 *       /practice/<question id>. A pageview stream is a list of which reports a named person
 *       opened. The six events in `events.ts` answer the funnel without it.
 *
 *   disable_session_recording: true
 *       Session replay records the screen. The screen contains the resume, the answers and
 *       the report.
 *
 *   capture_performance: false
 *       Web-vitals payloads carry the full URL, so they reintroduce the pageview leak by a
 *       side door.
 *
 *   persistence: 'localStorage'
 *       Not the default `localStorage+cookie`. A cookie is sent on every request to the
 *       vendor's domain and is the part of this that a reader will reasonably object to;
 *       localStorage is enough for a stable distinct id and stays on the device until the
 *       person withdraws, at which point `shutdown` clears it.
 *
 *   person_profiles: 'identified_only'
 *       No profile is created for anybody who has not been identified — and identification
 *       only happens after an explicit grant. Without this, an anonymous profile exists for
 *       every visitor.
 *
 * ## `disable_external_dependency_loading`
 *
 * PostHog can fetch extra bundles (surveys, toolbar, replay) from its CDN at runtime.
 * Switched off: this app has a Content-Security-Policy (`lib/security-headers.ts`) and a
 * script fetched at runtime is a script the policy was not written against.
 */

import type { AnalyticsSink } from './core';
import type { Properties } from './events';

/**
 * Build a PostHog sink, or null when analytics is not configured for this deployment.
 *
 * NULL RATHER THAN A NO-OP OBJECT. `core.isActive()` reads "is anything running", and a
 * no-op sink would make an unconfigured deployment claim it was tracking. It also means a
 * developer's laptop, which has no key, behaves exactly like a candidate who declined.
 *
 * Loaded with a dynamic `import()` so the vendor bundle is not in the main chunk. A page
 * that never gets consent never downloads it at all.
 */
export function createPostHogSink(): AnalyticsSink | null {
  const key = process.env.NEXT_PUBLIC_POSTHOG_KEY;
  if (!key || typeof window === 'undefined') return null;

  const host = process.env.NEXT_PUBLIC_POSTHOG_HOST || 'https://eu.i.posthog.com';

  // Events fired between the grant and the module arriving are queued HERE, in the adapter,
  // not in `core`. The distinction matters and is not a technicality: consent has already
  // been given by the time anything reaches this object, so holding a handful of events for
  // the length of a dynamic import is a network detail. `core` refusing to buffer is about
  // the period BEFORE consent, which is the period that matters.
  let client: typeof import('posthog-js').default | null = null;
  let pending: Array<[string, Properties]> = [];
  let identity: string | null = null;
  let discarded = false;

  void import('posthog-js')
    .then(({ default: posthog }) => {
      if (discarded) return;
      posthog.init(key, {
        api_host: host,
        // See the module docstring. Every one of these is load-bearing.
        autocapture: false,
        capture_pageview: false,
        capture_pageleave: false,
        capture_performance: false,
        disable_session_recording: true,
        disable_surveys: true,
        disable_external_dependency_loading: true,
        persistence: 'localStorage',
        person_profiles: 'identified_only',
        // THE LAST GATE, AND IT IS ON THE VENDOR'S OWN AUTOMATIC PROPERTIES rather than on
        // ours. `scrubProperties` governs what WE attach; the SDK attaches its own set to
        // every event regardless, and three of those carry the leak this file is about:
        // `$current_url` and `$referrer` are the report and question ids that
        // `capture_pageview: false` was switched off to keep out, and `$ip` is a location.
        //
        // Deleting them here means they are gone before the request is built, so they are
        // absent from the payload rather than merely unused at the other end.
        sanitize_properties: (properties) => {
          const out = { ...properties };
          delete out.$current_url;
          delete out.$referrer;
          delete out.$referring_domain;
          delete out.$pathname;
          delete out.$ip;
          return out;
        },
      });
      client = posthog;
      if (identity) posthog.identify(identity);
      for (const [event, properties] of pending) posthog.capture(event, properties);
      pending = [];
    })
    .catch(() => {
      // A blocked or failed vendor bundle must be silent. An ad blocker is the ordinary case
      // and it is not an error the candidate should ever see.
      pending = [];
    });

  return {
    identify(distinctId: string) {
      identity = distinctId;
      client?.identify(distinctId);
    },
    capture(event: string, properties: Properties) {
      if (client) client.capture(event, properties);
      else if (pending.length < 20) pending.push([event, properties]);
    },
    shutdown() {
      discarded = true;
      pending = [];
      // `reset` clears the stored distinct id and any person properties; `opt_out_capturing`
      // stops anything already in flight and writes the opt-out flag the SDK checks itself.
      // Both, because either alone leaves half of it: reset without opt-out lets a later
      // capture start a fresh anonymous id, and opt-out without reset leaves the old id in
      // localStorage after somebody has asked to be forgotten.
      client?.opt_out_capturing();
      client?.reset();
      client = null;
    },
  };
}
