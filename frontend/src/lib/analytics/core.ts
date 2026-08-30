/**
 * Consent-gated analytics dispatch — lib/analytics/core.ts
 *
 * THE ONE RULE: nothing reaches the vendor until this account has explicitly granted the
 * `analytics` consent, and everything stops the moment it is withdrawn.
 *
 * ## Why "no buffering" is the design and not an omission
 *
 * The obvious convenience is to queue events fired before the consent answer arrives and
 * flush them once it does. That is still collecting data before consent — the collection is
 * the act, and a buffer in the page is collection. Worse, it makes the failure invisible:
 * the code looks gated, the vendor receives everything, and the only difference is a few
 * hundred milliseconds.
 *
 * So an event fired before consent is DROPPED and `track` returns false. The measurable cost
 * is a `signup` event lost for anybody who declines at signup and grants later — which is
 * correct, because they had not agreed when it happened.
 *
 * ## Why the vendor SDK is loaded lazily and only after consent
 *
 * `posthog.init` is itself a processing act: it writes an identifier to storage, starts
 * autocapture, and can send a pageview before a single line of our code runs. Initialising
 * it "disabled" and flipping a flag later would mean the script had already loaded, already
 * stored an id, and already had the chance. The sink is therefore CONSTRUCTED on grant and
 * discarded on withdrawal, and `core` never imports the vendor at all — it takes a
 * `SinkFactory`. That is also what makes this file testable in plain Node with no DOM: the
 * tests hand it a recording sink and assert on exactly what would have been sent.
 *
 * ## Consent has three states, not two
 *
 *   'unknown'  the answer has not arrived from the server yet, or the request failed
 *   'granted'  an explicit grant
 *   'denied'   asked and refused, or never asked
 *
 * `unknown` and `denied` behave identically for dispatch — both drop — and they are kept
 * apart because only `unknown` is worth retrying, and only `denied` should stop the UI
 * asking again.
 */

import { type EventName, type Properties, scrubProperties } from './events';

/** What a vendor adapter has to provide. Deliberately four methods and no more. */
export interface AnalyticsSink {
  /** Called once, immediately after construction, with the pseudonymous account id. */
  identify(distinctId: string): void;
  capture(event: string, properties: Properties): void;
  /** Stop, and forget everything stored in the browser for this vendor. */
  shutdown(): void;
}

export type SinkFactory = () => AnalyticsSink | null;

export type ConsentState = 'unknown' | 'granted' | 'denied';

/**
 * One analytics client. A module singleton in the app; a fresh instance per test.
 *
 * A CLASS RATHER THAN MODULE-LEVEL LET BINDINGS, purely so the tests can construct an
 * isolated one. Module state that only a test-only reset function can clear is state that
 * leaks between tests in whatever order they happen to run, and the bug it produces —
 * "consent is granted because the previous test granted it" — is the exact bug this file
 * exists to prevent.
 */
export class Analytics {
  private consent: ConsentState = 'unknown';
  private sink: AnalyticsSink | null = null;
  private distinctId: string | null = null;

  constructor(private readonly createSink: SinkFactory) {}

  /**
   * Apply the answer the server gave for this account.
   *
   * IDEMPOTENT, because it is called from a React effect that re-runs on every render where
   * the query result identity changes. Granting twice must not construct two sinks; the
   * second would double every event.
   */
  setConsent(state: ConsentState, distinctId: string | null = this.distinctId): void {
    const identityChanged = distinctId !== null && distinctId !== this.distinctId;

    if (state !== 'granted') {
      // Covers both withdrawal and the initial denied/unknown state. Tearing down on
      // 'unknown' matters: a failed consent read must not leave a previously granted sink
      // running against an account whose answer we can no longer see.
      this.teardown();
      this.consent = state;
      this.distinctId = distinctId;
      return;
    }

    this.consent = 'granted';

    // A DIFFERENT ACCOUNT SIGNED IN. The vendor's stored identifier belongs to the previous
    // one, so continuing to use it would attribute this person's events to somebody else —
    // the same cross-account leak `useClearCacheOnAccountChange` exists to stop in the query
    // cache, in a store that ships off the device.
    if (this.sink && identityChanged) this.teardown();

    this.distinctId = distinctId;
    if (this.sink || !this.distinctId) return;

    this.sink = this.createSink();
    this.sink?.identify(this.distinctId);
  }

  /**
   * Send one event. Returns whether it was actually sent.
   *
   * The boolean is not decoration — it is what the tests assert on, and it is what makes
   * "was this dropped?" answerable at a call site that cares. Nothing in the product branches
   * on it, because nothing in the product may behave differently depending on whether
   * somebody consented to analytics.
   */
  track(event: EventName, properties: Properties = {}): boolean {
    if (this.consent !== 'granted' || !this.sink) return false;
    this.sink.capture(event, scrubProperties(event, properties));
    return true;
  }

  /** For the tests and for the settings UI: is anything actually running? */
  isActive(): boolean {
    return this.consent === 'granted' && this.sink !== null;
  }

  consentState(): ConsentState {
    return this.consent;
  }

  private teardown(): void {
    this.sink?.shutdown();
    this.sink = null;
  }
}
