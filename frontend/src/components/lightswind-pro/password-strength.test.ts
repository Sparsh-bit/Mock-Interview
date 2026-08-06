import { describe, expect, it } from 'vitest';

import { scorePassword } from './password-strength';

/**
 * The strength meter is the only one of these components with real logic, and a strength
 * meter that lies is worse than none: it teaches the wrong lesson to someone choosing the
 * password that protects their account.
 *
 * The thing being asserted is the WEIGHTING — that length beats punctuation, because that is
 * where the entropy actually is, and most meters get it backwards.
 */
describe('password strength', () => {
  it('rejects anything under the minimum outright', () => {
    expect(scorePassword('')).toBe(0);
    expect(scorePassword('Ab1!')).toBe(0);
    expect(scorePassword('Abc123!')).toBe(0); // 7 characters
  });

  it('values LENGTH over punctuation, which is the whole point', () => {
    // The classic "strong" password is short and full of symbols; the passphrase is longer
    // and has a far bigger search space. A meter that ranks these the other way round is
    // teaching people to pick the weaker one.
    const symbolSoup = scorePassword('P@ss1!xY');
    const passphrase = scorePassword('correct horse battery staple');
    expect(passphrase).toBeGreaterThan(symbolSoup);
  });

  it('cannot call a short password strong however many character classes it has', () => {
    expect(scorePassword('aB3$xY7z')).toBeLessThan(4);
  });

  it('rewards real length', () => {
    const short = scorePassword('abcdefghij12');
    const long = scorePassword('thequickbrownfoxjumps');
    expect(long).toBeGreaterThanOrEqual(short);
    expect(scorePassword('a-very-long-and-varied-Passphrase-99')).toBe(4);
  });

  it('caps an obvious sequence, however long it is', () => {
    // "abcd1234..." clears every length bar and is the first thing a cracker tries. A green
    // bar on it would be actively misleading.
    expect(scorePassword('abcd1234abcd1234')).toBeLessThanOrEqual(2);
    expect(scorePassword('qwerty12345678901')).toBeLessThanOrEqual(2);
  });

  it('caps a repeated run', () => {
    expect(scorePassword('aaaaaaaaaaaaaaaa')).toBeLessThanOrEqual(2);
  });

  it('never returns a score outside the band the UI renders', () => {
    // The component indexes a five-element array with this. An out-of-range score is a
    // crash on the signup form.
    for (const pw of ['', 'a', 'short', 'abcd1234', 'A'.repeat(200), 'correct horse battery staple']) {
      const s = scorePassword(pw);
      expect(s).toBeGreaterThanOrEqual(0);
      expect(s).toBeLessThanOrEqual(4);
    }
  });
});
