import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

/** Merges class names and resolves conflicting Tailwind utilities (e.g. `px-2` + `px-4` -> `px-4`). */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

export function formatDuration(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;
  
  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m ${secs}s`;
  return `${secs}s`;
}

/*
 * FIVE SCORE HELPERS USED TO LIVE HERE — `formatScore`, `getScoreLabel`, `getScoreColor` and
 * `getReadinessLabel`. All four are gone, and none of them had a single caller anywhere in the
 * app.
 *
 * They were not harmless. `getScoreLabel` banded at the backend's own 85/70/55/40 but returned
 * "Average" and "Poor" where the backend returns "Satisfactory" and "Significant Gaps";
 * `getScoreColor` put 70+ in indigo where lib/score-bands puts it in teal. So this was a FIFTH
 * answer to "what does this score mean" — with the right numbers and the wrong words — sitting
 * in the most-imported module in the codebase, one autocomplete away from being used.
 *
 * Dead code that disagrees with live code is worse than dead code: the next person to need a
 * score label finds this first, it looks authoritative because it is in `utils`, and the
 * product acquires a sixth vocabulary.
 *
 * lib/score-bands.ts is the only answer. `getReadinessLabel` went with them — READINESS_META in
 * the report page is the live copy, and two of those is how the last set of these started.
 */


export function getReadinessColor(level: string): string {
  if (level === 'interview_ready') return 'text-accent-emerald-ink';
  if (level === 'close_to_ready') return 'text-accent-amber-ink';
  if (level === 'significant_gaps') return 'text-accent-coral-ink';
  return 'text-accent-amber-ink';
}
