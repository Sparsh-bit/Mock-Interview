// Utility functions
export function cn(...inputs: (string | undefined | null | boolean | Record<string, boolean>)[]): string {
  const classes: string[] = [];
  
  for (const input of inputs) {
    if (!input) continue;
    if (typeof input === 'string') {
      classes.push(input);
    } else if (typeof input === 'object') {
      for (const [key, value] of Object.entries(input)) {
        if (value) classes.push(key);
      }
    }
  }
  
  return classes.join(' ');
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

export function getHireRecommendationLabel(rec: string): string {
  const labels: Record<string, string> = {
    strong_hire: '✅ Strong Hire',
    hire: '✅ Hire',
    borderline: '⚠️ Borderline',
    no_hire_currently: '❌ No Hire Currently',
    no_hire: '❌ No Hire',
  };
  return labels[rec] || rec;
}

export function getHireRecommendationColor(rec: string): string {
  if (rec === 'strong_hire' || rec === 'hire') return 'text-emerald-400';
  if (rec === 'borderline') return 'text-yellow-400';
  return 'text-red-400';
}
