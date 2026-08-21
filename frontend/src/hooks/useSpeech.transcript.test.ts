import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * No word the engine heard is thrown away — hooks/useSpeech.transcript.test.ts
 *
 * REPORTED: "the mic is also not accepting the correct answers the words are not perfectly
 * been registered i want that aslo fixed professionally as i do not want a single word to be
 * taking wrong".
 *
 * NOTHING WAS MISHEARING ANYTHING. `transcript` only ever grew from results the Web Speech
 * engine marked `isFinal`, and both of the ways a recognition session can end discarded
 * whatever was still interim at that moment:
 *
 *   1. CHROME ENDS SESSIONS BY ITSELF, `continuous = true` notwithstanding. `onend` restarts
 *      the engine — that part was already fixed, and its comment explains it — but the
 *      restart begins a fresh results list that knows nothing about the phrase in flight. So
 *      mid-answer, unpredictably, a clause went missing.
 *   2. `stop()`, which is what runs when the candidate finishes and submits. The last thing
 *      somebody says is the most likely thing to still be interim, so the END of almost every
 *      answer was at risk. That is the one a candidate notices, and it is what "it did not
 *      register what I said" means.
 *
 * The words were recognised. They were reported. They were then dropped on the floor by the
 * two lines that ended the session, and the answer went to the scorer short.
 *
 * WHY SOURCE ASSERTIONS. `useSpeechRecognition` needs `window.SpeechRecognition`, a real
 * audio pipeline and a mounted React tree; the vitest environment here is `node` (see
 * frontend/vitest.config.ts) and none of those exist. The same reasoning as
 * components/account-isolation.test.ts: this cannot prove the browser behaviour, and it can
 * prove that the specific lines which fix it are still there — which is the regression that
 * matters, somebody removing them in a refactor while every other test still passes.
 */

const SRC = readFileSync(join(process.cwd(), 'src/hooks/useSpeech.ts'), 'utf8');

/** Comments stripped, so no assertion can be satisfied by its own explanation. */
const CODE = SRC.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');

describe('the uncommitted tail is rescued, not discarded', () => {
  it('keeps the in-flight phrase in a ref, not only in render state', () => {
    // A ref, because both rescue points run inside callbacks that would otherwise close over
    // a stale render's `interim` value.
    expect(CODE).toMatch(/const interimRef = useRef<string>\(''\)/);
    expect(CODE).toMatch(/interimRef\.current = interimChunk/);
  });

  it('assigns the tail rather than appending it', () => {
    // `interimChunk` is recomputed from `e.resultIndex` on every event and is already the
    // whole uncommitted tail. Appending would duplicate every word as the phrase grows,
    // which would be a worse bug than the one being fixed — wrong words rather than missing
    // ones.
    expect(CODE).not.toMatch(/interimRef\.current \+= /);
  });

  it('commits the tail when Chrome ends the session on its own', () => {
    // The restart was already here. What was missing is rescuing the phrase first: after
    // onend that phrase will never be finalised by anything.
    const onend = CODE.slice(CODE.indexOf('rec.onend'), CODE.indexOf('recognitionRef.current = rec'));
    expect(onend).toContain('commitInterim()');
    expect(onend).toContain('rec.start()');
    // Order matters and is the whole point: rescue, then restart.
    expect(onend.indexOf('commitInterim()')).toBeLessThan(onend.indexOf('rec.start()'));
  });

  it('commits the tail when the candidate stops and submits', () => {
    const stop = CODE.slice(CODE.indexOf('const stop = useCallback'), CODE.indexOf('const reset = useCallback'));
    expect(stop).toContain('commitInterim()');
    // Before stop(), or the engine tears down and takes the phrase with it.
    expect(stop.indexOf('commitInterim()')).toBeLessThan(stop.indexOf('recognitionRef.current?.stop()'));
  });

  it('is idempotent, so a stop followed by the engine own onend cannot double-add', () => {
    // Both can fire in quick succession. Clearing the ref as the FIRST act means the second
    // call finds nothing — a phrase appearing twice in an answer would read as the candidate
    // repeating themselves and be scored as padding.
    const body = CODE.slice(CODE.indexOf('const commitInterim'), CODE.indexOf('useEffect(()'));
    expect(body.indexOf("interimRef.current = ''")).toBeLessThan(body.indexOf('if (!pending) return'));
  });

  it('a rescued phrase gets the same treatment as a finalised one', () => {
    // Otherwise "HashMap" would come out as "hash map" only when the session happened to end
    // mid-sentence, and the stored answer would be inconsistent with itself.
    const body = CODE.slice(CODE.indexOf('const commitInterim'), CODE.indexOf('useEffect(()'));
    expect(body).toContain('correctTechnicalTerms(pending)');
    expect(body).toContain('wordCountRef.current +=');
    expect(body).toMatch(/setTranscript\(\(prev\) => \(prev \? prev \+ ' ' : ''\) \+ clean\)/);
  });

  it('starting a new question clears any rescued tail', () => {
    // Or the end of the previous answer would be prepended to the next one and attributed to
    // a question it was never about.
    const reset = CODE.slice(CODE.indexOf('const reset = useCallback'), CODE.indexOf('return {'));
    expect(reset).toContain("interimRef.current = ''");
  });
});

describe('the recogniser is still configured for these candidates', () => {
  it('asks for Indian English', () => {
    // Not en-US. The recogniser transcribes Indian-accented English markedly better with
    // this hint, and accuracy is the complaint this file exists for.
    expect(CODE).toMatch(/rec\.lang = 'en-IN'/);
  });

  it('stays continuous and reports interim results', () => {
    // interimResults is what makes the rescue possible at all — without it there is no tail
    // to keep, and every pause would lose everything up to it.
    expect(CODE).toMatch(/rec\.continuous = true/);
    expect(CODE).toMatch(/rec\.interimResults = true/);
  });

  it('does not treat a thinking pause as a fatal error', () => {
    // Chrome raises `no-speech` whenever somebody pauses to think. Treating it as fatal is
    // what originally made the mic die mid-answer.
    expect(CODE).toMatch(/not-allowed|service-not-allowed/);
    expect(CODE).not.toMatch(/kind === 'no-speech'[\s\S]{0,120}setListening\(false\)/);
  });
});
