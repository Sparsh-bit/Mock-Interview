import { describe, it, expect } from 'vitest';
import { FOCUS_SUGGESTIONS, addFocusTerm, focusMentions } from './focus';

/**
 * The focus chips, pinned.
 *
 * The behaviour worth protecting is small and entirely about not mangling text the candidate
 * wrote: a chip must never duplicate itself, and appending must never leave the doubled commas
 * or dangling separators that make a form look broken in the user's own sentence.
 *
 * The other assertion here is the term list itself. Each of these six was checked against the
 * backend's `syllabus.match_focus` for the Cognizant Digital Nurture — Java FSE syllabus and
 * resolves to a distinct area. Renaming one silently turns a chip that steers the interview
 * into a chip that just adds a word, which is the exact failure this whole surface exists to
 * fix — so the strings are pinned, with the reason next to them.
 */

describe('FOCUS_SUGGESTIONS', () => {
  it('is exactly the terms verified to resolve to a syllabus area', () => {
    expect([...FOCUS_SUGGESTIONS]).toEqual([
      'Core Java', // -> Core Java
      'OOP', // -> OOP & Class Design
      'React', // -> React & Frontend
      'SQL', // -> SQL & Data Modelling
      'Spring Boot', // -> Spring Boot & REST
      'Coding', // -> Coding Fundamentals
    ]);
  });

  it('says "Spring Boot" rather than "REST"', () => {
    // match_focus tries sub-topic containment before area names, and the React area owns
    // "consuming a REST endpoint from a component" — so bare "REST" resolves to the FRONTEND
    // area, not to Spring. Correct in the matcher, a trap in a chip.
    expect(FOCUS_SUGGESTIONS).not.toContain('REST');
    expect(FOCUS_SUGGESTIONS).toContain('Spring Boot');
  });

  it('offers no Project or HR chip', () => {
    // They are stages every technical interview reaches, not weighted areas — a chip would
    // promise a steer with nothing to steer. The copy under the box says they are covered.
    expect(FOCUS_SUGGESTIONS.some((t) => /project|hr/i.test(t))).toBe(false);
  });
});

describe('focusMentions', () => {
  it('is case-insensitive', () => {
    expect(focusMentions('i want sql joins', 'SQL')).toBe(true);
    expect(focusMentions('SPRING BOOT please', 'Spring Boot')).toBe(true);
  });

  it('recognises a term embedded in the candidate’s own sentence', () => {
    expect(focusMentions('spring boot and rest endpoints', 'Spring Boot')).toBe(true);
  });

  it('is false when the term is absent', () => {
    expect(focusMentions('', 'React')).toBe(false);
    expect(focusMentions('mostly SQL', 'React')).toBe(false);
  });
});

describe('addFocusTerm', () => {
  it('is the term itself when the box is empty', () => {
    expect(addFocusTerm('', 'OOP')).toBe('OOP');
    expect(addFocusTerm('   ', 'OOP')).toBe('OOP');
  });

  it('appends comma-separated so the result still reads as a request', () => {
    expect(addFocusTerm('OOP', 'SQL')).toBe('OOP, SQL');
  });

  it('never duplicates a term, however many times the chip is tapped', () => {
    const once = addFocusTerm('', 'React');
    expect(addFocusTerm(once, 'React')).toBe(once);
    expect(addFocusTerm(addFocusTerm(once, 'React'), 'React')).toBe(once);
  });

  it('does not duplicate a term the candidate had already typed themselves', () => {
    expect(addFocusTerm('please push on sql joins', 'SQL')).toBe('please push on sql joins');
  });

  it('does not leave a doubled separator when the candidate was mid-sentence', () => {
    // "I want SQL, " + a chip must not become "I want SQL, , React".
    expect(addFocusTerm('I want SQL, ', 'React')).toBe('I want SQL, React');
    expect(addFocusTerm('OOP;', 'React')).toBe('OOP, React');
    expect(addFocusTerm('OOP \n', 'React')).toBe('OOP, React');
  });

  it('leaves prose intact rather than reformatting it', () => {
    const written = 'I am weakest on multithreading and I freeze on cross-questions.';
    expect(addFocusTerm(written, 'OOP')).toBe(`${written}, OOP`);
  });
});
