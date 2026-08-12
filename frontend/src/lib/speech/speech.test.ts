import { describe, expect, it } from 'vitest';

import {
  countFillers,
  countUnprofessional,
  summarizeDelivery,
  tokenizeWithFillers,
} from './delivery';
import { correctTechnicalTerms, polishTranscript, tidyTranscript } from './vocabulary';

/**
 * The reported symptom was "the software gets confused what I am saying" and
 * "in the answers it only marks like and basically and nothing else".
 *
 * Both are real, and neither is a bug in the matching logic:
 *   - technical terms arrive mangled because the Web Speech API has no domain
 *     vocabulary, so they need correcting after the fact
 *   - "uh"/"um" are stripped by Chrome before we see the text, so no list can
 *     catch them; what IS catchable is the word-shaped fillers, and there were
 *     only a handful of those
 */

describe('technical vocabulary correction', () => {
  it('fixes the terms the recogniser splits into two words', () => {
    expect(correctTechnicalTerms('i would use a hash map here')).toBe(
      'i would use a HashMap here',
    );
    expect(correctTechnicalTerms('use a string builder in a loop')).toBe(
      'use a StringBuilder in a loop',
    );
    expect(correctTechnicalTerms('an array list is backed by an array')).toBe(
      'an ArrayList is backed by an array',
    );
  });

  it('fixes acronyms the recogniser spells out letter by letter', () => {
    expect(correctTechnicalTerms('the j v m runs bytecode')).toBe('the JVM runs bytecode');
    expect(correctTechnicalTerms('connect using j d b c')).toBe('connect using JDBC');
    expect(correctTechnicalTerms('it returns j s o n')).toBe('it returns JSON');
  });

  it('handles the longest match first', () => {
    // "null pointer exception" must not become "null pointer" + "exception".
    expect(correctTechnicalTerms('it throws a null pointer exception')).toBe(
      'it throws a NullPointerException',
    );
  });

  it('rejoins words the recogniser separates', () => {
    expect(correctTechnicalTerms('poly morphism and over riding')).toBe(
      'polymorphism and overriding',
    );
    expect(correctTechnicalTerms('multi threading is hard')).toBe('multithreading is hard');
  });

  it('is case-insensitive and word-boundary anchored', () => {
    expect(correctTechnicalTerms('Hash Map')).toBe('HashMap');
    // "api" inside another word must not be touched.
    expect(correctTechnicalTerms('rapid development')).toBe('rapid development');
    // Nor should a substring of a longer word.
    expect(correctTechnicalTerms('likeable')).toBe('likeable');
  });

  it('is idempotent', () => {
    // The hook corrects each finalised chunk, and the caller may correct the whole
    // transcript again before submitting. Running twice must change nothing.
    const once = correctTechnicalTerms('the hash map and the j v m');
    expect(correctTechnicalTerms(once)).toBe(once);
  });

  it('leaves ordinary language alone', () => {
    const plain = 'I built a small tool for my college project last year';
    expect(correctTechnicalTerms(plain)).toBe(plain);
  });

  it('does not invent a correction for genuinely garbled speech', () => {
    // "annual function" is the artifact that caused a real bug. Nobody can know
    // what was actually said, so correcting it would put words in the
    // candidate's mouth.
    expect(correctTechnicalTerms('you mentioned annual function')).toBe(
      'you mentioned annual function',
    );
  });
});

describe('transcript tidying', () => {
  it('collapses whitespace and fixes spacing before punctuation', () => {
    expect(tidyTranscript('the  jvm   runs it , yes')).toBe('The jvm runs it, yes');
  });

  it('capitalises sentence starts', () => {
    expect(tidyTranscript('one thing. another thing')).toBe('One thing. Another thing');
  });

  it('does not invent punctuation', () => {
    // Guessing where a sentence ended would change what someone said.
    const runOn = 'the jvm runs bytecode it is platform independent';
    expect(tidyTranscript(runOn)).toBe('The jvm runs bytecode it is platform independent');
  });

  it('preserves the capitals corrections introduce', () => {
    expect(polishTranscript('the hash map stores the j v m config')).toBe(
      'The HashMap stores the JVM config',
    );
  });
});

describe('filler detection', () => {
  it('catches the word-shaped fillers a browser actually transcribes', () => {
    const { total, breakdown } = countFillers(
      'so basically I think the answer is like you know kind of simple',
    );
    expect(total).toBeGreaterThanOrEqual(4);
    expect(breakdown.basically).toBe(1);
    expect(breakdown.like).toBe(1);
  });

  it('counts multi-word hedges once per word so highlighting lines up', () => {
    const tokens = tokenizeWithFillers('it is you know fine');
    const flagged = tokens.filter((t) => t.isFiller).map((t) => t.text);
    expect(flagged).toEqual(['you', 'know']);
  });

  it('catches the hedges that make an answer sound uncertain', () => {
    const { total } = countFillers('maybe probably something like that I guess');
    expect(total).toBeGreaterThanOrEqual(3);
  });

  it('does not flag a substring of an ordinary word', () => {
    expect(countFillers('I liked the likeable actuator').total).toBe(0);
  });

  it('reports zero on a clean answer', () => {
    expect(
      countFillers('The JVM executes bytecode, which is what makes Java portable.').total,
    ).toBe(0);
  });
});

describe('unprofessional language', () => {
  it('flags profanity, which was not detected at all before', () => {
    const { total, words } = countUnprofessional('what the fuck is this supposed to do');
    expect(total).toBe(1);
    expect(words).toContain('fuck');
  });

  it('flags the censored spellings Chrome returns', () => {
    // Chrome masks profanity by default, so the obvious check for the plain word
    // misses exactly the case this exists to catch.
    expect(countUnprofessional('this is f*** ridiculous').total).toBe(1);
    expect(countUnprofessional('total s*** design').total).toBe(1);
  });

  it('is counted separately from fillers, not lumped in with them', () => {
    // Different mistakes, different advice: a filler is a habit, this is one
    // event that costs the offer.
    const text = 'basically this is fuck all use';
    expect(countFillers(text).total).toBe(1);
    expect(countUnprofessional(text).total).toBe(1);
  });

  it('never double-counts a word as both', () => {
    const tokens = tokenizeWithFillers('fuck');
    expect(tokens[0].isUnprofessional).toBe(true);
    expect(tokens[0].isFiller).toBe(false);
  });

  it('does NOT flag FK, which is how candidates say foreign key', () => {
    // This was a real false positive: "fk" was in the list, matching is
    // case-insensitive, and a correct answer about referential integrity earned a
    // conduct flag on the report plus a capped communication score. A word that is
    // a technical abbreviation in this question bank cannot carry an irreversible
    // penalty.
    expect(countUnprofessional('the FK on that table enforces referential integrity').total).toBe(0);
    expect(countUnprofessional('add an FK constraint').total).toBe(0);
  });

  it('keeps casual language out of the report-grade count', () => {
    // "Damn" muttered while tracing a nested loop is not the sentence that loses an
    // offer. Treating it as one destroys the credibility of the flag that is.
    expect(countUnprofessional('damn, that loop is O(n squared)').total).toBe(0);
    expect(countUnprofessional('this is a crap design').total).toBe(0);
  });

  it('still marks casual language in the transcript, just not in the report', () => {
    const tokens = tokenizeWithFillers('damn');
    expect(tokens[0].isCasual).toBe(true);
    expect(tokens[0].isUnprofessional).toBe(false);
    expect(tokens[0].isFiller).toBe(false);
  });

  it('assigns each word exactly one severity', () => {
    // The renderer branches in order, so a word that claimed two severities would
    // silently show the more serious one and the counts would disagree with the
    // colours.
    for (const tok of tokenizeWithFillers('basically damn fuck honestly')) {
      if (tok.wordIndex < 0) continue;
      const flags = [tok.isUnprofessional, tok.isCasual, tok.isFiller].filter(Boolean);
      expect(flags.length).toBeLessThanOrEqual(1);
    }
  });

  it('leaves a clean answer alone', () => {
    expect(countUnprofessional('I would use a HashMap for O(1) lookup.').total).toBe(0);
  });

  it('does not flag words that are only profanity in one sense', () => {
    // "what the hell does this do" is a candidate thinking aloud about code.
    expect(countUnprofessional('what the hell does this method do').total).toBe(0);
  });
});

describe('delivery summary', () => {
  it('surfaces unprofessional language alongside the delivery metrics', () => {
    const s = summarizeDelivery({
      text: 'basically the answer is like, fuck, I do not remember',
      seconds: 12,
      pauses: [{ wordIndex: 4, seconds: 3 }],
    });
    expect(s.fillerCount).toBeGreaterThanOrEqual(2);
    expect(s.unprofessionalCount).toBe(1);
    expect(s.unprofessionalWords).toContain('fuck');
    expect(s.pauseCount).toBe(1);
    expect(s.wpm).toBeGreaterThan(0);
  });

  it('reports zero rather than throwing on an empty answer', () => {
    const s = summarizeDelivery({ text: '', seconds: 0, pauses: [] });
    expect(s.words).toBe(0);
    expect(s.wpm).toBe(0);
    expect(s.unprofessionalCount).toBe(0);
  });
});

/**
 * MISHEARINGS — the recogniser substituting ordinary English for a technical word.
 *
 * Reported from a real session and visible in the transcript: "you keep the FEELS private
 * and only allow access through public CATCHERS". Both are real words, which is what makes
 * this class of error different from the split-word corrections above and much more
 * dangerous to fix: a blind rule rewrites somebody's actual sentence.
 *
 * So the over-correction tests below matter more than the correction ones. A missed
 * mishearing leaves a transcript slightly wrong; a wrong correction makes it confidently
 * wrong, and it then gets scored, quoted back in a follow-up, and printed in a report.
 */
describe('misheard technical words', () => {
  it('fixes the exact transcript that was reported', () => {
    expect(
      correctTechnicalTerms(
        'you keep the feels private and only allow access through public catchers',
      ),
    ).toBe('you keep the fields private and only allow access through public getters');
  });

  it.each([
    ['instance feels are private', 'instance fields are private'],
    ['getters and settlers', 'getters and setters'],
    ['gutters and setters', 'getters and setters'],
    ['public avoid main', 'public void main'],
    ['it throws a no pointer', 'it throws a null pointer'],
    ['threat safe collections', 'thread safe collections'],
    ['multi threat environment', 'multithread environment'],
    ['memory cash', 'memory cache'],
    ['bite code runs on the JVM', 'bytecode runs on the JVM'],
    ['rapper class for int', 'wrapper class for int'],
    ['car array', 'char array'],
    ['priority cue', 'priority queue'],
    ['string arcs', 'string args'],
    ['abstract clause', 'abstract class'],
    ['a bullion value', 'a boolean value'],
    ['inter face', 'interface'],
    ['in heritance', 'inheritance'],
    ['construct or', 'constructor'],
    ['im mutable', 'immutable'],
  ])('corrects %j', (heard, meant) => {
    expect(correctTechnicalTerms(heard).toLowerCase()).toContain(meant.toLowerCase());
  });

  describe('does NOT corrupt ordinary English', () => {
    it.each([
      // Every one of these is a sentence a candidate could plausibly say, containing a word
      // that appears in the misheard list without its technical anchor.
      'it feels wrong to me',
      'that feels like the right approach',
      'I want to avoid that problem',
      'we should avoid duplicate code',
      'there is no reason to do that',
      'no problem sir',
      'that is a security threat',
      'I paid cash for the course',
      'take a bite out of the problem',
      'he is a rapper',
      'I drove the car to college',
      'take my cue from the requirements',
      'the arcs of the diagram',
      'the where clause filters rows',
      'if clause and else clause',
      'in stance we take a position',
    ])('leaves %j alone', (sentence) => {
      expect(correctTechnicalTerms(sentence)).toBe(sentence);
    });
  });

  it('is still idempotent with the mishearing pass in front', () => {
    // The hook corrects each finalised chunk as it arrives, and the caller may correct the
    // whole transcript again before submitting. A rule that fires twice would compound.
    const once = correctTechnicalTerms('keep the feels private, use public catchers');
    expect(correctTechnicalTerms(once)).toBe(once);
  });

  it('runs mishearings before term corrections, so both can apply', () => {
    // "bite code" must become "byte code" before the split-word rule folds it to "bytecode".
    expect(correctTechnicalTerms('bite code')).toBe('bytecode');
  });
});
