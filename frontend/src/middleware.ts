import { NextResponse, type NextRequest } from 'next/server';
import { createServerClient, type SetAllCookies } from '@supabase/ssr';

/**
 * Everything that needs a session.
 *
 * THIS LIST WAS INCOMPLETE, and the omissions were the interesting ones: `/admin` and
 * `/ai-usage` were not on it. In practice the dashboard layout redirects an anonymous
 * visitor anyway, so nothing was ever exposed — but the middleware is the cheap edge gate
 * that runs before any server render, and a protected-routes list that does not include the
 * admin console is one refactor away from being the only gate that mattered.
 *
 * Enumerated rather than expressed as "everything except the public ones", because the
 * failure directions are not symmetric: forgetting to add a route here leaves it guarded by
 * the layout, while forgetting to add one to a public list would lock users out of the
 * landing page.
 */
const PROTECTED_ROUTES = [
  '/dashboard',
  /* The post-signup wizard. Protected for the same reason every other route here is — it
     reads and writes the account's profile — and listed before '/dashboard' has any effect
     because `isProtected` is a prefix match over the whole array. */
  '/welcome',
  '/interview',
  '/session',
  '/report',
  '/profile',
  '/settings',
  '/prepare',
  '/practice',
  '/quiz',
  '/gd',
  '/communication',
  '/analytics',
  '/tracks',
  '/achievements',
  // Admin console and the temporary cost view. Both are independently gated server-side by
  // the AdminUser dependency; this only stops a logged-out visitor rendering the shell.
  '/admin',
  '/ai-usage',
  // Receipts. Needs a session to know whose payment to render.
  '/account',
];
const AUTH_ROUTES = ['/login', '/register', '/forgot-password'];
/**
 * Reachable with no session at all.
 *
 * `/pricing` is deliberate: requiring an account to see what something costs is the one
 * place where auth actively loses the sale. `/r` is a shared report, gated on the owner
 * having published it plus an unguessable id.
 */
const PUBLIC_ROUTES = ['/', '/demo', '/pricing', '/r'];

function isProtected(pathname: string): boolean {
  return PROTECTED_ROUTES.some((route) => pathname.startsWith(route));
}

function isAuthRoute(pathname: string): boolean {
  return AUTH_ROUTES.some((route) => pathname.startsWith(route));
}

export async function middleware(request: NextRequest) {
  let supabaseResponse = NextResponse.next({ request });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        // Typed from the library — see the note in lib/supabase/server.ts.
        setAll(cookiesToSet: Parameters<SetAllCookies>[0]) {
          cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value));
          supabaseResponse = NextResponse.next({ request });
          cookiesToSet.forEach(({ name, value, options }) =>
            supabaseResponse.cookies.set(name, value, options)
          );
        },
      },
    }
  );

  const {
    data: { user },
  } = await supabase.auth.getUser();

  const { pathname } = request.nextUrl;

  // Redirect unauthenticated users trying to access protected routes
  if (!user && isProtected(pathname)) {
    const loginUrl = new URL('/login', request.url);
    loginUrl.searchParams.set('redirectTo', pathname);
    return NextResponse.redirect(loginUrl);
  }

  /*
   * Redirect authenticated users away from auth routes.
   *
   * THE LANDING PAD IS `/welcome`, NOT `/dashboard`. This used to send every authenticated
   * visitor straight to a dashboard of zeros, which for a brand-new account is three dead
   * ends in a row: no resume (so the interview form's submit is disabled), no target company
   * (so the study plan is unpersonalised), and no interview credit (so the front door is a
   * 402). `/welcome` fixes all three and then redirects here itself the moment setup is done
   * or the visitor has skipped it — so for an established account this costs one client-side
   * redirect and nothing else, and there is no `onboarding_completed` flag to drift out of
   * sync with the data it claims to describe.
   */
  if (user && isAuthRoute(pathname)) {
    return NextResponse.redirect(new URL('/welcome', request.url));
  }

  return supabaseResponse;
}

export const config = {
  matcher: [
    /*
     * Match all request paths except:
     * - _next/static (static files)
     * - _next/image (image optimization)
     * - favicon.ico, robots.txt, sitemap.xml
     * - Public media files
     */
    '/((?!_next/static|_next/image|favicon\\.ico|robots\\.txt|sitemap\\.xml|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|css|js)$).*)',
  ],
};
