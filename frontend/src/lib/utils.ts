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

export function formatScore(score: number): string {
  return `${score.toFixed(1)}/10`;
}

export function getScoreLabel(score: number): string {
  if (score >= 85) return 'Excellent';
  if (score >= 70) return 'Good';
  if (score >= 55) return 'Average';
  if (score >= 40) return 'Needs Improvement';
  return 'Poor';
}

/**
 * Five score bands, five distinguishable colours.
 *
 * The bands used to be emerald / blue / amber / orange / red. Amber and orange
 * are 20° apart and both collapsed onto the same semantic amber, which silently
 * merged "Average" and "Needs Improvement" — the two bands a candidate most
 * needs to tell apart.
 *
 * The step between them is `amber-hot`, a burnt orange that is a fourth TONE of
 * amber rather than a seventh colour in the system. The obvious alternative,
 * plain `accent-coral`, measures 4.19:1 on the paper ground and fails AA at
 * this size; amber-hot is 5.0:1.
 */
export function getScoreColor(score: number): string {
  if (score >= 85) return 'text-accent-emerald-ink';
  if (score >= 70) return 'text-accent-indigo-ink';
  if (score >= 55) return 'text-accent-amber-ink';
  if (score >= 40) return 'text-accent-amber-hot';
  return 'text-accent-coral-ink';
}

export function getReadinessLabel(level: string): string {
  const labels: Record<string, string> = {
    interview_ready: 'Interview Ready',
    close_to_ready: 'Close to Ready',
    needs_more_practice: 'Needs More Practice',
    significant_gaps: 'Significant Gaps',
  };
  return labels[level] || level;
}

export function getReadinessColor(level: string): string {
  if (level === 'interview_ready') return 'text-accent-emerald-ink';
  if (level === 'close_to_ready') return 'text-accent-amber-ink';
  if (level === 'significant_gaps') return 'text-accent-coral-ink';
  return 'text-accent-amber-ink';
}
