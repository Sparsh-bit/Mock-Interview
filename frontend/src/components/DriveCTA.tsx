'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ArrowRight, Target, X } from 'lucide-react';
import { useTracks } from '@/hooks/useData';
import {
  DRIVE_DISMISS_KEY,
  DRIVE_EYEBROW,
  driveDateLive,
  driveHref,
  driveTitle,
  findDriveTrack,
} from '@/lib/interview/drive';

/**
 * The one-click entry into the Cognizant Digital Nurture technical interview.
 *
 * WHY IT EXISTS. A student preparing for a named drive on a known date does not want a form
 * asking which of twenty-four companies they mean. They want the interview. This card is the
 * shortest honest path to it: one click lands on the setup page with the company, the program,
 * the technical/non-technical choice and the track already decided, and — when a resume is
 * already on file — with plan generation already under way.
 *
 * "HONEST" IS DOING WORK IN THAT SENTENCE. It is not a zero-click start, and it deliberately
 * is not. POST /api/v1/interview/plan calls `consume(db, user_id, "interview")` BEFORE it
 * generates anything, so every fire spends one of a free user's two interviews; and the server
 * does not require a resume, it just quietly falls back to the generic question set when there
 * is none. A card that promised "one click, straight in" would therefore, for a first-time user
 * with no resume uploaded, spend a paid interview on the worst version of the product. So the
 * link carries `autostart=1` as a request and the setup page decides — if the resume is there
 * it submits itself, and if it is not, the candidate lands on a fully pre-filled form with the
 * resume box explained and one field left to fill. For a returning student that is genuinely
 * one click. For a new one it is the correct two.
 *
 * WHY IT IS NOT A NEW ROUTE. /interview already reads search params, is already
 * Suspense-wrapped, and already carries `export const runtime = 'edge'` — which this project's
 * Cloudflare Pages build requires and has broken on before. A deep link into it needs no new
 * plumbing and cannot break a deploy.
 *
 * WHY IT LOOKS LIKE FeatureNudge. Because it is the same job: a dismissible full-width card at
 * the top of the dashboard pointing at one thing worth doing. Copying that component's shell
 * exactly — the flat indigo tint, the 11x11 icon tile, the uppercase eyebrow, the inline
 * primary link with a trailing arrow — means this is a second instance of an existing idiom
 * rather than a third card style on the same screen. Note the flat tint specifically: the
 * comment in FeatureNudge records that its gradient was REMOVED for being the only place in
 * the app where two hues blended, so re-introducing one here would undo that on purpose.
 */
export function DriveCTA() {
  const { data: tracks } = useTracks();

  /*
   * DISMISSAL AND THE DATE ARE BOTH READ AFTER MOUNT, NOT DURING RENDER.
   *
   * `localStorage` does not exist on the Cloudflare edge runtime and `Date.now()` there is a
   * different instant from `Date.now()` in the browser. Reading either during render makes the
   * server HTML and the first client render disagree, and React resolves that disagreement by
   * throwing away and re-rendering the subtree — which for a card like this shows up as a
   * flash, and for the dated headline specifically would only ever show up on the one day the
   * headline matters.
   *
   * `null` is the third state and it means "not yet known", which renders nothing. So the
   * sequence is: server emits nothing, first client paint emits nothing, then the effect
   * settles both facts and the card appears once, correct. There is no intermediate frame
   * showing a dismissed card or a stale date.
   */
  const [dismissed, setDismissed] = useState<boolean | null>(null);
  const [dateLive, setDateLive] = useState(false);

  useEffect(() => {
    // Wrapped because a browser with storage disabled (Safari private mode, some managed
    // school machines — a real part of this audience) throws on access rather than returning
    // null. Failing to read a dismissal must show the card, never crash the dashboard.
    let stored = false;
    try {
      stored = window.localStorage.getItem(DRIVE_DISMISS_KEY) === 'true';
    } catch {
      stored = false;
    }
    setDismissed(stored);
    setDateLive(driveDateLive(Date.now()));
  }, []);

  const track = findDriveTrack(tracks);

  // No track, no card. The tracks endpoint auto-seeds on first hit, so on a fresh database
  // this is null until something has asked for the list — and a link built on a missing track
  // would land on the setup page, fail the id check, and fall through to `tracks[0]`, which is
  // Accenture's "Advanced ASE". Rendering nothing is strictly better than rendering a card that
  // starts the wrong company's interview.
  if (!track) return null;
  if (dismissed !== false) return null;

  const dismiss = () => {
    try {
      window.localStorage.setItem(DRIVE_DISMISS_KEY, 'true');
    } catch {
      // Storage refused. The card still goes away for this session, which is what the click
      // asked for; it will simply come back next visit. Silently losing the click would be
      // worse than silently losing the preference.
    }
    setDismissed(true);
  };

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, height: 0 }}
        className="relative overflow-hidden rounded-2xl border border-accent-indigo/20 bg-accent-indigo-soft p-5"
      >
        <button
          onClick={dismiss}
          aria-label="Dismiss"
          className="absolute right-3 top-3 rounded-md p-1 text-muted-foreground transition-colors hover:bg-black/5 hover:text-foreground"
        >
          <X className="h-4 w-4" />
        </button>
        <div className="flex items-start gap-4 pr-6">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-accent-indigo text-white">
            {/* Target, matching /prepare — it is already this app's icon for "practice aimed
                at one named company" rather than practice in general. */}
            <Target className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-accent-indigo-ink">
              {DRIVE_EYEBROW}
            </p>
            <h3 className="mt-1 text-base font-semibold">{driveTitle(dateLive)}</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              The real technical round: Java and OOP cross-questions, React, SQL, Spring Boot
              and REST, code explained aloud, then your project and HR. Freshly written
              questions every time — never a repeat of the last run.
            </p>
            <Link
              href={driveHref(track)}
              className="mt-3 inline-flex items-center gap-1.5 text-sm font-semibold text-primary transition-opacity hover:opacity-80"
            >
              Start the mock interview <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
