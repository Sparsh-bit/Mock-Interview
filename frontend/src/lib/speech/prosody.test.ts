import { describe, expect, it } from 'vitest';

import { DEFAULT_PERSONA, personaFor, personasDistinguishable } from './persona';
import { shapingFor, toProsodyChunks } from './prosody';

/**
 * The user's ask was that the AI "sound like real panelists". These two modules
 * are the whole of what speechSynthesis will let us do about that — utterance
 * boundaries, the silence between them, and rate — so this is where the effect
 * either exists or does not.
 *
 * The failure mode being guarded is specific and silent: numbers in a table that
 * are too close together to hear. There is no way to catch that by listening once
 * on one machine, so the thresholds are asserted.
 */

/** The real stances, verbatim from backend/app/api/v1/gd.py PANELISTS. */
const RIYA =
  'Assertive and data-driven. Opens strong, quotes numbers and examples, ' +
  'and challenges vague claims directly. Dominates if nobody pushes back.';
const ARJUN =
  'Takes the opposing side on principle and argues it well. Interrupts to ' +
  'disagree, concedes only to a concrete point, and enjoys the debate.';
const MEERA =
  'The synthesiser. Listens, finds the middle ground, and brings quiet ' +
  'people in — she is usually the one who asks the candidate directly.';

describe('speaker personas', () => {
  it('gives each of the three real panelists a distinct delivery', () => {
    const personas = [RIYA, ARJUN, MEERA].map(personaFor);
    // The point of the module. If this fails, three people are reading in one
    // voice at one speed, which is the thing it was built to prevent.
    expect(personasDistinguishable(personas)).toBe(true);
  });

  it('reads the disposition, not the name', () => {
    // Names are the server's data and may change; dispositions are what decide how
    // someone talks. A renamed panelist must keep their delivery.
    expect(personaFor(RIYA).tempo).toBeGreaterThan(personaFor(MEERA).tempo);
    expect(personaFor(ARJUN).leadInMs).toBeLessThan(personaFor(MEERA).leadInMs);
  });

  it('makes the contrarian latch on and the synthesiser wait', () => {
    // This is the characterisation that carries the most for the least risk: how
    // long someone waits before taking the floor.
    expect(personaFor(ARJUN).leadInMs).toBeLessThan(150);
    expect(personaFor(MEERA).leadInMs).toBeGreaterThan(400);
  });

  it('keeps every lead-in inside the believable band', () => {
    // Under ~80ms reads as a glitch; over ~700ms reads as the app having hung.
    for (const s of [RIYA, ARJUN, MEERA, undefined]) {
      const { leadInMs } = personaFor(s);
      expect(leadInMs).toBeGreaterThanOrEqual(80);
      expect(leadInMs).toBeLessThanOrEqual(700);
    }
  });

  it('falls back to neutral rather than wrong for an unknown stance', () => {
    expect(personaFor(undefined)).toEqual(DEFAULT_PERSONA);
    expect(personaFor('')).toEqual(DEFAULT_PERSONA);
    expect(personaFor('A fourth panelist with a brand new disposition.')).toEqual(DEFAULT_PERSONA);
  });

  it('rejects tempos that are notionally different and audibly identical', () => {
    // The regression this guards: an earlier draft had 1.08 / 1.05, a 3% gap. The
    // module's own documentation says ~8% is the audible threshold, so 3% is a
    // number in a table and nothing in the ear.
    expect(
      personasDistinguishable([
        { tempo: 1.08, leadInMs: 200 },
        { tempo: 1.05, leadInMs: 200 },
      ]),
    ).toBe(false);
  });

  it('accepts a pair separated on only one channel', () => {
    // Same tempo is fine if one of them visibly waits and the other does not.
    expect(
      personasDistinguishable([
        { tempo: 1.0, leadInMs: 90 },
        { tempo: 1.0, leadInMs: 520 },
      ]),
    ).toBe(true);
  });
});

describe('clause segmentation', () => {
  it('gives each sentence its own utterance and a real pause after it', () => {
    const chunks = toProsodyChunks('Remote work saves commute time. But it costs mentoring.');
    expect(chunks).toHaveLength(2);
    expect(chunks[0].pauseAfterMs).toBeGreaterThan(250);
  });

  it('breaks at an em dash and holds the clause bare', () => {
    // The dash in this prompt is always a snap-off. A comma there would both drawl
    // the clause and make the engine add its own silence on top, turning a 200ms
    // clip into a 400ms sag.
    const chunks = toProsodyChunks('Hold on — that is not what the data says.');
    expect(chunks).toHaveLength(2);
    expect(chunks[0].text).toBe('Hold on');
    expect(chunks[0].text.endsWith(',')).toBe(false);
    expect(chunks[0].pauseAfterMs).toBeGreaterThan(0);
  });

  it('appends a continuation comma only where the contour needs it', () => {
    // An utterance ending bare gets the falling contour of a full stop, which turns
    // one thought into a list of statements. A colon-separated clause continues.
    const chunks = toProsodyChunks('There are two problems: cost and mentoring.');
    expect(chunks).toHaveLength(2);
    expect(chunks[0].text.endsWith(',')).toBe(true);
  });

  it('holds the longest silence after a question, because you wait for the answer', () => {
    const chunks = toProsodyChunks('So what do you think, Sparsh?');
    const last = chunks[chunks.length - 1];
    expect(last.isQuestion).toBe(true);
    expect(last.isFinal).toBe(true);
    expect(last.pauseAfterMs).toBeGreaterThanOrEqual(700);
  });

  it('lets the caller own the gap after a closing statement', () => {
    // The panel passes 0 because the next speaker's lead-in owns it; the lone
    // interviewer passes 250 because nothing follows them.
    expect(toProsodyChunks('That is my view.', { finalPauseMs: 0 }).at(-1)!.pauseAfterMs).toBe(0);
    expect(toProsodyChunks('That is my view.', { finalPauseMs: 250 }).at(-1)!.pauseAfterMs).toBe(250);
  });

  it('splits at sentences ONLY on a cloud voice, and holds no explicit pause', () => {
    // These fetch audio per utterance, so extra utterances are extra network round
    // trips inserted mid-sentence — on Indian student mobile data that is what
    // makes a panelist sound like they are buffering rather than thinking. The
    // engine's own fetch gap is the beat there.
    const text = 'Hold on — that is wrong. There are two issues: cost, and mentoring.';
    const local = toProsodyChunks(text);
    const cloud = toProsodyChunks(text, { networkVoice: true });
    expect(cloud).toHaveLength(2);
    expect(local.length).toBeGreaterThan(cloud.length);
    // No questions in this text, so nothing here has a "your turn" cue to hold.
    expect(cloud.every((c) => c.pauseAfterMs === 0)).toBe(true);
  });

  it('keeps the "your turn" pause even on a cloud voice', () => {
    // The sentence gap is only standing in for a breath, which the engine's fetch
    // already supplies. The pause after a question is not — it is the candidate's
    // cue to speak, and nothing else provides it.
    const cloud = toProsodyChunks('So what would you do, Sparsh?', { networkVoice: true });
    expect(cloud.at(-1)!.pauseAfterMs).toBeGreaterThanOrEqual(700);
  });

  it('caps how many times one sentence can be broken', () => {
    // A person pivots mid-sentence once, occasionally twice. Never five times.
    const chunks = toProsodyChunks('One — two — three — four — five.');
    expect(chunks.length).toBeLessThanOrEqual(3);
  });

  it('never emits an utterance with nothing to say in it', () => {
    // A leading or doubled separator yields an empty body, and speaking it is a
    // stray beat of silence the listener reads as a glitch.
    for (const text of ['— well, no.', 'Yes... ... no.', '  ...  ', '?']) {
      for (const c of toProsodyChunks(text)) {
        expect(c.text).toMatch(/[a-z0-9]/i);
      }
    }
  });

  it('returns nothing for empty input rather than one empty utterance', () => {
    expect(toProsodyChunks('')).toEqual([]);
    expect(toProsodyChunks('   ')).toEqual([]);
  });

  it('marks exactly one chunk as final', () => {
    const chunks = toProsodyChunks('First point. Second point — and a rider. Third.');
    expect(chunks.filter((c) => c.isFinal)).toHaveLength(1);
    expect(chunks[chunks.length - 1].isFinal).toBe(true);
  });
});

describe('emphasis tagging', () => {
  it('clips a short pivot and weights the clause it bought', () => {
    // This is what an interruption sounds like: you win the floor fast, then land
    // the point slowly.
    const chunks = toProsodyChunks('Wait — the cost argument ignores attrition.');
    expect(chunks[0].emphasis).toBe('urgent');
    expect(chunks[1].emphasis).toBe('weighted');
    expect(shapingFor(chunks[0])).toBeGreaterThan(1);
    expect(shapingFor(chunks[1])).toBeLessThan(1);
  });

  it('does NOT slow a whole sentence because of its first word', () => {
    // The regression this exists for: gd_panel.md instructs the model to open
    // roughly one turn in three with a verbal gesture, so matching those openers
    // meant re-timing a third of all panel speech. An opener long enough to be an
    // argument gets no emphasis at all.
    const long = toProsodyChunks(
      'Actually the thing that gets missed here is that juniors lose the mentoring nobody costs in.',
    );
    expect(long[0].emphasis).toBeNull();
    // Compared against the same chunk with emphasis forced on, so this isolates
    // the emphasis contribution from the turn-final lengthening it also carries.
    expect(shapingFor(long[0])).toBe(shapingFor({ ...long[0], emphasis: null }));
    expect(shapingFor(long[0])).toBeGreaterThan(shapingFor({ ...long[0], emphasis: 'weighted' }));
  });

  it('ignores throat-clearing that is not a pivot', () => {
    // "Hmm", "See," and "Okay so," are how the prompt tells the model to sound
    // human. They are not someone turning against what was just said.
    for (const opener of ['Hmm, that is fair.', 'See, the cost is real.', 'Okay so, two things.']) {
      expect(toProsodyChunks(opener)[0].emphasis).toBeNull();
    }
  });

  it('never weights a chunk that follows nothing urgent', () => {
    const chunks = toProsodyChunks('The data is clear. Attrition rose.');
    expect(chunks.every((c) => c.emphasis === null)).toBe(true);
  });
});

describe('rate shaping', () => {
  it('slows the clause a speaker ends on, which is the cue the floor is free', () => {
    expect(shapingFor({ isQuestion: false, isFinal: true, emphasis: null })).toBeLessThan(1);
    expect(shapingFor({ isQuestion: true, isFinal: true, emphasis: null })).toBeLessThan(
      shapingFor({ isQuestion: false, isFinal: true, emphasis: null }),
    );
  });

  it('leaves a mid-contribution statement alone', () => {
    expect(shapingFor({ isQuestion: false, isFinal: false, emphasis: null })).toBe(1);
  });

  it('floors the compounded slowdown before it reaches the engine', () => {
    // Every slow factor stacks on the same panelist: local synthesis 0.94 × the
    // synthesiser's 0.92 tempo × a question's 0.94 × weighted 0.94 is 0.76, and a
    // neural Indian voice at 0.76 does not sound considered — it sounds like it is
    // buffering, which is what voice-ranking.ts was rewritten to escape.
    const worst = shapingFor({ isQuestion: true, isFinal: true, emphasis: 'weighted' });
    expect(worst).toBeGreaterThanOrEqual(0.9);
    // And with the persona and local-synthesis factors on top, still audible.
    expect(0.94 * personaFor(MEERA).tempo * worst).toBeGreaterThan(0.75);
  });

  it('keeps the urgent lift from stacking into a squeak', () => {
    expect(shapingFor({ isQuestion: false, isFinal: false, emphasis: 'urgent' })).toBeLessThan(1.15);
  });
});
