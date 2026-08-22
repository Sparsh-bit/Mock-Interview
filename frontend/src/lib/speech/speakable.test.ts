import { describe, expect, it } from 'vitest';

import { toSpokenForm } from './speakable';

/**
 * Reported from a real session, with a screenshot: the panel asked "what's the difference
 * between == and === in JavaScript?" and read it aloud as "equal equal" and "equal equal
 * equal". It also said "oop" as a word rather than O-O-P.
 *
 * The thing these tests are really protecting is that this only ever touches the SPOKEN
 * copy. The line on screen and the transcript keep the operators, because a transcript that
 * says "double equals" gets quoted back in a follow-up and printed in the candidate's report
 * as though they had typed it.
 */
describe('toSpokenForm', () => {
  it('reads the reported sentence correctly', () => {
    const spoken = toSpokenForm("what's the difference between == and === in JavaScript?");
    expect(spoken).toContain('double equals');
    expect(spoken).toContain('triple equals');
    expect(spoken).not.toContain('==');
  });

  it('does the LONGEST operator first', () => {
    // The ordering bug this guards: with `==` first, `===` becomes "double equals equals",
    // which is worse than leaving it alone.
    expect(toSpokenForm('a === b')).toBe('a triple equals b');
    expect(toSpokenForm('a !== b')).toBe('a strict not equals b');
    expect(toSpokenForm('i++')).toBe('i plus plus');
  });

  it.each([
    ['a != b', 'not equals'],
    ['x <= y', 'less than or equal to'],
    ['x >= y', 'greater than or equal to'],
    ['a && b', ' and '],
    ['a || b', ' or '],
    ['x => x * 2', 'arrow'],
    ['int x = 5', 'equals'],
  ])('speaks %j as words', (written, expected) => {
    expect(toSpokenForm(written)).toContain(expected.trim());
  });

  it('spells out the acronyms an engine reads as words', () => {
    expect(toSpokenForm('the OOP pillars')).toBe('the O.O.P pillars');
    expect(toSpokenForm('OOPS concepts')).toContain('O.O.P.S');
    expect(toSpokenForm('the JVM runs it')).toContain('J.V.M');
    expect(toSpokenForm('DBMS and JDBC')).toBe('D.B.M.S and J.D.B.C');
  });

  it('leaves alone the acronyms engines already say correctly', () => {
    // Over-riding one that worked makes it worse — "A.P.I." comes out with odd pauses, and
    // both "sequel" and "S-Q-L" are how engineers really say SQL.
    expect(toSpokenForm('a REST API over HTTP')).toBe('a REST API over HTTP');
    expect(toSpokenForm('write the SQL query')).toBe('write the SQL query');
    expect(toSpokenForm('parse the JSON')).toBe('parse the JSON');
  });

  it('does not recite code-fence punctuation', () => {
    // "backtick backtick backtick java" is nonsense in the ear. The candidate can see the
    // code; the voice should talk about it.
    expect(toSpokenForm('look at ```java\nint x;\n```')).not.toContain('`');
  });

  it('leaves ordinary prose completely alone', () => {
    // The overwhelmingly common case. Anything this touches unnecessarily is a sentence
    // read out wrong.
    const prose = 'Tell me about a project where you had to make a difficult trade-off.';
    expect(toSpokenForm(prose)).toBe(prose);
  });

  it('does not mangle an equals sign inside a word or a URL', () => {
    // Only a genuinely free-standing `=` is an operator being read as a comparison.
    expect(toSpokenForm('see docs?id=42')).toBe('see docs?id=42');
  });

  it('is idempotent', () => {
    // The hook may polish a line more than once on the fallback path.
    const once = toSpokenForm('a == b and the OOP pillars');
    expect(toSpokenForm(once)).toBe(once);
  });

  it('handles an empty string without throwing', () => {
    expect(toSpokenForm('')).toBe('');
  });
});

describe('stage directions are performed, not pronounced', () => {
  /*
   * "i cannot see the panaelist laugh and a sort of smile and all the gestures that the
   * normal human do in an interview".
   *
   * The panel was already laughing. Rule 5 of prompts/interview_panel.md instructs it to and
   * gives the exact format — "*(laughs)* No, fair enough.", "*(both laugh)*" — so the model
   * was doing as it was told. Nothing translated the marker, so the vendor received the
   * literal string and a panelist SAID THE WORD "laughs" where a human would have laughed.
   *
   * That is worse than no laughter: it is uncanny, and it lands at exactly the moments meant
   * to make the panel feel like people.
   */
  it('drops the asterisk-wrapped form the prompt asks for', () => {
    expect(toSpokenForm('*(laughs)* No, fair enough.')).toBe('No, fair enough.');
    expect(toSpokenForm('*(both laugh)* Okay, next one.')).toBe('Okay, next one.');
  });

  it('drops the bare form too, because the model omits the asterisks', () => {
    expect(toSpokenForm('(laughs) Right, moving on.')).toBe('Right, moving on.');
    expect(toSpokenForm('(chuckles) Fair.')).toBe('Fair.');
    expect(toSpokenForm('(smiles) Go on.')).toBe('Go on.');
  });

  it('NEVER strips real parenthetical speech', () => {
    // The line that makes this safe. An unrestricted `(...)` strip would silently delete
    // content the candidate needs to hear — and a question missing its qualifier is a
    // different question.
    expect(toSpokenForm('The JDK (which includes the compiler) is what you need.')).toContain(
      'which includes the compiler',
    );
    expect(toSpokenForm('Explain the difference (briefly is fine).')).toContain('briefly is fine');
  });

  it('leaves the spoken words either side intact and tidy', () => {
    // The laugh becomes a real pause where the marker was, which is what the surrounding
    // words already carry. No double spaces, no space before the full stop.
    expect(toSpokenForm('Ha — okay. *(laughs)* That is one way to put it.')).toBe(
      'Ha — okay. That is one way to put it.',
    );
  });

  it('is still idempotent', () => {
    const once = toSpokenForm('*(laughs)* Tell me about HashMap.');
    expect(toSpokenForm(once)).toBe(once);
  });
});

describe('panelist names are pronounced, not mangled', () => {
  /*
   * "one of them is saying raya insted of riya."
   *
   * Correct: the vendor read "Riya" with a long English i, which is a different name. A panel
   * that cannot say its own members' names is the most obviously wrong thing it can do, and it
   * happens on the very first turn, where they greet each other.
   *
   * Respelled rather than phoneme-tagged: Fish's pronunciation markup is model-specific and
   * undocumented for these voices, and a tag the model does not understand gets READ OUT —
   * which is exactly how "*(laughs)*" became a spoken word. Plain respelling cannot be recited.
   */
  it('says Riya, not Raya', () => {
    expect(toSpokenForm('Riya, what do you think?')).toBe('Reeya, what do you think?');
  });

  it('does not match Riya inside Priya', () => {
    // Order matters: "Priya" contains "riya". Getting this wrong turns one name into
    // "PReeya"-with-a-stray-P or worse, and it would only show up for one panelist.
    expect(toSpokenForm('Priya, over to you.')).toBe('Preeya, over to you.');
    expect(toSpokenForm('Priya and Riya')).toBe('Preeya and Reeya');
  });

  it('leaves the written line alone — this is the SPOKEN form only', () => {
    // PanelThread renders line.text, so the screen still says Riya. A transcript that said
    // "Reeya" would be quoted back in the candidate's report.
    const written = 'Riya, what do you think?';
    expect(written).toContain('Riya');
    expect(toSpokenForm(written)).not.toContain('Riya');
  });

  it('only touches whole words', () => {
    expect(toSpokenForm('Riyadh')).toBe('Riyadh');
  });

  it('no respelling contains a hyphen or a filler syllable', () => {
    /*
     * THE RULE THAT CAUGHT MY OWN MISTAKE, so it cannot happen again.
     *
     * Anil was first respelled "Uh-neel", which renders as "Thanks uh… neel": a synthesiser
     * reads "Uh" as a hesitation filler and a hyphen as a pause, so the panel sounded like it
     * had forgotten the name — worse than the mispronunciation it replaced.
     *
     * A respelling has to survive being read by something that knows nothing about why it is
     * spelled that way. Asserted on the OUTPUT rather than on the table, so any future entry is
     * covered whether or not somebody remembers this comment.
     */
    const FILLERS = /^(uh|um|er|ah|hmm|eh)\b/i;
    for (const name of ['Anil', 'Priya', 'Riya', 'Arjun', 'Meera']) {
      const spoken = toSpokenForm(name);
      expect(spoken, `${name} -> ${spoken}`).not.toContain('-');
      expect(FILLERS.test(spoken), `${name} -> ${spoken} starts with a filler`).toBe(false);
      // And it must be a single word: a space is a pause too.
      expect(spoken.trim().split(/\s+/), `${name} -> ${spoken}`).toHaveLength(1);
    }
  });

  it('says Aneel, not the AY-nil engines default to', () => {
    expect(toSpokenForm('Thanks Anil.')).toBe('Thanks Aneel.');
    expect(toSpokenForm("That's Anil's question")).toBe("That's Aneel's question");
  });

  it('is still idempotent over names', () => {
    const once = toSpokenForm('Riya and Priya');
    expect(toSpokenForm(once)).toBe(once);
  });
});
