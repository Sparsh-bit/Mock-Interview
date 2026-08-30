import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * RETENTION WITHOUT COMPULSION — components/dashboard/retention-copy.test.ts
 *
 * The two cards added to the nudge deck — pick up an unfinished interview, and a streak that
 * today has not extended — are the two places in this product most likely to grow a dark
 * pattern, because the obvious version of each is the manipulative one:
 *
 *     rejected: "Your 6-day streak ends in 3h 12m!" with a countdown
 *     rejected: "Don't lose your progress — finish now"
 *     rejected: "You're falling behind other candidates"
 *
 * None of those is hypothetical; all three are what a streak card usually says. This file
 * exists so writing one fails the build rather than shipping.
 *
 * WHY IT IS ENFORCED RATHER THAN INTENDED. `docs/COMPLIANCE.md` records that this product has
 * no reliable way to know it is not talking to somebody under 18 — the signup age declaration
 * has a documented window — and DPDP §9 prohibits behavioural monitoring and targeted
 * advertising directed at children. Urgency mechanics are exactly the ones that would be a
 * problem if a minor reached them, and the honest answer is to not build them for anybody.
 *
 * The existing deck already had a rule of this shape — DESIGN-RULES.md bans vague superlatives
 * and unsupported claims, and every card carries a number the candidate can check. These two
 * cards inherit that and add the absence of pressure to it.
 */

const DECK = readFileSync(join(process.cwd(), 'src/components/dashboard/NudgeDeck.tsx'), 'utf8');
const HOOK = readFileSync(join(process.cwd(), 'src/hooks/useProgress.ts'), 'utf8');

/** Only the strings a candidate can actually read, so a test cannot match its own comments. */
const COPY = [...DECK.matchAll(/(?:hook|fact|cta):\s*[`'"]([^`'"]*)[`'"]/g)]
  .map((m) => m[1].toLowerCase())
  .join(' | ');

describe('the deck says something true to somebody already looking at it', () => {
  it('offers an unfinished interview back', () => {
    expect(DECK).toContain('progress?.resume');
    expect(DECK).toContain('/session/${progress.resume.session_id}');
  });

  it('names how far in they got, which is the reason to come back', () => {
    expect(DECK).toContain('progress.resume.questions_answered');
  });

  it('shows the streak card only when there is a real run', () => {
    // One day is not a streak, and a card about it would be noise on somebody's first visit.
    expect(DECK).toContain('progress.streak.days >= 2');
  });

  it('shows it only when today is still open', () => {
    // Telling somebody who has already practised today that they should practise today is the
    // fastest way to make the whole deck ignorable.
    expect(DECK).toContain('progress.streak.at_risk');
  });

  it('offers the free thing, not the paid one', () => {
    // A streak card that routes to a ₹-priced round is an advert wearing a habit's clothes.
    // Quizzes are free and unlimited, so keeping a run costs nothing.
    const card = DECK.slice(DECK.indexOf("key: 'streak-open'"));
    expect(card.slice(0, card.indexOf('});'))).toContain("href: '/quiz'");
  });
});

describe('no manufactured urgency', () => {
  it('never counts down', () => {
    for (const word of ['ends in', 'expires', 'hours left', 'minutes left', 'countdown', 'deadline', 'tonight', 'last chance', 'hurry']) {
      expect(COPY).not.toContain(word);
    }
  });

  it('does not render the resume card as a deadline', () => {
    // `hours_ago` is available and deliberately unused in the copy: it is elapsed time, and
    // the only thing it could add to a card is pressure.
    const card = DECK.slice(DECK.indexOf('key: `resume-'));
    expect(card.slice(0, card.indexOf('});'))).not.toContain('hours_ago');
  });

  it('has no timer anywhere in the progress hook', () => {
    // A poll or a focus-refetch makes the streak flicker and update while somebody watches it,
    // which is the visual language of a live counter — the thing this is not.
    expect(HOOK).toContain('refetchOnWindowFocus: false');
    expect(HOOK).not.toContain('refetchInterval');
  });
});

describe('no guilt and no comparison', () => {
  it('never characterises the candidate for not practising', () => {
    for (const phrase of ["don't lose", 'dont lose', 'falling behind', 'you failed', 'you missed', 'broke your', 'lost your']) {
      expect(COPY).not.toContain(phrase);
    }
  });

  it('never compares them to anybody else', () => {
    for (const phrase of ['other candidates', 'everyone else', 'top 10%', 'better than', 'most users', 'others are']) {
      expect(COPY).not.toContain(phrase);
    }
  });

  it('states the streak as something they have, not something at risk', () => {
    const card = DECK.slice(DECK.indexOf("key: 'streak-open'"));
    const text = card.slice(0, card.indexOf('});')).toLowerCase();
    expect(text).toContain('in a row so far');
    expect(text).not.toContain('lose');
    expect(text).not.toContain('keep it');
  });
});

describe('no variable reward', () => {
  it('the streak grants nothing', () => {
    // No credits, no multiplier, no bonus, no unlock. If a reward is ever attached it has to
    // be attached in the copy or the type, and both are checked.
    for (const word of ['bonus', 'multiplier', 'reward', 'unlock', 'free credit', 'x2', 'double']) {
      expect(COPY).not.toContain(word);
    }
  });

  it('the progress type carries no reward field', () => {
    for (const word of ['bonus', 'multiplier', 'reward']) {
      expect(HOOK.toLowerCase()).not.toContain(`${word}:`);
    }
  });
});

describe('nothing is pushed to anybody', () => {
  it('the deck is rendered, never sent', () => {
    // The brief's hard rule: no re-engagement message without real consent. There is no
    // outbound channel in this product at all, and this asserts the streak did not become the
    // first one by way of the browser.
    for (const api of ['Notification(', 'requestPermission', 'showNotification', 'serviceWorker', 'navigator.sendBeacon']) {
      expect(DECK).not.toContain(api);
      expect(HOOK).not.toContain(api);
    }
  });
});
