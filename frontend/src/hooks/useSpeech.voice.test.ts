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

  it('prefers Indian within the same quality tier', () => {
    const inIN = v('Microsoft Prabhat Online (Natural) - English (India)', 'en-IN');
    const inUS = v('Microsoft Aria Online (Natural) - English (US)', 'en-US');
    expect(scoreVoice(inIN)).toBeGreaterThan(scoreVoice(inUS));
  });

  it('rejects novelty, compact and non-English voices outright', () => {
    for (const bad of [v('Zarvox', 'en-US'), v('Fred', 'en-US'), v('Rishi (Compact)', 'en-IN')]) {
      expect(scoreVoice(bad)).toBe(-1);
    }
    expect(scoreVoice(v('Google Deutsch', 'de-DE'))).toBe(-1);
  });

  it('ranks a realistic macOS/Edge voice list with the neural Indian voice first', () => {
    const list = [
      v('Fred', 'en-US'),
      v('Rishi', 'en-IN'),
      v('Samantha', 'en-US'),
      v('Microsoft Aria Online (Natural) - English (US)', 'en-US'),
      v('Microsoft Neerja Online (Natural) - English (India)', 'en-IN'),
    ];
    const best = [...list].sort((a, b) => scoreVoice(b) - scoreVoice(a))[0];
    expect(best.name).toContain('Neerja');
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
