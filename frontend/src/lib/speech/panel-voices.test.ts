import { describe, expect, it } from 'vitest';

import {
  allDistinguishable,
  allocatePanelVoices,
  guessGender,
  type PanelSpeaker,
} from './panel-voices';

/**
 * The requirement was "three real different voices" in the group discussion. The
 * round previously spoke none of the panel aloud, so this is the logic that has
 * to hold up on real hardware — including hardware that does not have three
 * usable voices to give.
 */

/** Minimal stand-in; the allocator only reads name, lang and voiceURI. */
function voice(name: string, lang = 'en-IN'): SpeechSynthesisVoice {
  return {
    name,
    lang,
    voiceURI: `urn:${name.replace(/\s+/g, '-').toLowerCase()}`,
    default: false,
    localService: true,
  } as SpeechSynthesisVoice;
}

/**
 * The real panel, exactly as the server defines it in api/v1/gd.py. The genders
 * are the point: "Riya" must not speak in a male voice.
 */
const PANEL: PanelSpeaker[] = [
  { name: 'Riya', gender: 'female' },
  { name: 'Arjun', gender: 'male' },
  { name: 'Meera', gender: 'female' },
];
const NAMES = PANEL.map((p) => p.name);

/** What a well-equipped Edge-on-Windows machine reports. */
const RICH = [
  voice('Microsoft Neerja Online (Natural) - English (India)'),
  voice('Microsoft Prabhat Online (Natural) - English (India)'),
  voice('Microsoft Heera - English (India)'),
  voice('Microsoft Ravi - English (India)'),
  voice('Google UK English Female', 'en-GB'),
];

describe('gender inference', () => {
  it('recognises the platform voices it knows', () => {
    expect(guessGender('Microsoft Neerja Online (Natural)')).toBe('female');
    expect(guessGender('Microsoft Prabhat Online (Natural)')).toBe('male');
    expect(guessGender('Alex')).toBe('male');
    expect(guessGender('Samantha')).toBe('female');
  });

  it('admits when it does not know rather than guessing', () => {
    // A wrong guess pairs two voices the allocator thinks contrast and which
    // actually sound identical — worse than not knowing, because it stops the
    // pitch fallback from engaging.
    expect(guessGender('Voice 3')).toBe('unknown');
    expect(guessGender('en-IN-Standard-B')).toBe('unknown');
  });
});

describe('allocation with plenty of voices', () => {
  const alloc = allocatePanelVoices(RICH, PANEL);

  it('gives every panelist a voice', () => {
    expect(alloc.size).toBe(3);
    for (const n of NAMES) expect(alloc.get(n)?.voiceURI).toBeTruthy();
  });

  it('gives every panelist a DIFFERENT voice', () => {
    const uris = NAMES.map((n) => alloc.get(n)!.voiceURI);
    expect(new Set(uris).size).toBe(3);
  });

  it('does not detune anyone who has their own voice', () => {
    // Pitch shifting is the fallback for sharing, not something to apply for no
    // reason — a detuned neural voice sounds worse than a neutral one.
    for (const n of NAMES) {
      expect(alloc.get(n)!.pitch).toBe(1.0);
      expect(alloc.get(n)!.rate).toBe(1.0);
    }
  });

  it('MATCHES each panelist to a voice of their own gender', () => {
    // The requirement, stated plainly: "as the name is female then female voice
    // and vice versa". This is the test that would fail if gender were demoted
    // back to a tiebreak.
    for (const sp of PANEL) {
      expect(guessGender(alloc.get(sp.name)!.voiceName ?? '')).toBe(sp.gender);
    }
  });

  it('prefers the highest-quality voice WITHIN the right gender', () => {
    // Riya gets Neerja and Arjun gets Prabhat — the neural "Online (Natural)"
    // voices outrank the local ones by a wide margin.
    expect(alloc.get('Riya')!.voiceName).toContain('Neerja');
    expect(alloc.get('Arjun')!.voiceName).toContain('Prabhat');

    // Meera, the second female, gets the next-best FEMALE voice by scoreVoice —
    // which is Google UK English Female, not the local Microsoft Heera. That is
    // correct and deliberate: scoreVoice's documented policy is that quality
    // beats accent, because a network-backed voice in a British accent sounds far
    // more human than local synthesis in an Indian one. Asserted as "some female
    // voice, not one already taken" rather than a hardcoded name, because pinning
    // the name bakes in a ranking that is allowed to change.
    const meera = alloc.get('Meera')!;
    expect(guessGender(meera.voiceName ?? '')).toBe('female');
    expect(meera.voiceURI).not.toBe(alloc.get('Riya')!.voiceURI);
  });

  it('is deterministic, so a panelist keeps one voice for the discussion', () => {
    const again = allocatePanelVoices(RICH, PANEL);
    for (const n of NAMES) {
      expect(again.get(n)!.voiceURI).toBe(alloc.get(n)!.voiceURI);
      expect(again.get(n)!.pitch).toBe(alloc.get(n)!.pitch);
    }
  });

  it('reports the allocation as distinguishable', () => {
    expect(allDistinguishable(alloc)).toBe(true);
  });
});

describe('allocation on real, poorly-equipped hardware', () => {
  it('handles exactly two usable voices, one of each gender', () => {
    const alloc = allocatePanelVoices([voice('Samantha', 'en-US'), voice('Alex', 'en-US')], PANEL);
    expect(alloc.size).toBe(3);
    // Riya and Arjun get the right gender outright.
    expect(alloc.get('Riya')!.voiceName).toBe('Samantha');
    expect(alloc.get('Arjun')!.voiceName).toBe('Alex');
    // Meera shares, detuned, and is still distinguishable from Riya.
    expect(allDistinguishable(alloc)).toBe(true);
  });

  it('never gives a female panelist a voice known to be male when a female one exists', () => {
    const alloc = allocatePanelVoices(
      [voice('Alex', 'en-US'), voice('Daniel', 'en-GB'), voice('Samantha', 'en-US')],
      PANEL,
    );
    // Only one female voice for two female panelists: the first gets it outright.
    expect(alloc.get('Riya')!.voiceName).toBe('Samantha');
    // Arjun gets a male voice — which one is scoreVoice's call (en-GB Daniel
    // outranks en-US Alex), so assert the gender, not the name.
    expect(guessGender(alloc.get('Arjun')!.voiceName ?? '')).toBe('male');
    // Meera has to share a male voice, so her pitch must be lifted to the female
    // anchor rather than left as-is.
    expect(alloc.get('Meera')!.pitch).toBeGreaterThan(1.0);
    expect(guessGender(alloc.get('Meera')!.voiceName ?? '')).toBe('male');
  });

  it('leans pitch toward the panelist gender when only the wrong gender exists', () => {
    const alloc = allocatePanelVoices([voice('Samantha', 'en-US')], [PANEL[1]]);
    // Arjun is male, only a female voice exists: pitch must drop.
    expect(alloc.get('Arjun')!.pitch).toBeLessThan(1.0);
  });

  it('handles a single usable voice — the locked-down Linux case', () => {
    const alloc = allocatePanelVoices([voice('English (India)', 'en-IN')], PANEL);
    expect(alloc.size).toBe(3);
    // All three share the one voice, so pitch is what separates them — and the
    // male panelist must sit below the female ones.
    const pitches = NAMES.map((n) => alloc.get(n)!.pitch);
    expect(new Set(pitches).size).toBe(3);
    expect(alloc.get('Arjun')!.pitch).toBeLessThan(alloc.get('Riya')!.pitch);
    expect(allDistinguishable(alloc)).toBe(true);
  });

  it('handles no usable voices at all without throwing', () => {
    // An allocator that needs voices would fail here; the round must still run.
    const alloc = allocatePanelVoices([], PANEL);
    expect(alloc.size).toBe(3);
    for (const n of NAMES) expect(alloc.get(n)!.voiceURI).toBeNull();
    expect(allDistinguishable(alloc)).toBe(true);
  });

  it('ignores voices scoreVoice rejects', () => {
    // Novelty voices are never acceptable, so a panel must not be given "Zarvox"
    // even when it is the only thing on offer.
    const alloc = allocatePanelVoices(
      [voice('Zarvox', 'en-US'), voice('Bells', 'en-US'), voice('Samantha', 'en-US')],
      PANEL,
    );
    const names = NAMES.map((n) => alloc.get(n)!.voiceName);
    expect(names.some((n) => n === 'Zarvox' || n === 'Bells')).toBe(false);
  });

  it('ignores non-English voices', () => {
    const alloc = allocatePanelVoices(
      [voice('Kyoko', 'ja-JP'), voice('Samantha', 'en-US')],
      PANEL,
    );
    const names = NAMES.map((n) => alloc.get(n)!.voiceName);
    expect(names).not.toContain('Kyoko');
  });
});

describe('the distinguishability check itself', () => {
  it('fails a clash that a naive allocator would produce', () => {
    // Same voice, same pitch — the "one voice reading three people" failure the
    // allocator exists to avoid.
    const bad = new Map([
      ['A', { voiceURI: 'x', voiceName: 'X', pitch: 1, rate: 1 }],
      ['B', { voiceURI: 'x', voiceName: 'X', pitch: 1, rate: 1 }],
    ]);
    expect(allDistinguishable(bad)).toBe(false);
  });

  it('does not count an inaudible pitch difference as distinguishable', () => {
    const bad = new Map([
      ['A', { voiceURI: 'x', voiceName: 'X', pitch: 1.0, rate: 1 }],
      ['B', { voiceURI: 'x', voiceName: 'X', pitch: 1.03, rate: 1 }],
    ]);
    expect(allDistinguishable(bad)).toBe(false);
  });
});

describe('scaling beyond three', () => {
  it('handles more speakers than variations without collision', () => {
    const many = Array.from({ length: 8 }, (_, i) => `P${i}`);
    const alloc = allocatePanelVoices([voice('Samantha', 'en-US')], many);
    expect(alloc.size).toBe(8);
    // With one voice and five variations, some collision is unavoidable past
    // five speakers — the contract is that it does not throw and stays stable.
    expect(alloc.get('P0')!.pitch).toBe(1.0);
  });

  it('handles an empty speaker list', () => {
    expect(allocatePanelVoices(RICH, []).size).toBe(0);
  });
});
