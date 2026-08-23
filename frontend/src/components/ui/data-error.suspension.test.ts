/**
 * A suspended account is never a dead end — data-error.suspension.test.ts
 *
 * REPORTED: "once the id gets suspended then it is not opening even if we log out from
 * everywhere".
 *
 * Two separate faults produced that, and this file covers the client half. The suspension
 * arrived as an ordinary error, so the shared data-error card rendered it as a failed fetch:
 * "this is usually temporary, wait a moment and try again" — false — with a Try again button
 * that could never succeed and no link to the appeal that the server's own message tells the
 * user to go and find. The appeal endpoint was reachable the entire time.
 *
 * Source assertions rather than a render, because vitest runs in the `node` environment here
 * (see vitest.config.ts) and there is no DOM to mount into. What matters is checkable either
 * way: which branch the copy and the actions sit behind.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

import { ApiError } from '@/lib/api/errors';

const CARD = readFileSync(join(__dirname, 'data-error.tsx'), 'utf8');

describe('the error object can tell a suspension from any other 403', () => {
  const suspended = () =>
    new ApiError(
      403,
      'FORBIDDEN',
      'This account is suspended because it was used from two places at once.',
      { reason: 'shared_account', appealable: true },
      'req_1',
      'ACCOUNT_BANNED',
    );

  it('recognises it by the server code, not by the message', () => {
    expect(suspended().isAccountSuspended).toBe(true);
    expect(suspended().isAppealable).toBe(true);
  });

  it('does not mistake an ordinary 403 for a suspension', () => {
    // THE FAILURE THIS PREVENTS IS THE WORSE DIRECTION: showing "your account is suspended"
    // to somebody who merely lacked permission for one thing.
    const plain = new ApiError(403, 'FORBIDDEN', 'Not your report', undefined, 'req_2');
    expect(plain.isAccountSuspended).toBe(false);
    expect(plain.isAppealable).toBe(false);
  });

  it('keys on the code so rewording the message cannot break it', () => {
    // The sentence lives in one place server-side and will be reworded. A client matching on
    // prose would silently stop recognising suspensions, and the dead-end screen would come
    // back with no code change to blame it on.
    const reworded = new ApiError(
      403,
      'FORBIDDEN',
      'Completely different wording, decided later.',
      { appealable: true },
      undefined,
      'ACCOUNT_BANNED',
    );
    expect(reworded.isAccountSuspended).toBe(true);
  });

  it('treats a missing appealable flag as appealable', () => {
    // Hiding the only route out because a field went missing is the worse way to be wrong.
    const noFlag = new ApiError(403, 'FORBIDDEN', 'suspended', {}, undefined, 'ACCOUNT_BANNED');
    expect(noFlag.isAppealable).toBe(true);
  });

  it('respects an explicit non-appealable suspension', () => {
    // So a future ban that a form cannot resolve is not pointed at one that will refuse it.
    const final = new ApiError(
      403,
      'FORBIDDEN',
      'suspended',
      { appealable: false },
      undefined,
      'ACCOUNT_BANNED',
    );
    expect(final.isAccountSuspended).toBe(true);
    expect(final.isAppealable).toBe(false);
  });

  it('carries the server code through the envelope rather than discarding it', () => {
    // This is the plumbing the whole fix rests on: `code` is derived from the HTTP status, so
    // the application's own code had nowhere to live and was being dropped.
    const err = new ApiError(403, 'FORBIDDEN', 'x', {}, undefined, 'ACCOUNT_BANNED');
    expect(err.code).toBe('FORBIDDEN');
    expect(err.serverCode).toBe('ACCOUNT_BANNED');
  });
});

describe('the card says something true and offers something that works', () => {
  it('suppresses the retry hint for a suspension', () => {
    // "Usually temporary, wait a moment and try again" is true of a cold backend and false of
    // a suspended account.
    expect(CARD).toMatch(/hint && !suspended/);
  });

  it('does not offer Try again on a suspension', () => {
    // A button that can never succeed reads as the product being broken rather than as the
    // account being paused.
    // Anchored on the ACTIONS block. `suspended ? (` also appears earlier for the icon, and
    // slicing from that one spans the whole card and picks up the retry branch that legitimately
    // still exists for ordinary errors — which is how this assertion first passed a broken read.
    const at = CARD.indexOf('THE ROUTE OUT IS THE PRIMARY ACTION');
    expect(at).toBeGreaterThan(-1);
    const actions = CARD.slice(at, CARD.indexOf('{children}', at));
    const suspendedBranch = actions.slice(0, actions.indexOf(') : ('));
    expect(suspendedBranch).not.toMatch(/onRetry/);
    expect(suspendedBranch).toContain('/account/appeal');
    // And the retry path is still there for everything that is not a suspension.
    expect(actions).toMatch(/onRetry/);
  });

  it('links to the appeal, which is the whole point', () => {
    expect(CARD).toContain('/account/appeal');
    expect(CARD).toMatch(/appealable &&/);
  });

  it('says the suspension lifts on its own', () => {
    // The single most useful sentence on the screen: the difference between "I have lost my
    // account" and "I get back in tomorrow".
    expect(CARD).toMatch(/unlocks by itself|lifts by itself|on its own/i);
  });

  it('names no exact duration', () => {
    // The window escalates for repeats, so a figure here would be wrong for exactly the
    // accounts most likely to read it twice.
    const at = CARD.indexOf('Access is paused because');
    const copy = CARD.slice(at, at + 400);
    expect(copy).not.toMatch(/\b24 hours?\b|\b\d+ hours?\b|\b\d+ days?\b/);
  });
});
