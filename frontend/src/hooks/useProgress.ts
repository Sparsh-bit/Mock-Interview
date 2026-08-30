'use client';

import { useQuery } from '@tanstack/react-query';

import { getBrowserApiClient } from '@/lib/api/browser';

/**
 * What the candidate has actually built — hooks/useProgress.ts
 *
 * ONE READ for the streak, the milestones, where they left off and what their next round will
 * open at. The shapes mirror `backend/app/api/v1/progress.py` exactly, and that file carries
 * the reasoning for all of it — in particular, why the re-engagement channel is this endpoint
 * and not an email.
 *
 * NOTHING HERE IS PUSHED. Every field is read by a page the candidate chose to open. There is
 * no notification, no badge count, no background poll and no timer, and that is a deliberate
 * product position rather than an unfinished one: `docs/COMPLIANCE.md` records that this
 * product cannot reliably tell it is not talking to a minor, and DPDP §9 prohibits behavioural
 * targeting of children. A pull surface is the shape where being wrong about that costs
 * somebody a sentence they did not need to read.
 */

export interface StreakInfo {
  days: number;
  practised_today: boolean;
  best: number;
  /** The zone the days were counted in — shown if a candidate disputes the number. */
  timezone: string;
  /**
   * A live streak that today has not yet extended.
   *
   * STATED, NEVER COUNTED DOWN. This is the field most likely to be turned into a timer or a
   * red banner, and it must be neither. It exists so a page can say something true to somebody
   * who is already looking at it.
   */
  at_risk: boolean;
}

export interface MilestoneInfo {
  key: string;
  name: string;
  /** What earning it claims about the candidate — capability, never a count. */
  claim: string;
  /** What it takes, readable BEFORE it is earned. That is what makes it a goal. */
  requirement: string;
  earned: boolean;
  /** 0–1. Honest partial credit rather than a binary that reads as nothing happening. */
  fraction: number;
}

export interface ResumeInfo {
  session_id: string;
  questions_answered: number;
  hours_ago: number;
}

export interface ProgressInfo {
  streak: StreakInfo;
  rating: number;
  rank: string;
  next_rank: string | null;
  rank_fraction: number;
  milestones: MilestoneInfo[];
  resume: ResumeInfo | null;
  /** easy | medium | hard — where the next round opens, given what they have proven. */
  opens_at: string;
}

export function useProgress(enabled = true) {
  return useQuery({
    queryKey: ['progress', 'me'],
    queryFn: async (): Promise<ProgressInfo> => {
      const res = await getBrowserApiClient().get('/api/v1/progress/me');
      return res.data as ProgressInfo;
    },
    enabled,
    /*
     * A MINUTE, AND NO REFETCH ON FOCUS.
     *
     * Refetching whenever the tab regains focus would make the streak flicker and update while
     * somebody is looking at it, which is the visual language of a live counter — the thing
     * this is deliberately not. None of these numbers can change without the candidate having
     * finished a round, and finishing a round already invalidates this cache.
     */
    staleTime: 60_000,
    refetchOnWindowFocus: false,
    retry: 1,
  });
}
