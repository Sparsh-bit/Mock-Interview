import { describe, expect, it } from 'vitest';
import { scoreVoice, toSpeechChunks } from './useSpeech';

const v = (name: string, lang: string) =>
  ({ name, lang, voiceURI: name, default: false, localService: true } as SpeechSynthesisVoice);

describe('scoreVoice', () => {
  // The regression this ordering fixes: ranking accent above quality picked
  // Apple's local Rishi over Microsoft's neural Neerja, which is what made the
  // interviewer sound like a TTS engine.
  it('prefers a neural Indian voice over a local Indian voice', () => {
    const neural = v('Microsoft Neerja Online (Natural) - English (India)', 'en-IN');
    const local = v('Rishi', 'en-IN');
    expect(scoreVoice(neural)).toBeGreaterThan(scoreVoice(local));
  });

  it('prefers a neural non-Indian voice over local synthesis', () => {
    expect(scoreVoice(v('Microsoft Aria Online (Natural) - English (US)', 'en-US')))
      .toBeGreaterThan(scoreVoice(v('Rishi', 'en-IN')));
  });

  // ACCENT ORDER, reversed on purpose — see the long note in voice-ranking.ts.
  //
  // en-IN used to win by 50 points, which is what made it able to drag a bad voice above a
  // good one. It is now a nudge, applied inside a tier, and neutral English leads.
  it('prefers neutral US English to en-IN within the same quality tier', () => {
    const inIN = v('Microsoft Prabhat Online (Natural) - English (India)', 'en-IN');
    const inUS = v('Microsoft Aria Online (Natural) - English (US)', 'en-US');
    expect(scoreVoice(inUS)).toBeGreaterThan(scoreVoice(inIN));
  });

  // British last of the three. Not a quality judgement — a British interviewer is simply
  // the wrong character for an Indian campus panel, and it reads as more incongruous than
  // a neutral American one does.
  it('ranks en-GB below both en-US and en-IN within a tier', () => {
    const gb = v('Microsoft Libby Online (Natural) - English (GB)', 'en-GB');
    const us = v('Microsoft Aria Online (Natural) - English (US)', 'en-US');
    const inIN = v('Microsoft Prabhat Online (Natural) - English (India)', 'en-IN');
    expect(scoreVoice(us)).toBeGreaterThan(scoreVoice(gb));
    expect(scoreVoice(inIN)).toBeGreaterThan(scoreVoice(gb));
  });

  // The point of the reversal is that accent can no longer outrank quality. This is the
  // test that would catch someone restoring the old +50 while keeping US ahead nominally.
  it('never lets accent outrank the quality tier', () => {
    const neuralUS = v('Microsoft Aria Online (Natural) - English (US)', 'en-US');
    const neuralGB = v('Microsoft Libby Online (Natural) - English (GB)', 'en-GB');
    const localIN = v('Rishi', 'en-IN');
    // Even the LAST-ranked accent, when neural, beats the FIRST-ranked accent when it is a
    // decade-old formant synth.
    expect(scoreVoice(neuralGB)).toBeGreaterThan(scoreVoice(localIN));
    expect(scoreVoice(neuralUS)).toBeGreaterThan(scoreVoice(localIN));
  });

  it('rejects novelty, compact and non-English voices outright', () => {
    for (const bad of [v('Zarvox', 'en-US'), v('Fred', 'en-US'), v('Rishi (Compact)', 'en-IN')]) {
      expect(scoreVoice(bad)).toBe(-1);
    }
    expect(scoreVoice(v('Google Deutsch', 'de-DE'))).toBe(-1);
  });

  it('ranks a realistic macOS/Edge list with a neural neutral voice first', () => {
    const list = [
      v('Fred', 'en-US'),
      v('Rishi', 'en-IN'),
      v('Samantha', 'en-US'),
      v('Microsoft Aria Online (Natural) - English (US)', 'en-US'),
      v('Microsoft Neerja Online (Natural) - English (India)', 'en-IN'),
    ];
    const best = [...list].sort((a, b) => scoreVoice(b) - scoreVoice(a))[0];
    expect(best.name).toContain('Aria');
    // Whatever wins, it is never one of the local synths — that was the original bug and it
    // stays fixed independently of which accent is on top.
    expect(['Fred', 'Rishi', 'Samantha']).not.toContain(best.name);
  });
});

describe('toSpeechChunks', () => {
  it('splits on sentence boundaries so each sentence gets a natural breath', () => {
    expect(toSpeechChunks(
      'Tell me about yourself. What was your final year project about? Explain the design.'
    )).toEqual([
      'Tell me about yourself.',
      'What was your final year project about?',
      'Explain the design.',
    ]);
  });

  it('merges short fragments instead of speaking them alone', () => {
    // "Right." alone would be a clipped, choppy utterance.
    const chunks = toSpeechChunks('Right. Now explain how you would scale that to a large team.');
    expect(chunks).toHaveLength(1);
  });

  it('collapses whitespace and never returns empty output', () => {
    expect(toSpeechChunks('  Hello   there.\n\n  How are you doing today?  ')).toEqual([
      'Hello there.',
      'How are you doing today?',
    ]);
    expect(toSpeechChunks('')).toEqual(['']);
  });
});
