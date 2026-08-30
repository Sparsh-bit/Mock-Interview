import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * ASKING FOR A REPEAT MUST NOT COST A QUESTION.
 *
 * "Sorry, could you repeat that?" used to be submitted as the candidate's ANSWER: an Answer
 * row on that topic, one of the twelve questions the dashboard promised spent, that sentence
 * read out to the report generator as their attempt, and the panel's next turn correcting a
 * wrong answer they had never given.
 *
 * The server now recognises it (backend/app/services/interview/off_script.py), records what
 * they said, writes no answer, and reports `question_still_open`. This file pins the browser's
 * half, which is entirely about what it must NOT do:
 *
 *   · it must not refetch — `question` is unchanged, and a refetch would also re-run the
 *     cross-question injector against an answer that does not exist
 *   · it must hand the panel the SAME question, not the next one, because handing over a new
 *     question here is precisely what makes a clarification cost somebody a question
 *   · it must return before the decline and coding branches, which are about answers
 *
 * WHY THESE ARE SOURCE ASSERTIONS. The same reason mic-interlock.test.ts and one-voice.test.ts
 * give at length: this page owns a MediaStream, an AudioContext, MediaPipe and
 * speechSynthesis, none of which exist in jsdom. What that leaves catchable is the regression
 * that actually happens — somebody deleting a guard in a refactor and seeing every test pass.
 */

const PAGE = readFileSync(
  join(process.cwd(), 'src/app/(interview)/session/[id]/page.tsx'),
  'utf8',
);

/** Source with comments removed, so an assertion cannot match its own explanation. */
const CODE = PAGE.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');

/** The body of the submit mutation's onSuccess handler, where all the branching lives. */
const ON_SUCCESS = CODE.slice(CODE.indexOf('onSuccess: (res) =>'));

describe('a question the candidate asked back does not consume their question', () => {
  it('branches on question_still_open', () => {
    expect(ON_SUCCESS).toContain('res.question_still_open');
  });

  it('reads question_still_open rather than off_script', () => {
    // Past the server's clarification cap the KIND is still reported — so the panel can say
    // something honest — while the interview does move on. Branching on `off_script` would
    // hold the candidate on the same question forever, which is the loop the cap exists to
    // break.
    const branch = ON_SUCCESS.slice(0, ON_SUCCESS.indexOf('res.declined'));
    expect(branch).toContain('res.question_still_open');
    expect(branch).not.toContain('if (res.off_script)');
  });

  it('runs the off_script panel stage', () => {
    expect(ON_SUCCESS).toContain("stage: 'off_script'");
  });

  it('hands the panel the SAME question, never the next one', () => {
    // The whole bug in one line. `questionText` is the question they were just given and have
    // not answered; anything fetched fresh here would be the next one.
    const stage = ON_SUCCESS.slice(ON_SUCCESS.indexOf("stage: 'off_script'"));
    const call = stage.slice(0, stage.indexOf('});'));
    expect(call).toContain('question: questionText');
    expect(call).toContain('candidate_question: content');
  });

  it('does not refetch, so the interview does not advance', () => {
    const start = ON_SUCCESS.indexOf('res.question_still_open');
    const branch = ON_SUCCESS.slice(start, ON_SUCCESS.indexOf('res.declined'));
    expect(branch).not.toContain('refetch()');
  });

  it('returns before the decline and coding branches', () => {
    // Those two are about ANSWERS. Falling through to them after a clarification would offer
    // a pivot, or a code review, for a question that has not been answered.
    const branch = ON_SUCCESS.slice(
      ON_SUCCESS.indexOf('res.question_still_open'),
      ON_SUCCESS.indexOf('res.declined'),
    );
    expect(branch).toContain('return;');
  });

  it('is wrapped so a failed turn cannot strand the candidate', () => {
    // `panelForRef` is already claimed for this question, so if speakTurn throws here nothing
    // will ever speak again and the only way out is End Interview. The catch puts the question
    // back on screen itself: they lose the clarification, not the interview. Same guarantee
    // the pivot branch below it carries.
    const branch = ON_SUCCESS.slice(
      ON_SUCCESS.indexOf('res.question_still_open'),
      ON_SUCCESS.indexOf('res.declined'),
    );
    expect(branch).toContain('try {');
    expect(branch).toContain('} catch {');
    expect(branch).toContain('speakAs');
  });

  it('still records the answer normally when nothing is off script', () => {
    // The counterweight. A page that took this branch every time would never record anything.
    expect(ON_SUCCESS).toContain('res.declined');
    expect(ON_SUCCESS).toContain('setAnswered(res.questions_answered)');
  });
});
