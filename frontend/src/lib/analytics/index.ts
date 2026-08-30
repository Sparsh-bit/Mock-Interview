/**
 * The app's analytics client — lib/analytics/index.ts
 *
 * One instance per tab, wired to the PostHog sink. Everything interesting is in `core.ts`
 * (the consent gate) and `events.ts` (the closed catalogue); this file only decides which
 * vendor the singleton talks to and gives call sites a `track` that cannot be mis-typed.
 *
 * IMPORTING THIS FILE STARTS NOTHING. The instance holds `consent: 'unknown'` and no sink
 * until `AnalyticsGate` applies the answer the server gave, so a module-scope import — which
 * happens during the server render too — is inert.
 */

import { Analytics } from './core';
import { type EventName, type Properties } from './events';
import { createPostHogSink } from './posthog';

export { EVENTS, type EventName } from './events';
export type { ConsentState } from './core';

export const analytics = new Analytics(createPostHogSink);

/**
 * Send one event, if this account has consented.
 *
 * A free function rather than a hook, because most call sites are inside a mutation's
 * `onSuccess` or an event handler where a hook cannot go — and because a hook would imply
 * that not calling it during render is a mistake.
 *
 * NEVER THROWS AND NEVER AWAITS. Analytics sits inside the success path of an interview
 * start and a payment confirmation; it must not be able to fail either of them, and it must
 * not add latency to either. `Analytics.track` is synchronous and total, and the vendor's
 * own transport is fire-and-forget.
 */
export function track(event: EventName, properties: Properties = {}): void {
  analytics.track(event, properties);
}
