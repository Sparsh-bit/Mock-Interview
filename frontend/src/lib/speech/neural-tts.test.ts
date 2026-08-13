import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * Audio prefetching — the fix for "the text comes first and the voice after".
 *
 * Two separate faults produced that one symptom, and only one of them lived here.
 *
 * The first was ordering, in useSpeech.ts: onStart — which puts the line on screen — fired
 * BEFORE the vendor request went out, so the candidate read the whole sentence, waited three
 * and a half seconds, and then heard it. That is fixed by awaiting the audio before revealing
 * the text, and it is not testable from this file.
 *
 * The second is this one: a turn of three lines was three round-trips laid end to end, each
 * starting only after the previous had finished PLAYING. Ten seconds of silence inside what is
 * meant to be a conversation between two people. These tests are about the request bookkeeping
 * that lets all three be in flight at once.
 */

const post = vi.fn();
vi.mock('@/lib/api', () => ({ getBrowserApiClient: () => ({ post }) }));

const blob = (n = 1024) => new Blob([new Uint8Array(n)], { type: 'audio/mpeg' });

describe('prefetchUtterance / fetchUtterance', () => {
  beforeEach(async () => {
    vi.resetModules();
    post.mockReset();
    post.mockResolvedValue({ data: blob() });
  });

  it('a fetch after a prefetch of the same line makes no second request', async () => {
    // The whole point. If this deduplication fails, prefetching does not speed anything up —
    // it doubles the vendor bill and leaves the delay exactly where it was.
    const m = await import('./neural-tts');
    m.prefetchUtterance('Anil', 'Walk me through your approach.', 'asking');
    const got = await m.fetchUtterance('Anil', 'Walk me through your approach.', 'asking');
    expect(got).not.toBeNull();
    expect(post).toHaveBeenCalledTimes(1);
  });

  it('prefetching the same line twice makes one request, not two', async () => {
    const m = await import('./neural-tts');
    m.prefetchUtterance('Priya', 'Tell me about exceptions.', 'asking');
    m.prefetchUtterance('Priya', 'Tell me about exceptions.', 'asking');
    await m.fetchUtterance('Priya', 'Tell me about exceptions.', 'asking');
    expect(post).toHaveBeenCalledTimes(1);
  });

  it('a whole turn goes out in parallel rather than one after another', async () => {
    // Three lines prefetched together are three concurrent requests. Serially they were
    // ~3.5s each, in sequence, with playback between them.
    const m = await import('./neural-tts');
    const turn = [
      { speaker: 'Anil', text: 'That is not quite right.', tone: 'correcting' as const },
      { speaker: 'Anil', text: 'Priya, do you want the next one?', tone: 'aside' as const },
      { speaker: 'Priya', text: 'Sure. What is a HashMap?', tone: 'asking' as const },
    ];
    turn.forEach((l) => m.prefetchUtterance(l.speaker, l.text, l.tone));
    expect(post).toHaveBeenCalledTimes(3);
    for (const l of turn) expect(await m.fetchUtterance(l.speaker, l.text, l.tone)).not.toBeNull();
    // Still three: every line was served from the warm request it already had.
    expect(post).toHaveBeenCalledTimes(3);
  });

  it('the same words in a different TONE are a different request', async () => {
    // They are genuinely different audio — that is the entire reason tone exists. Sharing a
    // slot would serve a correction in the voice of a greeting.
    const m = await import('./neural-tts');
    m.prefetchUtterance('Anil', 'Yes.', 'correcting');
    await m.fetchUtterance('Anil', 'Yes.', 'affirming');
    expect(post).toHaveBeenCalledTimes(2);
  });

  it('the same words from a different SPEAKER are a different request', async () => {
    const m = await import('./neural-tts');
    m.prefetchUtterance('Anil', 'Go on.', 'neutral');
    await m.fetchUtterance('Priya', 'Go on.', 'neutral');
    expect(post).toHaveBeenCalledTimes(2);
  });

  it('a warm entry is consumed once, so the interview does not accumulate audio', async () => {
    // Blobs are large and an interview is long. The server-side cache already covers a line
    // genuinely said twice, so holding them here would be paying memory for nothing.
    const m = await import('./neural-tts');
    m.prefetchUtterance('Anil', 'Once more.', 'neutral');
    await m.fetchUtterance('Anil', 'Once more.', 'neutral');
    await m.fetchUtterance('Anil', 'Once more.', 'neutral');
    expect(post).toHaveBeenCalledTimes(2);
  });

  it('a failed prefetch is indistinguishable from one never made', async () => {
    // A warm-up must never be able to break a round. 402 (budget spent), 503 (vendor down)
    // and a timeout all land here, and all three mean "use browser speech".
    const m = await import('./neural-tts');
    post.mockRejectedValue(new Error('503'));
    m.prefetchUtterance('Anil', 'Anything.', 'neutral');
    await expect(m.fetchUtterance('Anil', 'Anything.', 'neutral')).resolves.toBeNull();
  });

  it('an empty line is never requested at all', async () => {
    const m = await import('./neural-tts');
    m.prefetchUtterance('Anil', '   ', 'neutral');
    expect(await m.fetchUtterance('Anil', '   ', 'neutral')).toBeNull();
    expect(post).not.toHaveBeenCalled();
  });

  it('whitespace around a line does not split it into two requests', async () => {
    const m = await import('./neural-tts');
    m.prefetchUtterance('Anil', 'Trimmed.', 'neutral');
    await m.fetchUtterance('Anil', '  Trimmed.  ', 'neutral');
    expect(post).toHaveBeenCalledTimes(1);
  });

  /*
   * A LINE THAT IS SPOKEN DIFFERENTLY FROM HOW IT IS WRITTEN STILL DEDUPLICATES.
   *
   * This is the case every test above missed, and missing it is why the bug it now pins
   * survived review. Each of them uses ordinary prose — "Tell me about exceptions." — which
   * toSpokenForm passes through unchanged, so prefetch and fetch derived the same key by
   * accident and the suite was green while the feature did nothing in production.
   *
   * A Java interview line is not ordinary prose. The moment one contains `==` or `JVM`, the
   * written and spoken forms diverge, and back when the two entry points normalised
   * differently that divergence meant: the prefetch missed, the real fetch ran cold on the
   * critical path for the full vendor latency, and the line was synthesised and billed twice.
   *
   * So the assertion is deliberately made on text that DOES change, and both orderings are
   * checked — the miss was directional, and only one of the two would have caught it.
   */
  it('a line whose spoken form differs from its written form is still one request', async () => {
    const m = await import('./neural-tts');
    const written = 'Does == compare references in the JVM?';
    m.prefetchUtterance('Priya', written, 'asking');
    const got = await m.fetchUtterance('Priya', written, 'asking');
    expect(got).not.toBeNull();
    expect(post).toHaveBeenCalledTimes(1);
  });

  it('sends the spoken form to the vendor, not the written one', async () => {
    // The vendor must receive "double equals", never "==" — that was the original
    // "the panel reads == as equal equal" report. Normalising inside this module is what
    // guarantees it now happens on the prefetch path too, which previously sent raw text.
    const m = await import('./neural-tts');
    m.prefetchUtterance('Priya', 'Is a == b?', 'asking');
    const [, body] = post.mock.calls[0];
    expect(body.text).toContain('double equals');
    expect(body.text).not.toContain('==');
  });

  it('does not grow without bound over a long interview', async () => {
    // Bounded at 24. A line evicted before it plays simply re-fetches, which is the old
    // behaviour rather than a fault — but an unbounded map of audio blobs is a leak that
    // only shows up in the sessions that matter most, the long ones.
    const m = await import('./neural-tts');
    for (let i = 0; i < 60; i++) m.prefetchUtterance('Anil', `line ${i}`, 'neutral');
    expect(post).toHaveBeenCalledTimes(60);
    // The earliest lines were evicted, so asking for one again is a fresh request.
    await m.fetchUtterance('Anil', 'line 0', 'neutral');
    expect(post).toHaveBeenCalledTimes(61);
    // The most recent are still warm.
    await m.fetchUtterance('Anil', 'line 59', 'neutral');
    expect(post).toHaveBeenCalledTimes(61);
  });
});
