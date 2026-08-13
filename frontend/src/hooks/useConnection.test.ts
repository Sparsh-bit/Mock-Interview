import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import { isNetworkError } from './useConnection';

/**
 * Losing the internet must not look like losing the interview.
 *
 * Reported: "if the device goes offline then the interview must give the warning of the
 * internet connection and also the session must go on or it must resume from theri as it was
 * earlier theri must be a less disturbance. the interview must not start from the starting."
 *
 * The interview's POSITION was never at risk — the plan lives in the session row and `/next`
 * returns the question the candidate has not answered yet, so a drop cannot lose their place.
 * Every part of the complaint was about what happened around that:
 *
 *   - No warning at all, so an outage presented as the panel going silent.
 *   - The full-page error card fired on `isError` alone, replacing the pinned question, the
 *     half-typed answer and the whole panel thread with a retry screen. Coming back to an
 *     empty thread is indistinguishable from starting over, which is why a system that
 *     resumed correctly was reported as restarting.
 *   - The microphone stayed armed against a recogniser it could not reach.
 */

describe('isNetworkError', () => {
  it('treats a request that never got an answer as a connection problem', () => {
    expect(isNetworkError(new TypeError('Failed to fetch'))).toBe(true);
    expect(isNetworkError(new Error('network request failed'))).toBe(true);
    expect(isNetworkError({ name: 'AbortError' })).toBe(true);
    expect(isNetworkError({ name: 'TimeoutError' })).toBe(true);
  });

  it('does NOT treat an HTTP response as a connection problem', () => {
    /*
     * The distinction that matters. A 402 out of credits and a 500 from the scorer both prove
     * the network worked — telling that candidate to check their wifi sends them to fix the
     * wrong thing, and hides the paywall or the real error behind a connectivity banner.
     */
    expect(isNetworkError({ status: 402, message: 'Out of credits' })).toBe(false);
    expect(isNetworkError({ status: 500, message: 'Internal error' })).toBe(false);
    expect(isNetworkError({ status: 403, message: 'Account banned' })).toBe(false);
    // Even when the message happens to contain a trigger word.
    expect(isNetworkError({ status: 502, message: 'upstream connection reset' })).toBe(false);
  });

  it('is safe on the values a catch block actually receives', () => {
    expect(isNetworkError(null)).toBe(false);
    expect(isNetworkError(undefined)).toBe(false);
    expect(isNetworkError({})).toBe(false);
    expect(isNetworkError('Failed to fetch')).toBe(true);
  });
});

const HOOK = readFileSync(join(process.cwd(), 'src/hooks/useConnection.ts'), 'utf8');
const HOOK_CODE = HOOK.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');

describe('the connection hook', () => {
  it('does not trust navigator.onLine to say we are back', () => {
    /*
     * The lying-onLine case is the common one on campus: a hotspot with no data left keeps the
     * radio associated and reports `true` forever. So the `online` event must only START a
     * probe — clearing the warning on the event alone would hide a live outage.
     */
    const onOnline = HOOK_CODE.slice(HOOK_CODE.indexOf('const onOnline'));
    const body = onOnline.slice(0, onOnline.indexOf('};') + 2);
    expect(body).toMatch(/probe\(\)/);
    expect(body).not.toMatch(/goOnline\(\)/);
  });

  it('only probes while it believes it is down', () => {
    // A heartbeat that runs when everything is fine is pure cost: the interview makes real
    // requests constantly and each is a better liveness check than a synthetic ping.
    const probe = HOOK_CODE.slice(HOOK_CODE.indexOf('const probe'));
    expect(probe.slice(0, 120)).toMatch(/if\s*\(\s*onlineRef\.current\s*\)\s*return/);
  });

  it('starts optimistic so it cannot flash a false warning on load', () => {
    expect(HOOK_CODE).toMatch(/useState\(true\)/);
  });

  it('does not let a cached response report a dead connection as alive', () => {
    expect(HOOK_CODE).toMatch(/cache:\s*'no-store'/);
  });

  it('bounds the probe so a hanging request cannot wedge recovery', () => {
    expect(HOOK_CODE).toMatch(/AbortController/);
    expect(HOOK_CODE).toMatch(/PROBE_TIMEOUT_MS/);
  });
});

const PAGE = readFileSync(
  join(process.cwd(), 'src/app/(interview)/session/[id]/page.tsx'),
  'utf8',
);
const PAGE_CODE = PAGE.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');

describe('the interview holds rather than restarts', () => {
  it('keeps the interview on screen during an outage', () => {
    // The regression that made a resumable system feel unresumable. Guarded on `!question`, so
    // the takeover only happens when there is genuinely nothing to show.
    expect(PAGE_CODE).toMatch(/if\s*\(\s*isError\s*&&\s*!question\s*\)/);
  });

  it('warns without taking the screen', () => {
    // A strip, not a modal: a dialog would take the question off screen and steal focus from
    // the answer box, which is the disturbance being complained about.
    expect(PAGE_CODE).toMatch(/!connection\.online\s*&&\s*\(/);
    expect(PAGE_CODE).toMatch(/aria-live="polite"/);
  });

  it('holds the microphone shut while the connection is down', () => {
    expect(PAGE_CODE).toMatch(/if\s*\(\s*!connection\.online\s*\)\s*return/);
  });

  it('re-arms the microphone once the connection returns', () => {
    // Without `connection.online` in the arming effect's deps, a candidate who dropped out
    // mid-question would have to reach for the button for the rest of it.
    const effect = PAGE_CODE.slice(PAGE_CODE.indexOf('armedForRef.current = question.id'));
    expect(effect.slice(0, 900)).toMatch(/connection\.online\]/);
  });

  it('re-fetches on reconnect rather than assuming its own copy is current', () => {
    /*
     * A submit whose REQUEST arrived and whose RESPONSE was lost is the ordinary case for a
     * drop mid-answer: the server has moved on and the client has not. Re-fetching is how they
     * agree again, and it is what stops the candidate being asked the same question twice.
     */
    const effect = PAGE_CODE.slice(PAGE_CODE.indexOf('wasOfflineRef'));
    expect(effect.slice(0, 600)).toMatch(/refetch\(\)/);
  });

  it('does not clear the answer box on a failed submit', () => {
    // The answer must survive the outage — it is the one piece of state that exists only on
    // the client. setAnswer('') therefore belongs to onSuccess and must never move into
    // onError or the mutate call itself.
    const submit = PAGE_CODE.slice(PAGE_CODE.indexOf('const submitContent'));
    const onError = submit.slice(submit.indexOf('onError:'), submit.indexOf('onError:') + 500);
    expect(onError).not.toMatch(/setAnswer\(''\)/);
  });

  it('does not tell a candidate with a server error to check their wifi', () => {
    const submit = PAGE_CODE.slice(PAGE_CODE.indexOf('const submitContent'));
    expect(submit).toMatch(/isNetworkError\(err\)/);
  });
});
