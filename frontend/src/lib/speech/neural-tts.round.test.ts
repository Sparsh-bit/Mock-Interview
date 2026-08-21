import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * ONE VOICE IDENTITY PER ROUND — the vendor half.
 *
 * THE REPORT: "in the starting of the interview the voices changes and then it changed again to
 * the old voices." Two distinct faults produced that one sentence, and both of them lived in
 * the fact that nothing in the speech layer remembered a decision.
 *
 *   THE FIRST LINE RACED THE PROBE. `/tts/status` was fetched from an effect and dropped into a
 *   ref that nothing awaited, so the greeting read `false`, spoke on the browser's voice, and
 *   the next line — probe now landed — spoke on Fish.
 *
 *   AND A FAILURE DOWNGRADED EXACTLY ONE LINE. A 402 (budget spent) or 503 (vendor blip) fell
 *   back for that utterance and left the decision untouched, so the following line tried again
 *   and frequently succeeded. Neural, browser, neural, browser, for the rest of the interview.
 *
 * These tests pin the two properties that make that impossible: the probe is asked once and is
 * awaitable, and the degrade is one-way. The second one is the assertion that would have caught
 * the reported bug, so it is worth more than the rest of this file put together.
 *
 * WHY THE MOCK CARRIES ITS OWN ApiError. `_fetchNow` now reads the status code off the error
 * rather than discarding it — that is what lets a 402 be named as a budget failure in the
 * console instead of being indistinguishable from a timeout. `instanceof` therefore has to be
 * against the class the module under test actually imported, which is this one.
 */

const post = vi.fn();
const get = vi.fn();

vi.mock('@/lib/api', () => {
  class ApiError extends Error {
    status: number;
    constructor(status: number, message = `HTTP ${status}`) {
      super(message);
      this.status = status;
    }
  }
  return { ApiError, getBrowserApiClient: () => ({ get, post }) };
});

const blob = (n = 1024) => new Blob([new Uint8Array(n)], { type: 'audio/mpeg' });

const status = (over: Record<string, unknown> = {}) => ({
  data: {
    enabled: true,
    provider: 'fish',
    budget_remaining_usd: 4.2,
    voices: { Anil: true, Priya: true },
    ...over,
  },
});

/** The mocked ApiError, from the same module instance neural-tts.ts resolved. */
async function apiError(code: number): Promise<Error> {
  const { ApiError } = (await import('@/lib/api')) as unknown as {
    ApiError: new (status: number) => Error;
  };
  return new ApiError(code);
}

describe('ttsStatusOnce — the probe the first line waits for', () => {
  beforeEach(() => {
    // Module state is the thing under test here, so isolating it per test is not hygiene.
    vi.resetModules();
    vi.useRealTimers();
    get.mockReset();
    post.mockReset();
    get.mockResolvedValue(status());
    post.mockResolvedValue({ data: blob() });
  });

  it('is asked ONCE however many callers want the answer', async () => {
    // speakAs asks for every line, prefetchTurn asks for every turn, and the mount effect asks
    // as well. Asking the server each time would put a round trip in front of every utterance
    // to re-learn something that cannot change mid-round.
    const m = await import('./neural-tts');
    const answers = await Promise.all(Array.from({ length: 10 }, () => m.ttsStatusOnce()));
    expect(get).toHaveBeenCalledTimes(1);
    // And every caller got the same answer, not merely an equal one.
    for (const a of answers) expect(a).toBe(answers[0]);
  });

  it('does not retry, and imposes its own deadline', async () => {
    /*
     * `/tts/status` is a GET, so without `retry: false` it inherits DEFAULT_RETRY_CONFIG —
     * three attempts backing off to a 10s ceiling — on top of the client's 30s default timeout.
     * Against a cold or 502-ing backend that is up to a minute spent answering a yes/no
     * question that has to be answered before anybody speaks, while /next and /panel/turn
     * succeed on an app that woke up in between. That patience IS the reported voice change.
     */
    const m = await import('./neural-tts');
    await m.ttsStatusOnce();
    const [path, config] = get.mock.calls[0];
    expect(path).toBe('/api/v1/tts/status');
    expect(config).toMatchObject({ retry: false });
    expect(config.timeout).toBeLessThanOrEqual(3_000);
  });

  it('resolves at the cap when the request never answers, and never rejects', async () => {
    /*
     * THE NO-DEADLOCK PROPERTY, asserted rather than reasoned about. The speech chain awaits
     * this before the first word of the interview, so a promise that never settles is a panel
     * that never speaks — a far worse bug than the one being fixed. A hung socket is not a slow
     * one, and only the race against a timer covers it.
     */
    vi.useFakeTimers();
    const m = await import('./neural-tts');
    get.mockReturnValue(new Promise(() => {}));

    const settled = vi.fn();
    const p = m.ttsStatusOnce().then(settled);
    await vi.advanceTimersByTimeAsync(2_400);
    expect(settled).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(600);
    await expect(p).resolves.toBeUndefined();
    expect(settled).toHaveBeenCalledWith(null);
  });

  it('a rejected request is a "no", not an error the speech chain has to catch', async () => {
    const m = await import('./neural-tts');
    get.mockRejectedValue(await apiError(401));
    await expect(m.ttsStatusOnce()).resolves.toBeNull();
  });
});

describe('the degrade latch — why one bad line cannot become an alternating interview', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.useRealTimers();
    get.mockReset();
    post.mockReset();
    get.mockResolvedValue(status());
    post.mockResolvedValue({ data: blob() });
  });

  it('THE REGRESSION: a 402 stops the NEXT line from trying again', async () => {
    /*
     * This is the assertion that would have caught the reported bug. api/v1/tts.py checks its
     * response cache BEFORE the daily budget, deliberately, so a cache hit stays free — which
     * means that past the budget the fixed question bank keeps returning 200 neural audio while
     * unique AI-written panel prose 402s. Without a latch, neural and browser then alternate
     * line by line for the rest of the interview with nothing having failed anywhere.
     */
    const m = await import('./neural-tts');
    post.mockRejectedValueOnce(await apiError(402));

    expect(await m.fetchUtterance('Anil', 'First line.', 'asking')).toBeNull();
    expect(m.neuralOff()).toBe(true);

    // The next line does not merely fall back — it does not even ask.
    post.mockResolvedValue({ data: blob() });
    expect(await m.fetchUtterance('Anil', 'Second line.', 'asking')).toBeNull();
    expect(post).toHaveBeenCalledTimes(1);
  });

  it('latches on a 503 and on a timeout too, not just on a spent budget', async () => {
    // A vendor blip is transient and a budget is not, and the latch treats them identically on
    // purpose: one consistent voice beats a better voice that changes every other line, and a
    // "allow one strike" counter is a second piece of state that has to be correct.
    const m = await import('./neural-tts');
    post.mockRejectedValueOnce(await apiError(503));
    await m.fetchUtterance('Priya', 'Vendor down.', 'neutral');
    expect(m.neuralOff()).toBe(true);

    vi.resetModules();
    const m2 = await import('./neural-tts');
    post.mockReset();
    post.mockRejectedValueOnce(new Error('The operation was aborted'));
    await m2.fetchUtterance('Priya', 'Timed out.', 'neutral');
    expect(m2.neuralOff()).toBe(true);
  });

  it('a 200 carrying no audio latches as well', async () => {
    // A blob of zero bytes is a proxy or vendor fault. It cannot be spoken, so it is a failure
    // whatever the status line said.
    const m = await import('./neural-tts');
    post.mockResolvedValueOnce({ data: blob(0) });
    expect(await m.fetchUtterance('Anil', 'Empty.', 'neutral')).toBeNull();
    expect(m.neuralOff()).toBe(true);
  });

  it('drops audio already in flight, so a warm line cannot arrive after the latch closed', async () => {
    /*
     * A turn is prefetched three lines at a time. Without clearing the in-flight map, a request
     * that was already running when the latch closed would still resolve with perfectly good
     * audio and hand ONE neural line to a round that has committed to browser voices — which is
     * the alternation the latch exists to remove, reintroduced at the worst possible moment.
     */
    const m = await import('./neural-tts');
    post.mockResolvedValue({ data: blob() });
    m.prefetchUtterance('Anil', 'Warm and paid for.', 'asking');
    expect(post).toHaveBeenCalledTimes(1);

    m.degradeNeural('budget');
    expect(await m.fetchUtterance('Anil', 'Warm and paid for.', 'asking')).toBeNull();
    // No second request either: the round is closed, not re-attempting.
    expect(post).toHaveBeenCalledTimes(1);
  });

  it('a prefetch after the latch bills nothing', async () => {
    const m = await import('./neural-tts');
    m.degradeNeural('vendor');
    m.prefetchUtterance('Priya', 'Never spoken.', 'asking');
    expect(post).not.toHaveBeenCalled();
  });

  it('resetSpeechRound is the ONLY way back to neural speech', async () => {
    /*
     * Load-bearing rather than hygiene. `_neuralOff` and the probe memo are module scope, so
     * "round" means "for as long as this module stays loaded" — and a second interview started
     * by client-side navigation does not reload it. Without this call one 402 in one interview
     * would silently put every later interview in the tab on browser voices, turning a single
     * bad round into a permanent complaint about the product's voices.
     *
     * Equally: nothing ELSE may clear it, or the latch is not a latch. fetchUtterance,
     * prefetchUtterance and a fresh probe are all exercised here and none of them reopen it.
     */
    const m = await import('./neural-tts');
    m.degradeNeural('budget');

    await m.fetchUtterance('Anil', 'Still off.', 'neutral');
    m.prefetchUtterance('Anil', 'Still off.', 'neutral');
    await m.ttsStatusOnce();
    expect(m.neuralOff()).toBe(true);

    m.resetSpeechRound();
    expect(m.neuralOff()).toBe(false);
    // And the probe is asked again for the new round, rather than replaying the old answer.
    get.mockClear();
    await m.ttsStatusOnce();
    expect(get).toHaveBeenCalledTimes(1);
  });

  it('warns once per round, not once per line', async () => {
    // Whoever reads a candidate's console after a complaint about the voices needs this line
    // and its reason. Forty copies of it is the same as none.
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const m = await import('./neural-tts');
    m.degradeNeural('budget');
    m.degradeNeural('vendor');
    m.degradeNeural('budget');
    expect(warn).toHaveBeenCalledTimes(1);
    expect(String(warn.mock.calls[0][0])).toContain('budget');
    warn.mockRestore();
  });
});
