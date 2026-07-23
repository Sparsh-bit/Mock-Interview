'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Camera, Eye, EyeOff, Loader2, Mic, ShieldCheck, X } from 'lucide-react';
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
  const [consented, setConsented] = useState(false);
  const { videoRef, active, loading, error, metrics, start, stop } = usePresenceMonitor();

  const enable = async () => {
    setConsented(true);
    await start();
  };

  const disable = () => {
    stop();
    setConsented(false);
  };

  if (!consented) {
    return (
      <div className="glass rounded-2xl border-border/50 p-5">
        <div className="mb-3 flex items-center gap-2">
          <ShieldCheck className="h-4 w-4 text-primary" />
          <h3 className="text-sm font-semibold">Presence check (optional)</h3>
        </div>
        <p className="mb-4 text-xs leading-relaxed text-muted-foreground">
          Enable your camera and microphone to get live feedback on eye contact and speaking
          during the interview — just like a real one. Everything is analyzed on your device in
          real time and <strong>never recorded, saved, or uploaded</strong>. You can turn it off
          anytime.
        </p>
        <Button size="sm" onClick={enable}>
          <Camera className="h-4 w-4" /> Enable camera &amp; mic
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
        {active && (
          <div className="absolute left-3 top-3 flex items-center gap-1.5 rounded-full bg-black/50 px-2.5 py-1 text-[11px] font-medium text-white backdrop-blur-sm">
            <span className="h-1.5 w-1.5 rounded-full bg-red-500" /> Live · on device
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
        <p className="p-4 text-xs text-red-600">{error}</p>
      ) : (
        <div className="grid grid-cols-2 gap-px bg-border/60">
          {/* Eye contact */}
          <div className="bg-surface-elevated p-4">
            <div className="mb-1 flex items-center gap-1.5 text-xs text-muted-foreground">
              {metrics.lookingAtScreen ? <Eye className="h-3.5 w-3.5 text-emerald-600" /> : <EyeOff className="h-3.5 w-3.5 text-amber-600" />}
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
