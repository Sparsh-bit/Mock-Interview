import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * STREAMING MOVES THE SYNTHESIS EARLIER. IT MUST NOT MOVE THE WORDS EARLIER.
 *
 * The panel writes its four lines into one JSON object left to right, so line one is finished
 * long before line four. Streaming lets the browser start synthesising line one while the rest
 * is still being written — measured at ~680ms against the live model by
 * backend/scripts/panel_stream_latency.py.
 *
 * The obvious next step is the wrong one. This page has fixed "the words appear seconds before
 * the voice" TWICE (see one-voice.test.ts), and the reveal in the speak loop is driven by
 * `onStart` for exactly that reason: a line and its audio arrive together. Rendering streamed
 * text would undo that and reintroduce the bug somewhere new — with the extra twist that
 * streamed text is PROVISIONAL, read from a half-written object and discarded on a server-side
 * retry. So the words on screen must still come from the validated `done` payload.
 *
 * These are source assertions, for the reason mic-interlock.test.ts sets out at length: the
 * page owns a MediaStream, an AudioContext, MediaPipe and speechSynthesis, none of which exist
 * in jsdom. What that leaves catchable is the regression that actually happens — somebody
 * "improving" the stream callback into a renderer during a refactor.
 */

const PAGE = readFileSync(
  join(process.cwd(), 'src/app/(interview)/session/[id]/page.tsx'),
  'utf8',
);
const HOOK = readFileSync(join(process.cwd(), 'src/hooks/useInterviewPanel.ts'), 'utf8');

/** Source with comments removed, so an assertion cannot match its own explanation. */
const CODE = PAGE.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
const HOOK_CODE = HOOK.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');

/** The body of the stream call in speakTurn: everything inside `streamPanelTurn(...)`. */
const STREAM_CALL = (() => {
  const start = CODE.indexOf('streamPanelTurn(');
  return CODE.slice(start, CODE.indexOf('setPanelPending(false)', start));
})();

describe('the panel turn is streamed', () => {
  it('asks for the stream before falling back to the whole turn', () => {
    expect(CODE).toContain('streamPanelTurn(');
    const streamAt = CODE.indexOf('streamPanelTurn(');
    const wholeAt = CODE.indexOf('panelTurn.mutateAsync(turnArgs)');
    expect(streamAt).toBeGreaterThan(-1);
    expect(wholeAt).toBeGreaterThan(streamAt);
  });

  it('falls back to the whole turn when streaming is unavailable', () => {
    // Null means "no stream here" — an SSE-hostile proxy, no ReadableStream, a blip. It is
    // not a failure, and it must not cost the candidate the turn.
    expect(CODE).toContain('streamed ?? (await panelTurn.mutateAsync(turnArgs))');
  });

  it('sends the identical arguments to both paths', () => {
    // Two argument objects would be two turns: a different stage or question reaches a
    // different cache key, so the fallback would silently be a different turn.
    expect(CODE).toContain('const turnArgs = {');
    expect(STREAM_CALL).toContain('turnArgs');
    expect(CODE).toContain('panelTurn.mutateAsync(turnArgs)');
  });
});

describe('streamed lines warm audio and never render', () => {
  it('the stream callback only prefetches', () => {
    expect(STREAM_CALL).toContain('voicesRef.current.prefetchTurn([line])');
  });

  it('the stream callback does not append to the thread', () => {
    // THE REGRESSION THIS FILE EXISTS FOR. setPanelLines here is the words arriving ahead of
    // the voice, which is the bug this page has already fixed twice.
    expect(STREAM_CALL).not.toContain('setPanelLines');
  });

  it('the stream callback does not speak', () => {
    // Speaking here would put two voices on the same line: this one and the ordered loop
    // below, which is the other half of the same failure.
    expect(STREAM_CALL).not.toContain('speakAs');
  });

  it('the reveal is still driven by onStart in the speak loop', () => {
    // The invariant itself, restated here so a change to the loop fails this file too rather
    // than only one-voice.test.ts.
    expect(CODE).toContain('onStart: reveal');
    const loop = CODE.slice(CODE.indexOf('for (const line of result.turns)'));
    expect(loop).toContain('setPanelLines((prev) => [...prev, line])');
  });

  it('the words spoken come from the resolved turn, not from the stream', () => {
    // `result` is `streamed ?? whole`, and `streamed` is built from the `done` event alone.
    const loop = CODE.slice(CODE.indexOf('for (const line of result.turns)'));
    expect(loop).toContain('result.turns');
  });
});

describe('the SSE reader', () => {
  it('only resolves from the done event', () => {
    // Everything before `done` is provisional — the server says so and means it. A reader
    // that assembled its result from `line` events would return a turn the server never
    // validated.
    expect(HOOK_CODE).toContain("name === 'done'");
    expect(HOOK_CODE).toContain('done = payload as PanelTurnResult');
    expect(HOOK_CODE).toContain('return done;');
  });

  it('throws away warmed lines when the server restarts', () => {
    // A retry rewrites the answer from the top. Without this the client would resolve with a
    // turn from the abandoned attempt.
    expect(HOOK_CODE).toContain("name === 'restart'");
  });

  it('keeps a partial frame in the buffer instead of parsing it', () => {
    // SSE frames end at a blank line. Parsing whatever arrived last would be reading half an
    // event, and a panel line legitimately contains newlines.
    expect(HOOK_CODE).toContain("buffer.split('\\n\\n')");
    expect(HOOK_CODE).toContain('buffer = frames.pop() ?? ');
  });

  it('returns null rather than throwing on any failure', () => {
    // The caller treats null as "use the whole-turn endpoint". A throw would propagate into
    // speakTurn, whose contract is that it never rejects.
    const fn = HOOK_CODE.slice(
      HOOK_CODE.indexOf('export async function streamPanelTurn'),
      HOOK_CODE.indexOf('export function useInterviewPanel'),
    );
    expect(fn).toContain('return null;');
    expect(fn).toContain('} catch {');
  });

  it('carries the access token, because fetch does not go through ApiClient', () => {
    const fn = HOOK_CODE.slice(
      HOOK_CODE.indexOf('export async function streamPanelTurn'),
      HOOK_CODE.indexOf('export function useInterviewPanel'),
    );
    expect(fn).toContain('Authorization');
    expect(CODE).toContain('await getBrowserAccessToken()');
  });
});
