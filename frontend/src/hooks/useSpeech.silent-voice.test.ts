/**
 * A panelist must never be silent — useSpeech.silent-voice.test.ts
 *
 * REPORTED, twice: "the priya is not speaking", then "only the anil is speaking the priya is
 * not their in the interview". Two independent faults produced it, and either one alone is
 * enough to take one person out of a two-person panel.
 *
 *   AN ERROR LOOKED LIKE SUCCESS. `speakOnce` had `utter.onerror = finish` and returned
 *   `Promise<void>`, so a refused utterance was reported to the caller exactly as a spoken
 *   one: the line was revealed into the transcript, the chain moved on, and that panelist
 *   made no sound. Nothing logged it. And speechSynthesis refuses PER VOICE, not per page —
 *   a cloud-backed voice (`localService: false`) that the engine cannot reach raises
 *   `synthesis-failed` and produces silence — so whichever panelist was allocated a local
 *   voice kept working and the room sounded like one person.
 *
 *   ONE FAILED LINE ABORTED THE WHOLE TURN. The session page awaited each line bare inside a
 *   `for` loop, so a rejection broke out of it and every later line was neither spoken nor
 *   shown. Anil leads almost every turn, so a fault on his line deleted Priya's from the
 *   interview — which is literally "Priya is not there".
 *
 * These are source-level assertions rather than a DOM harness on purpose: the failure lives in
 * whether an error is DISTINGUISHED from success and whether a loop is isolated, and both are
 * visible in the source in a way a jsdom speechSynthesis stub (which does not implement voice
 * failure at all) cannot reproduce.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

const SRC = join(__dirname, '..');
const SPEECH = readFileSync(join(SRC, 'hooks/useSpeech.ts'), 'utf8');
const SESSION = readFileSync(join(SRC, 'app/(interview)/session/[id]/page.tsx'), 'utf8');

/** Source with comments stripped — prose about a rule is not the rule. */
function code(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, '');
}

const SPEECH_CODE = code(SPEECH);
const SESSION_CODE = code(SESSION);

describe('an utterance reports whether it actually made a sound', () => {
  it('speakOnce resolves a boolean, not void', () => {
    // The whole fix hangs on the caller being ABLE to tell. While this was Promise<void>
    // there was no way to express "that voice produced nothing" at all.
    expect(SPEECH_CODE).toMatch(/function speakOnce\([\s\S]{0,120}\): Promise<boolean>/);
  });

  it('an error before any audio reports false', () => {
    // The precise condition. `engineStarted` is set only by the engine's own start event, so
    // this is "the voice was refused and nothing was heard".
    expect(SPEECH_CODE).toMatch(/utter\.onerror = \(\) => finish\(engineStarted\)/);
  });

  it('a normal end reports true', () => {
    expect(SPEECH_CODE).toMatch(/utter\.onend = \(\) => finish\(true\)/);
  });

  it('the watchdog reports true, so a quiet engine is never made to repeat itself', () => {
    // iOS Safari fires neither end nor error while speaking perfectly well. Reporting false
    // here would make every one of those lines be spoken twice — a worse and far more
    // noticeable fault than the one being fixed.
    expect(SPEECH_CODE).toMatch(/setTimeout\(\(\) => finish\(true\), 3000/);
  });

  it('the reveal fallback does not count as having spoken', () => {
    // `startFallback` exists to release the transcript on engines that skip onstart. If it
    // set engineStarted, an error afterwards would look like partial audio and the retry
    // would never happen — which is exactly the bug, restored through the back door.
    const at = SPEECH_CODE.indexOf('const startFallback');
    const body = SPEECH_CODE.slice(at, at + 200);
    expect(body).not.toMatch(/engineStarted/);
  });

  it('only the engine start event sets engineStarted', () => {
    const assignments = SPEECH_CODE.match(/engineStarted = true/g) ?? [];
    expect(assignments).toHaveLength(1);
    expect(SPEECH_CODE).toMatch(/utter\.onstart = \(\) => \{\s*engineStarted = true;/);
  });
});

describe('a voice that produces no audio falls back to the engine default', () => {
  it('speakChunk retries on the default voice', () => {
    expect(SPEECH_CODE).toMatch(/async function speakChunk/);
    // Dropping the voice is the point: the default is local and essentially always works.
    expect(SPEECH_CODE).toMatch(/retry\.voice = null/);
  });

  it('it retries at most once, and not when it was already the default', () => {
    const at = SPEECH_CODE.indexOf('async function speakChunk');
    const body = SPEECH_CODE.slice(at, SPEECH_CODE.indexOf('\n}', at));
    // Nothing to fall back to when no voice was assigned in the first place.
    expect(body).toMatch(/if \(!hadVoice\) return;/);
    // Exactly two attempts in the body: the original and the one retry.
    expect((body.match(/speakOnce\(/g) ?? []).length).toBe(2);
  });

  it('the fallback keeps pitch and rate, which is what makes it still sound like that person', () => {
    // Two panelists frequently share one system voice, and pitch/rate are the only things
    // telling them apart. A fallback that reset them would make the panel one narrator.
    const at = SPEECH_CODE.indexOf('async function speakChunk');
    const body = SPEECH_CODE.slice(at, SPEECH_CODE.indexOf('\n}', at));
    expect(body).not.toMatch(/retry\.pitch|retry\.rate/);
  });

  it('the utterance is rebuilt rather than re-spoken', () => {
    // A SpeechSynthesisUtterance the engine has already refused cannot be handed back to
    // speak() — it silently does nothing. Without the factory the retry would be a no-op
    // that looks like a fix.
    expect(SPEECH_CODE).toMatch(/speakChunk\(\s*build: \(\) => SpeechSynthesisUtterance/);
    expect(SPEECH_CODE).toMatch(/const retry = build\(\);/);
  });

  it('it says which speaker went silent, because nothing else can', () => {
    // A silent panelist is invisible from the outside. The only previous evidence was a
    // candidate noticing, twice.
    const at = SPEECH_CODE.indexOf('async function speakChunk');
    expect(SPEECH_CODE.slice(at, at + 1200)).toMatch(/console\.warn/);
  });

  it('both speech paths use it — the panel and the single voice', () => {
    // The single-voice path is what every candidate hears when the panel layer is
    // unavailable, so a silent voice there is the entire interview, not one panelist.
    expect((SPEECH_CODE.match(/await speakChunk\(/g) ?? []).length).toBe(2);
    // And nothing calls speakOnce directly any more except speakChunk itself — a call site
    // that bypassed it would be a voice with no fallback, which is the original bug.
    const at = SPEECH_CODE.indexOf('async function speakChunk');
    const end = SPEECH_CODE.indexOf('\n}', at);
    const outside = [
      ...(SPEECH_CODE.slice(0, at).match(/await speakOnce\(/g) ?? []),
      ...(SPEECH_CODE.slice(end).match(/await speakOnce\(/g) ?? []),
    ];
    expect(outside).toHaveLength(0);
  });
});

describe('one failed line does not silence the rest of the turn', () => {
  it('each line is spoken inside its own try', () => {
    // A bare await in this loop meant a rejection skipped every later line of the turn.
    const at = SESSION_CODE.indexOf('for (const line of result.turns)');
    expect(at).toBeGreaterThan(-1);
    const loop = SESSION_CODE.slice(at, at + 900);
    expect(loop).toMatch(/try \{/);
    expect(loop).toMatch(/catch \(err\)/);
    expect(loop).toMatch(/await voicesRef\.current\.speakAs\(/);
  });

  it('a line whose audio failed is still shown', () => {
    // Losing the voice is a degraded interview. Losing the words is a broken one, and the
    // second used to follow from the first for every line after a failure.
    const at = SESSION_CODE.indexOf('for (const line of result.turns)');
    const loop = SESSION_CODE.slice(at, at + 900);
    expect(loop).toMatch(/const reveal = \(\) => \{/);
    // Called from the catch as well as passed as onStart.
    expect(loop).toMatch(/catch \(err\) \{[\s\S]{0,240}reveal\(\);/);
  });

  it('the reveal cannot double-post a line', () => {
    // onStart fires AND the catch runs, in the case where speech began and then threw. Two
    // copies of one line in the transcript is its own bug.
    const at = SESSION_CODE.indexOf('for (const line of result.turns)');
    const loop = SESSION_CODE.slice(at, at + 900);
    expect(loop).toMatch(/let shown = false;/);
    expect(loop).toMatch(/if \(shown\) return;/);
  });

  it('it names the speaker whose line failed', () => {
    const at = SESSION_CODE.indexOf('for (const line of result.turns)');
    expect(SESSION_CODE.slice(at, at + 900)).toMatch(/line\.speaker/);
  });
});
