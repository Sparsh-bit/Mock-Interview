/**
 * The one deep-link param that outlived the drive card — params.test.ts
 *
 * `parseIsTechnical` decides whether an interview has a code editor, whether coding questions
 * are asked, and whether the panel are engineers or their own field's managers. It is the
 * highest-consequence thing a URL can assert about a session, so the parse stays strict and
 * these are the cases that keep it that way.
 *
 * Carried over from drive.test.ts, which went with the drive card. The other ~200 lines there
 * tested link-building and a hardcoded '24 August' date, neither of which exists any more.
 */

import { describe, expect, it } from 'vitest';

import { parseIsTechnical } from './params';

describe('parseIsTechnical', () => {
  it('accepts exactly the two literals', () => {
    expect(parseIsTechnical('true')).toBe(true);
    expect(parseIsTechnical('false')).toBe(false);
  });

  it('returns null for anything else, so the page works it out from the role instead', () => {
    // null is not "unknown, guess technical" — it is the setup page's existing default path. A
    // malformed link must degrade to a guess, never assert the wrong answer.
    const notLiterals = [
      null,
      '',
      '1',
      '0',
      'yes',
      'no',
      'TRUE',
      'False',
      ' true',
      'true ',
      'tru',
      'true&isTechnical=false',
    ];
    for (const raw of notLiterals) {
      expect(parseIsTechnical(raw)).toBeNull();
    }
  });

  it('never throws, whatever arrives', () => {
    // Every value reaching this function is now hand-edited or pasted, since nothing in the
    // app generates the link any more.
    for (const raw of ['<script>', '../../etc/passwd', '   ', '%%%']) {
      expect(() => parseIsTechnical(raw)).not.toThrow();
    }
  });
});
