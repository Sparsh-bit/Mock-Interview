'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { installMediapipeLogFilter } from '@/lib/mediapipeLogs';

const MP_VERSION = '0.10.35';
const WASM_URL = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${MP_VERSION}/wasm`;
const BUNDLE_URL = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${MP_VERSION}/vision_bundle.mjs`;
const MODEL_URL =
  'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task';

// MediaPipe's npm bundle does an internal dynamic import that bundlers can't
// statically resolve, so we load the ESM bundle straight from the CDN at
// runtime (the ignore comments keep webpack/Turbopack from trying to bundle
// it). The npm package is kept only for its TypeScript types.
type VisionModule = typeof import('@mediapipe/tasks-vision');
let _visionPromise: Promise<VisionModule> | null = null;
function loadVision(): Promise<VisionModule> {
  if (!_visionPromise) {
    _visionPromise = import(/* webpackIgnore: true */ /* turbopackIgnore: true */ BUNDLE_URL) as Promise<VisionModule>;
  }
  return _visionPromise;
}

export interface PresenceMetrics {
  faceDetected: boolean;
  lookingAtScreen: boolean;
  /** Rolling % of observed frames with a face looking at the screen. */
  eyeContactPct: number;
  /** 0–1 microphone loudness (RMS), for a live "speaking" meter. */
  micLevel: number;
  /** How many faces are in frame right now. Capped at 2 by the detector config. */
  faceCount: number;
  /**
   * More than one person, sustained for ~1.2s.
   *
   * Sustained rather than instantaneous: someone walking past behind the candidate is not a
   * second interviewee, and a warning that fires on a passer-by is a warning nobody believes.
   */
  multiplePeople: boolean;
  /** Nobody in frame for ~2.5s. The candidate has walked away or covered the camera. */
  candidateAbsent: boolean;
  /**
   * A second person was detected at ANY point this session, and this never clears.
   *
   * Deliberately sticky. A live-only flag can be defeated by having the other person duck out
   * of frame, which makes it worth nothing as a proctoring signal.
   */
  multiplePeopleEver: boolean;
}

const INITIAL: PresenceMetrics = {
  faceDetected: false,
  lookingAtScreen: false,
  eyeContactPct: 100,
  micLevel: 0,
  faceCount: 0,
  multiplePeople: false,
  candidateAbsent: false,
  multiplePeopleEver: false,
};

/**
 * Live webcam + mic behavioral analysis, processed entirely in-browser and
 * never recorded or uploaded. MediaPipe FaceLandmarker (loaded from CDN)
 * gives face landmarks + blendshapes; we derive a rough gaze/eye-contact
 * signal from the eyeLook* blendshapes. Mic loudness comes from the Web
 * Audio API. Everything stops and releases the tracks on stop().
 */
export function usePresenceMonitor() {
  const [active, setActive] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [metrics, setMetrics] = useState<PresenceMetrics>(INITIAL);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const startingRef = useRef(false);
  const streamRef = useRef<MediaStream | null>(null);
  const landmarkerRef = useRef<import('@mediapipe/tasks-vision').FaceLandmarker | null>(null);
  const rafRef = useRef<number | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const framesRef = useRef({
    total: 0,
    contact: 0,
    //: Consecutive frames with more than one face, with zero faces, and the longest run of
    //: the former this session. See the note where these are updated.
    multiFrames: 0,
    absentFrames: 0,
    multiPeak: 0,
  });
  const restoreLogsRef = useRef<(() => void) | null>(null);

  const stop = useCallback(() => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    rafRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    audioCtxRef.current?.close().catch(() => {});
    audioCtxRef.current = null;
    analyserRef.current = null;
    landmarkerRef.current?.close();
    landmarkerRef.current = null;
    framesRef.current = { total: 0, contact: 0, multiFrames: 0, absentFrames: 0, multiPeak: 0 };
    startingRef.current = false;
    // Restore console after MediaPipe is torn down.
    restoreLogsRef.current?.();
    restoreLogsRef.current = null;
    setActive(false);
    setMetrics(INITIAL);
  }, []);

  const start = useCallback(async () => {
    // Guard against double-invocation (React StrictMode re-runs effects in dev).
    if (startingRef.current || streamRef.current) return;
    startingRef.current = true;
    setError(null);
    setLoading(true);
    try {
      if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
        throw new Error('unsupported');
      }
      const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }

      // Mic loudness via Web Audio.
      const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      const audioCtx = new AudioCtx();
      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser);
      audioCtxRef.current = audioCtx;
      analyserRef.current = analyser;

      // MediaPipe/TFLite print benign INFO/WARNING diagnostics through
      // console.error during init + inference; filter only those (reversible)
      // so Next's dev overlay doesn't flag them as real errors.
      if (!restoreLogsRef.current) {
        restoreLogsRef.current = installMediapipeLogFilter();
      }

      // MediaPipe face landmarker (loaded from CDN at runtime).
      const vision = await loadVision();
      const fileset = await vision.FilesetResolver.forVisionTasks(WASM_URL);
      const landmarker = await vision.FaceLandmarker.createFromOptions(fileset, {
        baseOptions: { modelAssetPath: MODEL_URL, delegate: 'GPU' },
        runningMode: 'VIDEO',
        // TWO, not one. A second person in frame is the single thing a proctored interview
        // most needs to notice, and with numFaces: 1 the detector returns at most one set of
        // landmarks — so somebody sitting beside the candidate was invisible BY
        // CONFIGURATION, not by oversight in the loop below.
        //
        // Two rather than more: the cost is per detected face, this runs every animation
        // frame, and the question being answered is "is the candidate alone?" — which two
        // answers as well as five, for half the work.
        numFaces: 2,
        outputFaceBlendshapes: true,
      });
      landmarkerRef.current = landmarker;

      setActive(true);
      setLoading(false);

      const audioData = new Uint8Array(analyser.frequencyBinCount);

      const loop = () => {
        const video = videoRef.current;
        const lm = landmarkerRef.current;
        const an = analyserRef.current;
        if (!video || !lm || !an) return;

        // Mic RMS
        an.getByteTimeDomainData(audioData);
        let sumSq = 0;
        for (let i = 0; i < audioData.length; i++) {
          const v = (audioData[i] - 128) / 128;
          sumSq += v * v;
        }
        const micLevel = Math.min(1, Math.sqrt(sumSq / audioData.length) * 3);

        let faceDetected = false;
        let lookingAtScreen = false;
        let faceCount = 0;
        // Only run detection once the frame actually has pixels — calling
        // detectForVideo on a 0x0 frame makes MediaPipe throw (ROI must be
        // > 0), which would otherwise crash the loop.
        if (video.readyState >= 2 && video.videoWidth > 0 && video.videoHeight > 0) {
          try {
            const res = lm.detectForVideo(video, performance.now());
            faceCount = res.faceLandmarks?.length ?? 0;
            faceDetected = faceCount > 0;
            const shapes = res.faceBlendshapes?.[0]?.categories;
            if (faceDetected && shapes) {
              const byName: Record<string, number> = {};
              for (const c of shapes) byName[c.categoryName] = c.score;
              // Average left/right gaze-away components; high = looking off-screen.
              const gazeAway =
                ((byName.eyeLookOutLeft ?? 0) + (byName.eyeLookInLeft ?? 0) +
                 (byName.eyeLookOutRight ?? 0) + (byName.eyeLookInRight ?? 0) +
                 (byName.eyeLookUpLeft ?? 0) + (byName.eyeLookDownLeft ?? 0) +
                 (byName.eyeLookUpRight ?? 0) + (byName.eyeLookDownRight ?? 0)) / 4;
              lookingAtScreen = gazeAway < 0.55;
            }
          } catch {
            // Transient decode/ROI hiccup — skip this frame, keep the loop alive.
          }
        }

        const f = framesRef.current;
        f.total += 1;
        if (faceDetected && lookingAtScreen) f.contact += 1;
        const eyeContactPct = f.total > 0 ? Math.round((f.contact / f.total) * 100) : 100;

        /*
         * SUSTAINED signals, not per-frame ones.
         *
         * Detection flickers: a candidate turns to think and the face is lost for three
         * frames; someone walks past behind them and there are briefly two. Raising a warning
         * on a single frame would make the UI strobe and would cry wolf, which is worse than
         * not warning at all — a proctoring signal nobody believes is noise.
         *
         * So both are counted in consecutive frames and only reported once they persist.
         * At ~60fps these are roughly 1.2 and 2.5 seconds: long enough that a passer-by or a
         * glance away does not trip them, short enough to catch someone actually sitting down
         * beside the candidate.
         */
        if (faceCount > 1) f.multiFrames += 1;
        else f.multiFrames = 0;
        if (faceCount === 0) f.absentFrames += 1;
        else f.absentFrames = 0;

        if (f.multiFrames > f.multiPeak) f.multiPeak = f.multiFrames;

        setMetrics({
          faceDetected,
          lookingAtScreen,
          eyeContactPct,
          micLevel,
          faceCount,
          multiplePeople: f.multiFrames >= 75,
          candidateAbsent: f.absentFrames >= 150,
          // Sticky for the whole session: a second person who appeared and left still
          // happened, and a warning that clears itself the moment they duck out of frame is
          // a warning that can be defeated by ducking out of frame.
          multiplePeopleEver: f.multiPeak >= 75,
        });
        rafRef.current = requestAnimationFrame(loop);
      };
      rafRef.current = requestAnimationFrame(loop);
    } catch (e) {
      // Clean up a partially-acquired stream so a retry can work.
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
      setLoading(false);
      setActive(false);
      const name = (e as { name?: string })?.name ?? '';
      const msg = e instanceof Error ? e.message : String(e);
      if (name === 'NotAllowedError' || /permission|denied|notallowed/i.test(msg)) {
        setError('Camera/microphone permission was denied. Allow access in your browser and try again.');
      } else if (name === 'NotFoundError' || /notfound|devicesnotfound/i.test(msg)) {
        setError('No camera or microphone was found on this device.');
      } else if (msg === 'unsupported') {
        setError('This browser does not support camera capture, or the page is not on a secure (https/localhost) origin.');
      } else {
        setError('Could not start camera analysis. Please try again.');
      }
      // Restore console if we failed after installing the filter.
      restoreLogsRef.current?.();
      restoreLogsRef.current = null;
    } finally {
      startingRef.current = false;
    }
  }, []);

  useEffect(() => () => stop(), [stop]);

  return { videoRef, active, loading, error, metrics, start, stop };
}
