import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
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
        ],
      },
    ];
  },
};

export default nextConfig;
