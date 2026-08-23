'use client';

import { useEffect, useRef, useState } from 'react';

/**
 * Warn a candidate before they abandon a live interview — hooks/useLeaveGuard.ts
 *
 * An interview in progress cannot be resumed and the attempt is already spent, so closing the
 * tab, reloading, or wandering off to another app costs the candidate the whole thing. Most
 * people who do it have no idea — they switch away to look something up, or reload because a
 * question is taking a few seconds and the page looks stuck.
 *
 * THREE DIFFERENT EVENTS, BECAUSE THEY ARE THREE DIFFERENT MISTAKES and only one of them can
 * be intercepted:
 *
 *   CLOSING OR RELOADING — `beforeunload`. The browser shows its own confirmation and there is
 *   no way to supply the wording: Chrome and Safari deliberately ignore any custom string,
 *   because sites abused it. So this cannot explain what is at stake; it can only make the
 *   action deliberate. That is still the single most valuable of the three, because it is the
 *   only one that can actually stop the loss.
 *
 *   SWITCHING TAB OR APP — `visibilitychange`. Nothing can be prevented here and no dialog is
 *   allowed, so the honest thing is to notice and tell them when they come BACK. Blocking is
 *   not on the table; the interview kept running while they were gone.
 *
 *   IN-APP NAVIGATION — a link to another page. `beforeunload` does NOT fire for a client-side
 *   route change, which is the trap: the guard looks like it covers everything and silently
 *   misses the case where the candidate clicks something in our own UI. Handled by the caller
 *   confirming before it navigates, which is why `armed` is exposed.
 *
 * IT DOES NOT TRY TO BLOCK ANYTHING IT CANNOT BLOCK. No fake modal over a tab switch, no
 * pretending a dialog stopped a reload it did not. Each event gets the strongest honest
 * response available to it, and the copy is the caller's job — this hook owns the events and
 * the counting, not the words.
 */
export interface LeaveGuard {
  /** True while the guard is active, for a caller that wants to confirm its own navigation. */
  armed: boolean;
  /** How many times they have left and come back. Zero until it happens. */
  awayCount: number;
  /** True from the moment they first switch away, so a warning can persist rather than flash. */
  hasLeft: boolean;
  /** Dismiss the warning without disarming the guard. */
  acknowledge: () => void;
}

export function useLeaveGuard(active: boolean): LeaveGuard {
  const [awayCount, setAwayCount] = useState(0);
  const [hasLeft, setHasLeft] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  // A ref as well as state, because the visibility handler is registered once and would
  // otherwise close over a stale `active`.
  const activeRef = useRef(active);
  activeRef.current = active;

  useEffect(() => {
    if (!active) return;

    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      // BOTH FORMS ON PURPOSE. `preventDefault()` is the modern spec; assigning `returnValue`
      // is what older Safari and Firefox still require. Setting only one leaves the prompt
      // missing on some browsers, and the browsers where it goes missing are exactly the ones
      // this product's users are on.
      e.preventDefault();
      e.returnValue = '';
      return '';
    };

    const onVisibility = () => {
      if (!activeRef.current) return;
      if (document.visibilityState === 'hidden') {
        setHasLeft(true);
        setAwayCount((n) => n + 1);
        // Re-shown on every departure: somebody who dismissed it once and left again has
        // demonstrated they did not take it in.
        setAcknowledged(false);
      }
    };

    window.addEventListener('beforeunload', onBeforeUnload);
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      window.removeEventListener('beforeunload', onBeforeUnload);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [active]);

  return {
    armed: active,
    awayCount,
    hasLeft: hasLeft && !acknowledged,
    acknowledge: () => setAcknowledged(true),
  };
}

export default useLeaveGuard;
