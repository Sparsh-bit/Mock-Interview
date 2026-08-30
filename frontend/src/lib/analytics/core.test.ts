import { beforeEach, describe, expect, it } from 'vitest';

import { Analytics, type AnalyticsSink } from './core';
import { ALLOWED_PROPERTIES, EVENTS, scrubProperties } from './events';

/**
 * Nothing reaches the analytics vendor before consent — lib/analytics/core.test.ts
 *
 * This is the file that has to be right. The property it protects is not "the code contains a
 * consent check"; it is "no event left this browser before somebody agreed", and the only way
 * to assert that is to record everything the sink WOULD have received and prove the list is
 * empty.
 *
 * WHY A RECORDING SINK RATHER THAN A MOCK OF posthog-js. A mock of the vendor tests that we
 * called the vendor's API correctly. What matters here is the gate, which sits above the
 * vendor and must hold whichever vendor is behind it — so the tests drive the real
 * `Analytics` class with a sink that writes to an array, and every assertion is about that
 * array. `posthog.ts` is asserted separately, against its source, in `no-pii.test.ts`.
 */

interface Recorded {
  event: string;
  properties: Record<string, unknown>;
}

function recordingSink() {
  const captured: Recorded[] = [];
  const identified: string[] = [];
  let live = true;
  const sink: AnalyticsSink = {
    identify: (id) => identified.push(id),
    capture: (event, properties) => captured.push({ event, properties }),
    shutdown: () => {
      live = false;
    },
  };
  return { sink, captured, identified, isLive: () => live };
}

const USER = '11111111-2222-3333-4444-555555555555';
const OTHER_USER = '99999999-8888-7777-6666-555555555555';

describe('nothing is sent before consent', () => {
  let made: ReturnType<typeof recordingSink>[];
  let factory: () => AnalyticsSink;

  beforeEach(() => {
    made = [];
    factory = () => {
      const next = recordingSink();
      made.push(next);
      return next.sink;
    };
  });

  const allCaptured = () => made.flatMap((m) => m.captured);

  it('constructs no sink at all until consent is granted', () => {
    const analytics = new Analytics(factory);
    analytics.track(EVENTS.SIGNUP);
    expect(made).toHaveLength(0);
    expect(analytics.isActive()).toBe(false);
  });

  it('drops every event while the answer is still unknown', () => {
    const analytics = new Analytics(factory);
    for (const event of Object.values(EVENTS)) {
      expect(analytics.track(event)).toBe(false);
    }
    expect(allCaptured()).toEqual([]);
  });

  it('drops every event after an explicit refusal', () => {
    const analytics = new Analytics(factory);
    analytics.setConsent('denied', USER);
    for (const event of Object.values(EVENTS)) {
      expect(analytics.track(event)).toBe(false);
    }
    expect(made).toHaveLength(0);
    expect(allCaptured()).toEqual([]);
  });

  it('does not buffer pre-consent events and replay them on grant', () => {
    // THE SUBTLE FAILURE THIS EXISTS FOR. A queue that flushes on consent looks gated and
    // is not: the collection already happened, and the only difference is a delay. If
    // somebody adds a buffer "so we do not lose the signup event", this fails.
    const analytics = new Analytics(factory);
    analytics.track(EVENTS.SIGNUP);
    analytics.track(EVENTS.INTERVIEW_STARTED);
    analytics.track(EVENTS.PURCHASE, { item_id: 'interview_1' });

    analytics.setConsent('granted', USER);
    expect(allCaptured()).toEqual([]);
  });

  it('is not active for a signed-out visitor even after a previous grant', () => {
    const analytics = new Analytics(factory);
    analytics.setConsent('granted', USER);
    analytics.setConsent('unknown', null);
    expect(analytics.isActive()).toBe(false);
    expect(analytics.track(EVENTS.SIGNUP)).toBe(false);
  });

  it('sends nothing when granted without an account to identify', () => {
    // A grant with no distinct id would mean an anonymous profile at the vendor, created
    // before anybody was identified — which is a person the vendor has a row for and we
    // cannot tie to a consent record.
    const analytics = new Analytics(factory);
    analytics.setConsent('granted', null);
    expect(analytics.isActive()).toBe(false);
    expect(analytics.track(EVENTS.SIGNUP)).toBe(false);
    expect(made).toHaveLength(0);
  });
});

describe('tracking after consent', () => {
  it('identifies the account exactly once and sends the event', () => {
    const { sink, captured, identified } = recordingSink();
    const analytics = new Analytics(() => sink);

    analytics.setConsent('granted', USER);
    expect(identified).toEqual([USER]);
    expect(analytics.track(EVENTS.SIGNUP)).toBe(true);
    expect(captured).toEqual([{ event: 'signup', properties: {} }]);
  });

  it('does not build a second sink when consent is re-applied', () => {
    // `setConsent` runs from a React effect that re-fires whenever the query result identity
    // changes. A second sink would double every event from that point on.
    const made: AnalyticsSink[] = [];
    const captured: Recorded[] = [];
    const analytics = new Analytics(() => {
      const sink: AnalyticsSink = {
        identify: () => {},
        capture: (event, properties) => captured.push({ event, properties }),
        shutdown: () => {},
      };
      made.push(sink);
      return sink;
    });

    analytics.setConsent('granted', USER);
    analytics.setConsent('granted', USER);
    analytics.setConsent('granted', USER);
    analytics.track(EVENTS.SIGNUP);

    expect(made).toHaveLength(1);
    expect(captured).toHaveLength(1);
  });

  it('carries each event with the properties it is allowed', () => {
    const { sink, captured } = recordingSink();
    const analytics = new Analytics(() => sink);
    analytics.setConsent('granted', USER);

    analytics.track(EVENTS.RESUME_UPLOADED, { is_first: true });
    analytics.track(EVENTS.INTERVIEW_STARTED, { is_first: false });
    analytics.track(EVENTS.INTERVIEW_COMPLETED, { is_first: true });
    analytics.track(EVENTS.PURCHASE, {
      item_id: 'interview_5',
      feature: 'interview',
      quantity: 5,
      price_paise: 19900,
      is_repeat: false,
    });

    expect(captured).toEqual([
      { event: 'resume_uploaded', properties: { is_first: true } },
      { event: 'interview_started', properties: { is_first: false } },
      { event: 'interview_completed', properties: { is_first: true } },
      {
        event: 'purchase',
        properties: {
          item_id: 'interview_5',
          feature: 'interview',
          quantity: 5,
          price_paise: 19900,
          is_repeat: false,
        },
      },
    ]);
  });
});

describe('withdrawal', () => {
  it('stops immediately and tells the sink to forget what it stored', () => {
    const { sink, captured, isLive } = recordingSink();
    const analytics = new Analytics(() => sink);

    analytics.setConsent('granted', USER);
    analytics.track(EVENTS.SIGNUP);
    analytics.setConsent('denied', USER);

    expect(isLive()).toBe(false);
    expect(analytics.isActive()).toBe(false);
    expect(analytics.track(EVENTS.PURCHASE, { item_id: 'interview_1' })).toBe(false);
    expect(captured).toHaveLength(1);
  });

  it('treats a failed consent read as a withdrawal rather than carrying on', () => {
    // A withdrawal made on another device is invisible to this one until the read succeeds.
    // Continuing to track on a failed read is the one direction this must never fail in.
    const { sink, isLive } = recordingSink();
    const analytics = new Analytics(() => sink);

    analytics.setConsent('granted', USER);
    analytics.setConsent('unknown', USER);

    expect(isLive()).toBe(false);
    expect(analytics.isActive()).toBe(false);
  });

  it('can be granted again after a withdrawal, with a fresh sink', () => {
    const made: ReturnType<typeof recordingSink>[] = [];
    const analytics = new Analytics(() => {
      const next = recordingSink();
      made.push(next);
      return next.sink;
    });

    analytics.setConsent('granted', USER);
    analytics.setConsent('denied', USER);
    analytics.setConsent('granted', USER);
    analytics.track(EVENTS.SIGNUP);

    expect(made).toHaveLength(2);
    expect(made[0].captured).toEqual([]);
    expect(made[1].captured).toHaveLength(1);
  });
});

describe('one browser, two accounts', () => {
  it('tears down and re-identifies when a different account signs in', () => {
    // The vendor's stored id belongs to the previous account. Keeping it attributes this
    // person's events to somebody else — the cross-account leak `useClearCacheOnAccountChange`
    // fixes in the query cache, except this copy leaves the device.
    const made: ReturnType<typeof recordingSink>[] = [];
    const analytics = new Analytics(() => {
      const next = recordingSink();
      made.push(next);
      return next.sink;
    });

    analytics.setConsent('granted', USER);
    analytics.track(EVENTS.SIGNUP);
    analytics.setConsent('granted', OTHER_USER);
    analytics.track(EVENTS.INTERVIEW_STARTED, { is_first: true });

    expect(made).toHaveLength(2);
    expect(made[0].identified).toEqual([USER]);
    expect(made[0].isLive()).toBe(false);
    expect(made[1].identified).toEqual([OTHER_USER]);
    expect(made[1].captured.map((c) => c.event)).toEqual(['interview_started']);
  });
});

describe('property scrubbing', () => {
  it('drops anything the event does not declare', () => {
    expect(
      scrubProperties(EVENTS.INTERVIEW_STARTED, {
        is_first: true,
        session_id: 'abc',
        track_id: 'xyz',
      } as never)
    ).toEqual({ is_first: true });
  });

  it.each([
    ['email', 'candidate@example.com'],
    ['full_name', 'A Real Person'],
    ['resume_text', 'Priya Sharma, B.Tech'],
    ['transcript', 'I would use a HashMap because'],
    ['answer', 'a long answer'],
    ['question_text', 'What is a HashMap?'],
    ['overall_score', 72],
    ['feedback', 'needs work on concurrency'],
    ['access_token', 'ey.J...'],
    ['phone', '9876543210'],
    ['college_name', 'A Named Institute'],
  ])('never lets %s through, on any event', (key, value) => {
    for (const event of Object.values(EVENTS)) {
      expect(scrubProperties(event, { [key]: value } as never)).toEqual({});
    }
  });

  it('drops values that are not primitives', () => {
    // An API response spread into a property bag is how an object arrives here, and an object
    // is an unbounded amount of somebody's data.
    expect(
      scrubProperties(EVENTS.PURCHASE, {
        item_id: { id: 'interview_1', payer: 'someone@example.com' },
      } as never)
    ).toEqual({});
  });

  it('sends nothing at all for an event that declares no properties', () => {
    expect(ALLOWED_PROPERTIES[EVENTS.SIGNUP]).toEqual([]);
    expect(scrubProperties(EVENTS.SIGNUP, { is_first: true } as never)).toEqual({});
  });

  it('scrubs on the way through track, not only when called directly', () => {
    const { sink, captured } = recordingSink();
    const analytics = new Analytics(() => sink);
    analytics.setConsent('granted', USER);

    analytics.track(EVENTS.PURCHASE, {
      item_id: 'gd_1',
      payer_email: 'candidate@example.com',
      razorpay_payment_id: 'pay_123',
    } as never);

    expect(captured[0].properties).toEqual({ item_id: 'gd_1' });
  });
});

describe('analytics can never break the surface that fired it', () => {
  it('does not throw when the sink factory returns null', () => {
    // An unconfigured deployment — a developer's laptop, or CI. It must behave exactly like
    // somebody who declined, not like an error.
    const analytics = new Analytics(() => null);
    analytics.setConsent('granted', USER);
    expect(analytics.isActive()).toBe(false);
    expect(() => analytics.track(EVENTS.SIGNUP)).not.toThrow();
  });

  it('reports the consent state without ever needing a sink', () => {
    const analytics = new Analytics(() => null);
    expect(analytics.consentState()).toBe('unknown');
    analytics.setConsent('denied', USER);
    expect(analytics.consentState()).toBe('denied');
  });
});

describe('the catalogue itself', () => {
  it('covers exactly the funnel that was asked for', () => {
    expect(Object.values(EVENTS).sort()).toEqual([
      'interview_completed',
      'interview_started',
      'purchase',
      'resume_uploaded',
      'signup',
    ]);
  });

  it('declares an allowlist for every event, with no orphans either way', () => {
    expect(Object.keys(ALLOWED_PROPERTIES).sort()).toEqual(Object.values(EVENTS).sort());
  });

});
