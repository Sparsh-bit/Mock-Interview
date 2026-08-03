import { useMemo } from 'react';

import { useAuth } from '@/hooks/useAuth';
import { useUserProfile } from '@/hooks/useData';

/**
 * Who the candidate is, by name — hooks/useCandidateName.ts
 *
 * Every surface that addresses the user by name needs the same answer, and there
 * are three places a name can come from with a real order of authority:
 *
 *   1. the profile they filled in on this app (they chose it deliberately)
 *   2. the name Supabase captured at signup (Google/GitHub give one; email may not)
 *   3. the local part of their email (a last resort — "sparsh.sharma" is still
 *      better than "candidate")
 *
 * Centralised because a GD panelist calling you "Sparsh" while the dashboard
 * greets "sparsh.sharma22" is the kind of seam that makes a product feel assembled
 * rather than built. It also means one place decides what happens when a user has
 * given no name at all.
 */
export interface CandidateName {
  /** The best full name available, or '' when nothing usable exists. */
  full: string;
  /**
   * What a person would actually call them out loud — the first word, letters
   * only. "Sparsh", not "Sparsh Sharma"; "Priya", not "priya.k_2024".
   */
  first: string;
  /** For greetings, where a name is optional: falls back to 'there'. */
  greeting: string;
}

/** Strip an email-shaped or punctuated name down to something speakable. Exported for tests. */
export function speakableFirstWord(raw: string): string {
  const first = raw.trim().split(/[\s._\-+]+/)[0] ?? '';
  const letters = first.replace(/[^A-Za-z]/g, '');
  if (letters.length < 2) return '';
  // "sparsh" → "Sparsh". Names typed in lowercase are common and read as sloppy
  // when a panelist says them back; names already capitalised are left alone.
  return letters[0].toUpperCase() + letters.slice(1);
}

export function useCandidateName(): CandidateName {
  const { user } = useAuth();
  // The profile request is shared with the rest of the app through TanStack Query,
  // so reading it here costs nothing extra. While it is in flight the auth
  // metadata answers, which is why the fallback chain matters rather than a
  // loading state — a panelist must not wait on a name lookup to start talking.
  const { data: profile } = useUserProfile();

  return useMemo(() => {
    const meta = (user?.user_metadata ?? {}) as { full_name?: string; name?: string };
    const full = (
      profile?.full_name ||
      meta.full_name ||
      meta.name ||
      user?.email?.split('@')[0] ||
      ''
    ).trim();
    const first = speakableFirstWord(full);
    return { full, first, greeting: first || 'there' };
  }, [profile?.full_name, user]);
}
