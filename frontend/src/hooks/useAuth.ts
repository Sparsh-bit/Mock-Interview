'use client';

import { createClient } from '@/lib/supabase/client';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import type { User, Session } from '@supabase/supabase-js';

interface AuthState {
  user: User | null;
  session: Session | null;
  loading: boolean;
}

export function useAuth() {
  const [state, setState] = useState<AuthState>({
    user: null,
    session: null,
    loading: true,
  });
  const router = useRouter();
  const supabase = createClient();

  useEffect(() => {
    // Get initial session
    supabase.auth.getSession().then(({ data: { session } }) => {
      setState({
        user: session?.user ?? null,
        session,
        loading: false,
      });
    });

    // Listen for auth changes
    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      (_event, session) => {
        setState({
          user: session?.user ?? null,
          session,
          loading: false,
        });
        router.refresh();
      }
    );

    return () => subscription.unsubscribe();
    // Intentionally mount-once: `supabase` is a fresh client each render (not
    // memoized) and `router` is stable per Next.js App Router guarantees, so
    // neither belongs in this dependency array without re-subscribing on
    // every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const signIn = async (email: string, password: string) => {
    const { data, error } = await supabase.auth.signInWithPassword({ email, password });
    return { data, error };
  };

  /*
   * `emailRedirectTo` IS WHAT MAKES THE WIZARD A SIGNUP-ONLY STEP.
   *
   * The confirmation link is the only moment in the system that knows for certain it is
   * carrying a brand-new account, so it is the only honest place to decide that this person
   * should see onboarding. Everywhere else has to infer it, and the inference the app used to
   * make — "send everyone to /welcome, it forwards on if setup looks done" — treated an
   * unfinished setup as a new user and re-ran all four steps on every login forever.
   *
   * Same `/auth/callback?next=…` shape `resetPassword` below already uses, so there is one
   * redirect route to keep allowlisted rather than two.
   *
   * IF THE URL IS NOT ALLOWLISTED in the Supabase dashboard, Supabase silently falls back to
   * the project's Site URL and the new account lands on the landing page instead of the
   * wizard. That degrades to "no onboarding", not to a broken signup — but it is worth
   * checking the dashboard lists this path, because the failure is invisible from here.
   */
  const signUp = async (email: string, password: string, metadata?: { full_name?: string }) => {
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        data: metadata,
        emailRedirectTo: `${window.location.origin}/auth/callback?next=/welcome`,
      },
    });
    return { data, error };
  };

  const signOut = async () => {
    await supabase.auth.signOut();
    router.push('/');
  };

  const resetPassword = async (email: string) => {
    return supabase.auth.resetPasswordForEmail(email, {
      redirectTo: `${window.location.origin}/auth/callback?next=/reset-password`,
    });
  };

  return {
    user: state.user,
    session: state.session,
    loading: state.loading,
    isAuthenticated: !!state.user,
    signIn,
    signUp,
    signOut,
    resetPassword,
  };
}
