'use client';

import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Camera, Eye, EyeOff, Loader2, Mic, ShieldCheck, UserX, Users, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { usePresenceMonitor } from '@/hooks/usePresenceMonitor';
import { cn } from '@/lib/utils';

/**
 * Opt-in live camera + mic presence check. Shows a consent gate first;
 * once accepted, streams the webcam locally and displays live eye-contact
 * and speaking indicators. Nothing is recorded or uploaded — analysis is
 * in-browser and discarded when stopped.
 */
export function PresenceMonitor() {
  /*
   * ON BY DEFAULT, for the whole interview.
   *
   * This was opt-in behind an "Enable camera & mic" button, which meant the common case was a
   * candidate practising with the camera off — and a mock interview with no camera is missing
   * the thing that makes a real one uncomfortable. Real rounds are invigilated from the
   * moment they start; you do not get asked whether you would like to be watched.
   *
   * The privacy position is unchanged and is what makes defaulting to on defensible: every
   * frame is analysed in the browser by MediaPipe and NOTHING is recorded, saved or uploaded.
   * There is no stream to send because there is no server involved. The candidate can still
   * turn it off at any point, and the browser's own permission prompt is the real gate — this
   * default only decides whether we ask for it up front or make them go looking.
   */
  const [consented, setConsented] = useState(true);
  const { videoRef, active, loading, error, metrics, start, stop } = usePresenceMonitor();

  // Start only AFTER the <video> element has mounted (consent flips true),
  // otherwise videoRef.current is still null and the stream never attaches.
  useEffect(() => {
    if (consented) start();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [consented]);

  const enable = () => setConsented(true);

  const disable = () => {
    stop();
    setConsented(false);
  };

  if (!consented) {
    return (
      <div className="glass rounded-2xl border-border/50 p-5">
        <div className="mb-3 flex items-center gap-2">
          <ShieldCheck className="h-4 w-4 text-primary" />
          <h3 className="text-sm font-semibold">Camera is off</h3>
        </div>
        <p className="mb-4 text-xs leading-relaxed text-muted-foreground">
          The camera stays on for the whole interview, the way a real panel round is
          invigilated — it tracks your eye contact, and it flags if a second person appears in
          frame. Everything is analysed on your device and{' '}
          <strong>never recorded, saved, or uploaded</strong>. You can turn it off at any time.
        </p>
        <Button size="sm" onClick={enable}>
          <Camera className="h-4 w-4" /> Turn the camera back on
        </Button>
      </div>
    );
  }

  return (
    <div className="glass overflow-hidden rounded-2xl border-border/50">
      <div className="relative aspect-video bg-black">
        {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
        <video ref={videoRef} muted playsInline className="h-full w-full -scale-x-100 object-cover" />
        {loading && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-black/60 text-white">
            <Loader2 className="h-6 w-6 animate-spin" />
            <span className="text-xs">Starting camera analysis…</span>
          </div>
        )}
        {/* PROCTORING WARNINGS.
            A real interview is invigilated, and the two things an invigilator would actually
            say something about are somebody else in the room and the candidate leaving it.
            Both are sustained signals rather than per-frame ones — see usePresenceMonitor —
            because a warning that fires on a passer-by is a warning nobody believes.

            ABSOLUTELY POSITIONED, AND THAT IS A BUG FIX, NOT A STYLE CHOICE. These used to
            be in normal flow inside this box, which is a fixed `aspect-video` container that
            the <video> already fills at h-full — so each warning was laid out BELOW the
            video, overflowed the container, and was clipped by the `overflow-hidden` on the
            card. The detection could fire perfectly and the candidate would still see
            nothing, which is indistinguishable from detection not working at all. Overlaying
            the video is also simply what a proctoring alert should do. */}
        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 space-y-2 p-3">
        {active && metrics.multiplePeople && (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-xl border border-destructive/60 bg-destructive px-3 py-2 text-[11px] leading-snug text-destructive-foreground shadow-lg"
          >
            <Users className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
            <span>
              <span className="font-semibold">Another person is in frame.</span> In a real
              interview this ends the round. Make sure you are alone before continuing.
            </span>
          </div>
        )}
        {active && !metrics.multiplePeople && metrics.multiplePeopleEver && (
          <div className="flex items-start gap-2 rounded-xl border border-accent-amber/60 bg-accent-amber/95 px-3 py-2 text-[11px] leading-snug text-accent-amber-ink shadow-lg backdrop-blur-sm">
            <Users className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
            {/* Sticky on purpose: a flag that clears when the second person ducks out of
                frame can be defeated by ducking out of frame. */}
            <span>A second person was detected earlier in this interview.</span>
          </div>
        )}
        {active && metrics.candidateAbsent && (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-xl border border-accent-amber/60 bg-accent-amber/95 px-3 py-2 text-[11px] leading-snug text-accent-amber-ink shadow-lg backdrop-blur-sm"
          >
            <UserX className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
            <span>
              <span className="font-semibold">We cannot see you.</span> The panel is still
              waiting — come back into frame.
            </span>
          </div>
        )}
        </div>

        {active && (
          <div className="absolute left-3 top-3 z-10 flex items-center gap-1.5">
            <span className="flex items-center gap-1.5 rounded-full bg-black/50 px-2.5 py-1 text-[11px] font-medium text-white backdrop-blur-sm">
              <span className="h-1.5 w-1.5 rounded-full bg-accent-coral" /> Live · on device
            </span>
            {/*
              THE LIVE COUNT, shown always rather than only when it is wrong.
              Two reasons. A real proctored round tells you it can see you — silence about
              what the camera thinks is what makes candidates distrust it. And when this said
              nothing, "the camera is not detecting two people" was impossible to tell apart
              from "the warning is not rendering": now the number is on screen, so the two
              failures look different. It is the raw per-frame count, deliberately un-smoothed
              — the WARNING is the sustained signal, this is the instrument reading.
            */}
            <span
              className={cn(
                'rounded-full px-2.5 py-1 text-[11px] font-semibold backdrop-blur-sm',
                metrics.faceCount > 1
                  ? 'bg-destructive text-destructive-foreground'
                  : metrics.faceCount === 1
                    ? 'bg-black/50 text-white'
                    : 'bg-accent-amber text-accent-amber-ink',
              )}
            >
              {metrics.faceCount === 1
                ? '1 person'
                : metrics.faceCount === 0
                  ? 'nobody in frame'
                  : `${metrics.faceCount} people`}
            </span>
          </div>
        )}
        <button
          onClick={disable}
          title="Turn off"
          className="absolute right-3 top-3 flex h-7 w-7 items-center justify-center rounded-full bg-black/50 text-white backdrop-blur-sm hover:bg-black/70"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {error ? (
        <p className="p-4 text-xs text-accent-coral-ink">{error}</p>
      ) : (
        <div className="grid grid-cols-2 gap-px bg-border/60">
          {/* Eye contact */}
          <div className="bg-surface-elevated p-4">
            <div className="mb-1 flex items-center gap-1.5 text-xs text-muted-foreground">
              {metrics.lookingAtScreen ? <Eye className="h-3.5 w-3.5 text-accent-emerald-ink" /> : <EyeOff className="h-3.5 w-3.5 text-accent-amber-ink" />}
              Eye contact
            </div>
            <p className="text-2xl font-semibold tracking-tight">
              {metrics.faceDetected ? `${metrics.eyeContactPct}%` : '—'}
            </p>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              {!metrics.faceDetected ? 'No face detected' : metrics.lookingAtScreen ? 'Looking at screen' : 'Looking away'}
            </p>
          </div>
          {/* Speaking */}
          <div className="bg-surface-elevated p-4">
            <div className="mb-1 flex items-center gap-1.5 text-xs text-muted-foreground">
              <Mic className="h-3.5 w-3.5 text-primary" /> Speaking
            </div>
            <div className="flex h-8 items-end gap-1">
              <AnimatePresence>
                {Array.from({ length: 12 }).map((_, i) => {
                  const on = metrics.micLevel * 12 > i;
                  return (
                    <motion.span
                      key={i}
                      className={cn('w-1.5 rounded-full', on ? 'bg-primary' : 'bg-border')}
                      animate={{ height: on ? 8 + i * 2 : 4 }}
                      transition={{ duration: 0.1 }}
                    />
                  );
                })}
              </AnimatePresence>
            </div>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              {metrics.micLevel > 0.08 ? 'Detecting your voice' : 'Quiet'}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
