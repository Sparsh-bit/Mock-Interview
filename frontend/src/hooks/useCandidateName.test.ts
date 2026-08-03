import { describe, expect, it } from 'vitest';

import { speakableFirstWord } from './useCandidateName';

/**
 * The panel says this name out loud. A GD where "Arjun" turns to the candidate and
 * says "sparsh.sharma22, what do you think" is worse than one that says nothing, so
 * every shape a name arrives in has to come out speakable — or come out empty, which
 * the callers treat as "do not use a name at all".
 */
describe('speakable first name', () => {
  it('takes the first word of a full name', () => {
    expect(speakableFirstWord('Sparsh Sharma')).toBe('Sparsh');
    expect(speakableFirstWord('Priya  Krishnan Iyer')).toBe('Priya');
  });

  it('capitalises a lowercase name', () => {
    // Signing up with a lowercase name is common, and a panelist saying it back in
    // the transcript as "sparsh" reads as a bug.
    expect(speakableFirstWord('sparsh')).toBe('Sparsh');
  });

  it('leaves an already-capitalised name alone', () => {
    expect(speakableFirstWord('Rahul')).toBe('Rahul');
    // Not lowercased mid-word — "McCarthy" must not become "Mccarthy".
    expect(speakableFirstWord('McCarthy Joseph')).toBe('McCarthy');
  });

  it('handles the email local part, which is the last-resort source', () => {
    expect(speakableFirstWord('sparsh.sharma22')).toBe('Sparsh');
    expect(speakableFirstWord('priya_k')).toBe('Priya');
    expect(speakableFirstWord('rahul-verma')).toBe('Rahul');
    expect(speakableFirstWord('anita+campus')).toBe('Anita');
  });

  it('strips digits and punctuation rather than speaking them', () => {
    expect(speakableFirstWord('arjun2024')).toBe('Arjun');
    expect(speakableFirstWord('k.r.sundar')).toBe('');
  });

  it('returns empty rather than something unusable', () => {
    // Callers fall back to "the candidate" on empty. A one-letter or numeric
    // handle is not a name, and pretending it is produces "N, what do you think".
    expect(speakableFirstWord('')).toBe('');
    expect(speakableFirstWord('   ')).toBe('');
    expect(speakableFirstWord('a')).toBe('');
    expect(speakableFirstWord('12345')).toBe('');
    expect(speakableFirstWord('_')).toBe('');
  });
});
