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

export function getScoreColor(score: number): string {
  if (score >= 85) return 'text-emerald-400';
  if (score >= 70) return 'text-blue-400';
  if (score >= 55) return 'text-yellow-400';
  if (score >= 40) return 'text-orange-400';
  return 'text-red-400';
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
  if (level === 'interview_ready') return 'text-emerald-400';
  if (level === 'close_to_ready') return 'text-yellow-400';
  if (level === 'significant_gaps') return 'text-red-400';
  return 'text-orange-400';
}
