import { describe, expect, it } from 'vitest';

import { correctTechnicalTerms } from './vocabulary';

/**
 * The transcript spells the terms the interview now asks about — vocabulary.areas.test.ts
 *
 * REPORTED TWICE: "the mic is not getting what i am saying", then "try to implement
 * autocorrect". Autocorrect already existed — around a hundred rules — and it had been written
 * for a Java-only interview. `app/data/syllabus.py` now covers React, SQL and Spring Boot/REST,
 * because that is what a Cognizant Digital Nurture candidate is actually asked, and not one term
 * from those three areas was in the table.
 *
 * THIS IS NOT COSMETIC. The transcript is what gets SCORED, and it is what the panel quotes back
 * in a follow-up. A candidate who says "useState" and has it recorded as "use state" is marked
 * against a keyword list that cannot match it, and may then be asked about a term they never
 * used. The words were heard correctly and written down wrongly.
 */
describe('React', () => {
  it('joins the hooks back together', () => {
    expect(correctTechnicalTerms('I used use state and use effect')).toContain('useState');
    expect(correctTechnicalTerms('I used use state and use effect')).toContain('useEffect');
    expect(correctTechnicalTerms('use ref holds a DOM node')).toContain('useRef');
  });

  it('capitalises the DOM', () => {
    expect(correctTechnicalTerms('the virtual dom diffs')).toContain('virtual DOM');
    expect(correctTechnicalTerms('it updates the real dom')).toContain('real DOM');
  });

  it('fixes the spelled-out initialisms', () => {
    expect(correctTechnicalTerms('we write j s x')).toContain('JSX');
  });
});

describe('SQL', () => {
  it('uppercases the clauses that are keywords', () => {
    expect(correctTechnicalTerms('then group by department')).toContain('GROUP BY');
    expect(correctTechnicalTerms('and order by salary')).toContain('ORDER BY');
  });

  it('uppercases the joins', () => {
    expect(correctTechnicalTerms('an inner join on the id')).toContain('INNER JOIN');
    expect(correctTechnicalTerms('a left outer join')).toContain('LEFT OUTER JOIN');
  });

  it('gets the ranking functions right, which the salary question always reaches for', () => {
    expect(correctTechnicalTerms('use dense rank over order by')).toContain('DENSE_RANK');
    expect(correctTechnicalTerms('row number partitioned')).toContain('ROW_NUMBER');
  });

  it('hears "no sequel" as NoSQL', () => {
    expect(correctTechnicalTerms('mongo is a no sequel database')).toContain('NoSQL');
    expect(correctTechnicalTerms('my sequel is relational')).toContain('MySQL');
  });

  it('fixes the normal forms', () => {
    expect(correctTechnicalTerms('that is three n f')).toContain('3NF');
  });
});

describe('Spring Boot and REST', () => {
  it('writes the annotations with their at-sign', () => {
    // Said without it, written with it — that is how they appear in code and how the report
    // should quote them back.
    expect(correctTechnicalTerms('I annotate with rest controller')).toContain('@RestController');
    expect(correctTechnicalTerms('a get mapping on slash students')).toContain('@GetMapping');
    expect(correctTechnicalTerms('using request body')).toContain('@RequestBody');
  });

  it('fixes the config file names', () => {
    expect(correctTechnicalTerms('set it in application properties')).toContain(
      'application.properties',
    );
    expect(correctTechnicalTerms('change the server port')).toContain('server.port');
  });

  it('joins the split words', () => {
    expect(correctTechnicalTerms('REST is state less')).toContain('stateless');
    expect(correctTechnicalTerms('PUT is idem potent')).toContain('idempotent');
  });
});

describe('OOP words the recogniser splits', () => {
  it('rejoins them', () => {
    expect(correctTechnicalTerms('in heritance and a b straction')).toContain('inheritance');
    expect(correctTechnicalTerms('in heritance and a b straction')).toContain('abstraction');
    expect(correctTechnicalTerms('an inter face')).toContain('interface');
  });

  it('handles complexity said aloud', () => {
    expect(correctTechnicalTerms('that is o of n')).toContain('O(n)');
    expect(correctTechnicalTerms('lookup is o of one')).toContain('O(1)');
    expect(correctTechnicalTerms('sorting is o of log n')).toContain('O(log n)');
  });
});

describe('the bar every rule had to clear', () => {
  /*
   * "Could this pattern fire on a sentence that had nothing wrong with it?" If yes, it is not in
   * the table. Twenty-six rules were removed for failing this after being written: nineteen were
   * NO-OPS — `rule('primary key', 'primary key')`, which changes nothing while making the term
   * look considered — and seven UPPERCASED ORDINARY ENGLISH. One of those, "where clause", was
   * caught by an existing test asserting that "the where clause filters rows" is left alone.
   * That test was right and the rule was wrong.
   */
  it('leaves ordinary English untouched', () => {
    for (const sentence of [
      'the where clause filters rows',
      'I could not find the primary key so I asked',
      'we had a dependency injection problem in the project',
      'the status code was not found in the docs',
      'I joined the team in June',
      'the state of the project was bad',
    ]) {
      expect(correctTechnicalTerms(sentence)).toBe(sentence);
    }
  });

  it('never rewrites a bare English word that is also a technical term', () => {
    // "state", "props", "join", "table", "key", "view" all appear in normal speech. A bare rule
    // for any of them would corrupt sentences that were transcribed perfectly.
    expect(correctTechnicalTerms('join the call')).toBe('join the call');
    expect(correctTechnicalTerms('the table was full')).toBe('the table was full');
  });

  it('is idempotent, so a rescued phrase cannot be double-corrected', () => {
    // commitInterim in useSpeech runs this over text that may already have been through it.
    const once = correctTechnicalTerms('use state and inner join and rest controller');
    expect(correctTechnicalTerms(once)).toBe(once);
  });
});
