import type { NextConfig } from 'next';

/**
 * Origins the browser is allowed to talk to, for `connect-src`.
 *
 * Derived rather than hardcoded, because the API and Supabase origins differ between local,
 * preview and production — a hardcoded list would either be wrong in production or force
 * `connect-src *`, which is the same as having no rule. Anything that fails to parse is
 * dropped rather than throwing: a malformed env var must not take the build down.
 */
function connectOrigins(): string[] {
  const raw = [
    process.env.NEXT_PUBLIC_API_URL,
    process.env.NEXT_PUBLIC_SUPABASE_URL,
    process.env.NEXT_PUBLIC_APP_URL,
  ];
  const origins = new Set<string>(["'self'"]);
  for (const value of raw) {
    if (!value) continue;
    try {
      origins.add(new URL(value).origin);
    } catch {
      // Not a URL. Skip it.
    }
  }
  // Supabase Realtime and Storage use wss:// and a per-project subdomain, and the anon key
  // is designed to be used from the browser, so the project's own wildcard is required for
  // auth to work at all under a restrictive policy.
  origins.add('https://*.supabase.co');
  origins.add('wss://*.supabase.co');
  return [...origins];
}

const nextConfig: NextConfig = {
  /*
   * NOTHING ABOUT THE SERVER IN THE RESPONSE. `X-Powered-By: Next.js` names the framework and
   * therefore the CVE list worth trying. Free to remove, and the first thing a scanner reads.
   */
  poweredByHeader: false,

  /*
   * NO BROWSER SOURCE MAPS IN PRODUCTION.
   *
   * This is Next's default, and it is set explicitly because the default is the kind that gets
   * flipped on during a debugging session and left on. With maps shipped, the whole frontend is
   * readable as original TypeScript — variable names, comments and all — which is the concrete,
   * fixable part of "no one can inspect and see how it is made".
   *
   * What it does NOT do is make the frontend unreadable. Minified JavaScript is still
   * JavaScript, it is on the user's machine because it has to run there, and it can be read.
   * The protection that actually holds is architectural and already in place: the prompts, the
   * question banks, the scoring, the plan builder and the billing rules all live in the
   * backend, so what the browser holds is a rendering layer with no proprietary logic in it.
   */
  productionBrowserSourceMaps: false,

  // Emit the build to the REPO ROOT (../.next) rather than frontend/.next.
  //
  // @cloudflare/next-on-pages resolves two things relative to its own cwd: the
  // build directory, and the asset paths recorded by `vercel build`. In an npm
  // workspace those disagree — Vercel records `frontend/.next/...` (relative to
  // the monorepo root) while the adapter runs in `frontend/`, so it looks for
  // `frontend/frontend/.next/...` and dies copying the edge-runtime wasm.
  // Building from the root with the output at the root makes both agree.
  distDir: process.env.NEXT_DIST_ROOT === '1' ? '../.next' : '.next',
  // Enable React strict mode for better development warnings
  reactStrictMode: true,

  images: {
    // Cloudflare Pages via @cloudflare/next-on-pages has no Next image
    // optimizer behind it, so the /_next/image endpoint cannot resize or
    // re-encode anything — it serves the original bytes, or 500s. Saying so
    // explicitly means <Image> emits a plain <img> with the right width/height
    // and lazy-loading instead of routing through an endpoint that isn't there.
    // The landing photography is therefore pre-encoded; see Photo.tsx.
    unoptimized: true,
    remotePatterns: [
      {
        protocol: 'https',
        hostname: '*.supabase.co',
        pathname: '/storage/v1/object/public/**',
      },
      {
        protocol: 'https',
        hostname: 'lh3.googleusercontent.com', // Google OAuth avatars
      },
      {
        protocol: 'https',
        hostname: 'avatars.githubusercontent.com', // GitHub avatars
      },
    ],
  },

  // Experimental features
  experimental: {
    // Optimize package imports for performance
    optimizePackageImports: ['framer-motion', 'lucide-react', 'recharts'],
  },

  // Environment variables exposed to the client
  // Only NEXT_PUBLIC_ prefix variables are exposed
  env: {
    APP_VERSION: process.env.npm_package_version || '0.1.0',
  },

  // Rewrites for API proxy in development
  // In production, the backend is deployed separately
  async rewrites() {
    const backendUrl = process.env.INTERNAL_API_URL || process.env.NEXT_PUBLIC_API_URL;
    if (!backendUrl) return [];

    return [
      {
        source: '/api/v1/:path*',
        destination: `${backendUrl}/api/v1/:path*`,
      },
    ];
  },

  // Security headers
  async headers() {
    return [
      {
        source: '/(.*)',
        headers: [
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'X-XSS-Protection', value: '1; mode=block' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          {
            // Allow camera + mic for our own origin (needed for the live
            // presence check and voice answers). An empty allowlist —
            // camera=() — disables it for everyone including self, which
            // silently blocks getUserMedia before any app code runs.
            key: 'Permissions-Policy',
            value: 'camera=(self), microphone=(self), geolocation=()',
          },
          {
            /*
             * HSTS. Without it, the first request of a session can still be plain HTTP and is
             * strippable on a hostile network — campus wifi being exactly the network this
             * product runs on. Two years, subdomains included, and preload-eligible.
             *
             * Only meaningful over HTTPS; browsers ignore it on http://localhost, so it is
             * safe to send unconditionally.
             */
            key: 'Strict-Transport-Security',
            value: 'max-age=63072000; includeSubDomains; preload',
          },
          {
            /*
             * CSP — the one header that turns an injected script into a blocked request.
             *
             * `'unsafe-inline'` on script-src is a real and deliberate concession: the App
             * Router emits inline bootstrap scripts, and the alternative is per-request nonces
             * threaded through middleware, which is a larger change than belongs in a hardening
             * pass. It costs the inline-XSS protection and KEEPS the part that matters most
             * here — an injected `<script src="https://attacker/…">` is still refused, because
             * the host is not in the allowlist.
             *
             * `frame-ancestors 'none'` duplicates X-Frame-Options on purpose: the older header
             * is what some corporate proxies honour, this is what modern browsers honour.
             *
             * `object-src 'none'` and `base-uri 'self'` close two classic bypasses — plugin
             * embedding, and rewriting relative URLs by injecting a <base> tag.
             *
             * img-src includes the avatar and storage hosts already whitelisted for <Image>,
             * plus data: and blob: — blob: is required because neural TTS audio is played from
             * an object URL, and without it the panel is silent under this policy.
             */
            key: 'Content-Security-Policy',
            value: [
              "default-src 'self'",
              "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
              "style-src 'self' 'unsafe-inline'",
              "img-src 'self' data: blob: https://*.supabase.co https://lh3.googleusercontent.com https://avatars.githubusercontent.com",
              "font-src 'self' data:",
              // blob: and mediastream: — the presence check reads a camera track and the
              // panel plays TTS audio from an object URL.
              "media-src 'self' blob: mediastream:",
              `connect-src ${connectOrigins().join(' ')}`,
              "worker-src 'self' blob:",
              "object-src 'none'",
              "base-uri 'self'",
              "form-action 'self'",
              "frame-ancestors 'none'",
              'upgrade-insecure-requests',
            ].join('; '),
          },
          {
            // Isolates this origin's browsing context group, so a popup cannot reach back into
            // the page via window.opener.
            key: 'Cross-Origin-Opener-Policy',
            value: 'same-origin',
          },
        ],
      },
    ];
  },
};

export default nextConfig;
