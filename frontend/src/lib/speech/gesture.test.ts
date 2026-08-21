import { describe, expect, it } from 'vitest';

import { hasGesture, splitGestures } from './gesture';
import { toSpokenForm } from './speakable';

/**
 * A laugh is performed, not printed and not pronounced — lib/speech/gesture.test.ts
 *
 * "i cannot see the panaelist laugh and a sort of smile and all the gestures that the normal
 * human do in an interview."
 *
 * The panel was already laughing — rule 5 of prompts/interview_panel.md instructs it to, with
 * the exact format. Both consumers then failed with the result: the voice said the WORD
 * "laughs", and the screen printed the characters `*(laughs)*`. So the one feature written to
 * make the room feel human was the thing that made it feel like a machine.
 *
 * The last test in this file is the important one: the eye and the ear must agree about what
 * a gesture is. They disagreed by omission before, and that is how the marker reached the
 * vendor at all.
 */
describe('splitting a line into what was said and what was done', () => {
  it('keeps an ordinary line as one piece', () => {
    const parts = splitGestures('Tell me about your project.');
    expect(parts).toEqual([{ kind: 'said', text: 'Tell me about your project.' }]);
  });

  it('separates the asterisk-wrapped form the prompt asks for', () => {
    expect(splitGestures('*(laughs)* No, fair enough.')).toEqual([
      { kind: 'gesture', text: 'laughs' },
      { kind: 'said', text: 'No, fair enough.' },
    ]);
  });

  it('separates the bare form, because the model omits the asterisks', () => {
    expect(splitGestures('(both laugh) Okay, next one.')).toEqual([
      { kind: 'gesture', text: 'both laugh' },
      { kind: 'said', text: 'Okay, next one.' },
    ]);
  });

  it('handles a direction in the middle of a line', () => {
    expect(splitGestures('Ha — okay. *(laughs)* That is one way to put it.')).toEqual([
      { kind: 'said', text: 'Ha — okay.' },
      { kind: 'gesture', text: 'laughs' },
      { kind: 'said', text: 'That is one way to put it.' },
    ]);
  });

  it('NEVER treats real parenthetical speech as a gesture', () => {
    // The assertion that keeps this from becoming a comprehension bug. A question missing its
    // qualifier is a different question.
    const parts = splitGestures('The JDK (which includes the compiler) is what you need.');
    expect(parts).toHaveLength(1);
    expect(parts[0].kind).toBe('said');
  });

  it('does not leak regex state between calls', () => {
    // A module-level /g regex carries lastIndex. Reused across renders, the second line
    // would parse from the wrong offset — a bug that only ever shows on the second panelist.
    const once = splitGestures('*(laughs)* One.');
    const twice = splitGestures('*(laughs)* One.');
    expect(twice).toEqual(once);
    expect(hasGesture('*(smiles)* Sure.')).toBe(true);
    expect(hasGesture('*(smiles)* Sure.')).toBe(true);
    expect(hasGesture('Nothing here.')).toBe(false);
  });
});

describe('the eye and the ear agree about what a gesture is', () => {
  /*
   * THE ONE THAT MATTERS. Two consumers, two code paths, one definition. If `speakable.ts`
   * strips something this parser does not recognise, the screen shows raw markup; if this
   * recognises something speakable does not strip, a voice reads it out loud. The original
   * bug was exactly that asymmetry — the prompt defined a format and neither consumer knew.
   */
  const LINES = [
    '*(laughs)* No, fair enough.',
    '*(both laugh)* Okay, next one.',
    '(chuckles) Fair.',
    '(smiles) Go on.',
    'Ha — okay. *(laughs)* That is one way to put it.',
  ];

  for (const line of LINES) {
    it(`spoken form contains no gesture word: ${line}`, () => {
      const spoken = toSpokenForm(line);
      for (const part of splitGestures(line)) {
        if (part.kind === 'gesture') {
          expect(spoken.toLowerCase()).not.toContain(part.text.toLowerCase());
        }
      }
      // And nothing that was SAID may be lost from the spoken form.
      for (const part of splitGestures(line)) {
        if (part.kind === 'said') {
          const head = part.text.split(' ')[0].replace(/[^\w]/g, '');
          if (head) expect(spoken).toContain(head);
        }
      }
    });
  }

  it('a real parenthetical survives in both', () => {
    const line = 'The JDK (which includes the compiler) is what you need.';
    expect(toSpokenForm(line)).toContain('which includes the compiler');
    expect(splitGestures(line).every((p) => p.kind === 'said')).toBe(true);
  });
});
