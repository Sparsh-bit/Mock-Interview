import type { MetadataRoute } from 'next';

import { siteUrl } from '@/lib/seo/site-url';

/**
 * robots.txt, generated rather than hand-written — app/robots.ts
 *
 * THERE WAS NO robots.txt AT ALL, so nothing told a crawler where the sitemap was or which
 * paths only ever redirect. Next builds this file from the export below, so there is no static
 * copy to drift from the routes it describes.
 *
 * THE DISALLOW LIST IS NOT A SECURITY CONTROL and must never be mistaken for one — `middleware.ts`
 * redirects unauthenticated requests, and that is the enforcement. This exists for two duller
 * reasons: a crawler otherwise spends its budget on paths that answer with a redirect to the
 * login page, and the login page itself gets indexed as thin content under a dozen URLs that
 * all render the same thing.
 *
 * `/r/` IS ALREADY noindex VIA METADATA (see app/r/layout.tsx) and is listed here as well.
 * Belt and braces on purpose: those are shared interview reports, which carry a candidate's
 * name and scores, and a `noindex` tag only works if the page is fetched and parsed.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: '*',
      allow: '/',
      disallow: [
        '/api/',
        '/dashboard',
        /* The onboarding wizard. Nothing on it is public and an indexed /welcome would rank
           for the brand name above the landing page it is meant to follow. */
        '/welcome',
        '/settings',
        '/profile',
        '/achievements',
        '/analytics',
        '/ai-usage',
        '/admin',
        '/interview',
        '/prepare',
        '/quiz',
        '/tracks',
        '/session',
        '/report',
        '/account',
        // Shared reports: a candidate's name and scores live under here.
        '/r/',
        // Auth screens. Indexing a login form gains nothing and splits the brand query.
        '/login',
        '/register',
        '/forgot-password',
        '/reset-password',
        '/auth/',
      ],
    },
    sitemap: `${siteUrl()}/sitemap.xml`,
  };
}
