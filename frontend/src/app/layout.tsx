import type { Metadata, Viewport } from 'next';

import { siteUrl } from '@/lib/seo/site-url';
import { BRAND } from '@/lib/brand';
import { Inter, JetBrains_Mono } from 'next/font/google';
import './globals.css';
/*
 * Imported AFTER globals.css and never before it. Everything in marketing.css is plain CSS at
 * the same specificity as a Tailwind utility, so source order is the whole tie-break: load it
 * first and `.mk-btn`'s background loses to any `bg-*` class that happens to be on the same
 * element, which is a bug that only shows up on the two or three controls that carry both.
 */
import './fonts.css';
import './marketing.css';
import { Providers } from '@/components/providers';
import { Toaster } from 'sonner';

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-inter',
  display: 'swap',
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  variable: '--font-jetbrains-mono',
  display: 'swap',
});

/*
 * THE MARKETING FACES ARE NOT HERE. Fraunces and DM Sans are declared as `@font-face` in
 * `app/fonts.css` and served from `public/fonts/`, for the reasons that file sets out — the
 * short version being that a build which needs the network to end up with the right typeface
 * will one day not have it. Inter and JetBrains Mono stay on `next/font/google` because they
 * are already there and moving them would be churn for no gain.
 */

export const metadata: Metadata = {
  title: {
    /*
     * "AI-Powered Mock Interviews" was the exact shape DESIGN-RULES bans — adjective-noun-AI,
     * which says nothing and appears on every generated landing page since 2023. The tagline
     * says what the product does instead, and it is the same line the mark carries.
     */
    default: `${BRAND.name} — ${BRAND.tagline}`,
    template: `%s · ${BRAND.name}`,
  },
  description: BRAND.promise,
  keywords: [
    'mock interview',
    'technical interview',
    'Cognizant Digital Nurture',
    'Java interview practice',
    'AI interview simulator',
    'coding interview prep',
  ],
  authors: [{ name: BRAND.name }],
  creator: BRAND.name,
  /*
   * THE HOST EVERY ABSOLUTE URL IS BUILT FROM — canonical, OpenGraph, Twitter.
   *
   * This read NEXT_PUBLIC_APP_URL directly, which is the DEPLOYMENT url. In production that was
   * the Cloudflare Pages subdomain while the site people visit is a custom domain, so every
   * canonical and every share card named `*.pages.dev`. Two hosts serving identical content with
   * no canonical signal is the textbook duplicate-content split.
   *
   * `siteUrl()` prefers NEXT_PUBLIC_SITE_URL — the canonical identity of the site, which is a
   * product decision rather than a property of where the build ran — and falls back to the
   * deployment URL so preview builds link to themselves.
   */
  metadataBase: new URL(siteUrl()),
  // Self-referencing canonical on the root. Relative, so metadataBase resolves it; per-page
  // metadata can override it, and the pages that need to already do.
  alternates: { canonical: '/' },
  openGraph: {
    type: 'website',
    locale: 'en_US',
    url: 'https://interviewos.dev',
    title: `${BRAND.name} — ${BRAND.tagline}`,
    description: BRAND.promise,
    siteName: BRAND.name,
  },
  twitter: {
    card: 'summary_large_image',
    title: `${BRAND.name} — ${BRAND.tagline}`,
    // "land your dream offer" was a phrase, not a claim. This one is checkable.
    description:
      'Practise against a panel that sounds like the one you are about to face, then read what they would have said about you.',
  },
  robots: { index: true, follow: true },
};

export const viewport: Viewport = {
  /*
   * A REAL BUG, not a restyle. These two lines still described the dark theme the product had
   * before the retheme to warm paper, and both are things the BROWSER acts on rather than the
   * page:
   *
   *   `themeColor` paints the address bar and the task-switcher card on Android Chrome. A
   *   near-black bar sat directly above a #F9F6F0 page — the join looked like a rendering
   *   fault, on the surface a candidate sees before anything else has loaded.
   *
   *   `colorScheme: 'dark'` is stronger and worse: it tells the engine to render form controls,
   *   scrollbars and the canvas under the page in its dark palette. Native selects, date
   *   inputs and the scrollbar were dark-on-light, and on a slow connection the page flashed
   *   a dark ground before the CSS arrived.
   *
   * #FBF6EC is `--background` (40 65.2% 95.5%) converted to hex. It has to be a literal — this
   * object is read at build time and cannot resolve a CSS custom property — so if the ground
   * is ever retoned, retone this with it.
   */
  themeColor: '#FBF6EC',
  colorScheme: 'light',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${jetbrainsMono.variable}`}
      suppressHydrationWarning
    >
      <body className="min-h-screen bg-background font-sans antialiased">
        <Providers>
          {children}
          <Toaster
                        position="bottom-right"
            toastOptions={{
              style: {
                background: 'hsl(222 14% 8%)',
                border: '1px solid hsl(217 19% 17%)',
                color: 'hsl(210 40% 96%)',
              },
            }}
          />
        </Providers>
      </body>
    </html>
  );
}
