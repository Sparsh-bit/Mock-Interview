'use client';

import { useQuery } from '@tanstack/react-query';
import { getBrowserApiClient } from '@/lib/api';

export type ActivityType = 'interview' | 'group_discussion' | 'communication' | 'quiz';

export interface ActivityItem {
  id: string;
  activity_type: ActivityType;
  title: string;
  score: number;
  details: Record<string, unknown> | null;
  created_at: string;
}

/**
 * Unified history feed — every activity the candidate has completed
 * (interviews, group discussions, communication rounds, quizzes), newest first.
 */
export function useActivity(limit = 100) {
  return useQuery({
    queryKey: ['activity', limit],
    queryFn: async () => {
      const res = await getBrowserApiClient().get(`/api/v1/reports/activity/all?limit=${limit}`);
      return res.data as ActivityItem[];
    },
    staleTime: 30 * 1000,
  });
}
