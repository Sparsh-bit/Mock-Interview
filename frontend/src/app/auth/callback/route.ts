import { NextResponse, type NextRequest } from 'next/server';
import { safeRedirect } from '@/lib/auth/safe-redirect';
import { createClient } from '@/lib/supabase/server';

export const runtime = 'edge';

// Handles Supabase auth redirects — the password-reset link, and the signup
// confirmation, which arrives as `?next=/welcome` so a new account lands in the
// onboarding wizard. Exchanges the code for a session, then forwards.
export async function GET(request: NextRequest) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get('code');
  /*
   * THROUGH `safeRedirect`, BECAUSE `${origin}${next}` WAS AN OPEN REDIRECT.
   *
   * `next` came straight off the query string and was concatenated onto the origin. Most of
   * the obvious payloads are harmless here — `//evil.com` and `/\evil.com` both normalise to
   * a same-origin path once the origin is in front of them — but `?next=@evil.com` produces
   * `<our-origin>@evil.com`, where everything before the `@` is parsed as userinfo and the
   * browser navigates to the host after it.
   *
   * That is the same vulnerability `lib/auth/safe-redirect.ts` was written to close on the
   * login form, on a route that never called it: the victim clicks a link in a real email
   * from us, lands on our real domain, and is handed somewhere else with a live session. The
   * module already existed — this route just was not using it.
   *
   * The `?? '/settings'` default is preserved for a link with no `next` at all (the original
   * password-reset shape); only a supplied value is now sanitised.
   */
  const next = safeRedirect(searchParams.get('next') ?? '/settings');

  if (code) {
    const supabase = await createClient();
    const { error } = await supabase.auth.exchangeCodeForSession(code);

    if (!error) {
      return NextResponse.redirect(`${origin}${next}`);
    }
  }

  return NextResponse.redirect(`${origin}/settings`);
}
