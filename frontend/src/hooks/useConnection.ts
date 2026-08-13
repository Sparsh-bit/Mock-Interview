'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Is the connection actually working?
 *
 * Reported: "if the device goes offline then the interview must give the warning of the
 * internet connection and also the session must go on or it must resume from theri as it was
 * earlier theri must be a less disturbance. the interview must not start from the starting."
 *
 * WHY THIS IS NOT JUST `navigator.onLine`. That flag answers a narrower question than it
 * looks: it is true whenever the device has a link, so a laptop attached to a wifi router
 * whose uplink is down reports `true` forever. On mobile it is worse — a train going through
 * a tunnel keeps the radio associated. Trusting it alone means the banner never appears in the
 * most common Indian campus failure mode, which is a working hotspot with no data left.
 *
 * So there are two signals and they are combined:
 *
 *   THE EVENTS are trusted only in one direction. `offline` firing means we are definitely
 *   offline — the OS knows the link dropped. `online` firing means only that the link is back,
 *   which is not the same as the backend being reachable, so it triggers a probe rather than
 *   clearing the warning.
 *
 *   THE CALLERS report what they observed. `reportFailure()` is called by request code that
 *   saw a network error, which is the only signal that catches the lying-`onLine` case, and
 *   `reportSuccess()` by anything that completed — a request that just succeeded is proof of
 *   reachability and outranks every heuristic.
 *
 * RECOVERY IS POLLED, AND ONLY WHILE DOWN. A heartbeat that runs when everything is fine is
 * pure cost — the interview already makes real requests constantly, and each one is a better
 * liveness check than a synthetic ping. The probe therefore starts when we believe we are
 * offline and stops the moment it succeeds.
 *
 * WHAT THIS HOOK DOES NOT DO is decide what to do about it. Holding the interview, pausing the
 * timer, keeping the microphone shut and re-fetching the current question are the page's
 * decisions, because only the page knows which of those are safe at that moment.
 */

/** Cheap, unauthenticated, and already exists. Same origin, so no preflight. */
const PROBE_URL = '/api/v1/health';

/**
 * How often to re-probe while down. Three seconds is a compromise: fast enough that a
 * candidate whose wifi blipped is not left staring at a warning after it recovered, slow
 * enough that a genuinely long outage does not spend the device's battery on it.
 */
const PROBE_INTERVAL_MS = 3_000;

/** A probe that hangs is a probe that never tells us anything. */
const PROBE_TIMEOUT_MS = 4_000;

export interface ConnectionState {
  /** Best current belief. Starts optimistic — see the note in the effect. */
  online: boolean;
  /** When we went offline, for "reconnecting for 12s" style copy. Null while online. */
  offlineSince: number | null;
  /** Call when a request fails for a reason that looks like the network. */
  reportFailure: () => void;
  /** Call when any request succeeds. Outranks every other signal. */
  reportSuccess: () => void;
}

/** Does this error look like a connection problem rather than a rejected request? */
export function isNetworkError(err: unknown): boolean {
  if (!err) return false;
  // An HTTP response — even a 500 — means the network worked. Only treat a request that never
  // got an answer as a connectivity problem, or a candidate whose session hit a server error
  // would be told to check their wifi.
  const status = (err as { status?: unknown }).status;
  if (typeof status === 'number' && status > 0) return false;
  const name = (err as { name?: unknown }).name;
  if (name === 'AbortError' || name === 'TimeoutError') return true;
  const message = String((err as { message?: unknown }).message ?? err).toLowerCase();
  return (
    message.includes('fetch') ||
    message.includes('network') ||
    message.includes('timeout') ||
    message.includes('connection') ||
    message.includes('offline')
  );
}

export function useConnection(): ConnectionState {
  /*
   * Optimistic initial value, deliberately. `navigator.onLine` is not available during SSR,
   * and starting `false` would flash an "internet lost" banner on every page load — a warning
   * that cries wolf on load is one candidates learn to ignore by the time it is real.
   */
  const [online, setOnline] = useState(true);
  const [offlineSince, setOfflineSince] = useState<number | null>(null);

  //: Mirrors `online` for use inside callbacks and intervals without making them depend on it
  //: — the probe interval must not be torn down and rebuilt on every state change.
  const onlineRef = useRef(true);

  const goOffline = useCallback(() => {
    if (!onlineRef.current) return;
    onlineRef.current = false;
    setOnline(false);
    setOfflineSince(Date.now());
  }, []);

  const goOnline = useCallback(() => {
    if (onlineRef.current) return;
    onlineRef.current = true;
    setOnline(true);
    setOfflineSince(null);
  }, []);

  const reportFailure = useCallback(() => {
    goOffline();
  }, [goOffline]);

  const reportSuccess = useCallback(() => {
    goOnline();
  }, [goOnline]);

  // Browser events. `offline` is trusted outright; `online` only starts a probe, because a
  // link is not a route to the backend.
  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (navigator.onLine === false) goOffline();

    const onOffline = () => goOffline();
    const onOnline = () => {
      // Do NOT clear the warning here. The probe below is already running and will clear it
      // once the backend actually answers, which is the claim the banner makes.
      void probe();
    };

    const probe = async () => {
      if (onlineRef.current) return;
      try {
        const ctrl = new AbortController();
        const timer = setTimeout(() => ctrl.abort(), PROBE_TIMEOUT_MS);
        // `cache: 'no-store'` matters: a cached 200 would report the backend reachable from
        // a device with no connection at all.
        const res = await fetch(PROBE_URL, {
          method: 'GET',
          cache: 'no-store',
          signal: ctrl.signal,
        });
        clearTimeout(timer);
        // Any answer at all proves reachability, including an unhealthy one — the question
        // here is "can we talk to the server", not "is the server well".
        if (res) goOnline();
      } catch {
        // Still down. The interval will try again.
      }
    };

    window.addEventListener('offline', onOffline);
    window.addEventListener('online', onOnline);
    // Also probe when the tab comes back to the foreground: a phone that slept through the
    // outage fires no events at all, and the candidate returning to the tab is exactly when
    // a stale banner is most confusing.
    const onVisible = () => {
      if (document.visibilityState === 'visible') void probe();
    };
    document.addEventListener('visibilitychange', onVisible);

    const interval = setInterval(() => void probe(), PROBE_INTERVAL_MS);

    return () => {
      window.removeEventListener('offline', onOffline);
      window.removeEventListener('online', onOnline);
      document.removeEventListener('visibilitychange', onVisible);
      clearInterval(interval);
    };
  }, [goOffline, goOnline]);

  return { online, offlineSince, reportFailure, reportSuccess };
}
