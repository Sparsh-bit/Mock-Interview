import Link from 'next/link';

import { Lockup } from '@/components/brand/Brandmark';
import { BRAND } from '@/lib/brand';
// From the pure variants module, not from `button.tsx` — that file is a client
// component, and a server component cannot call a function exported by one.
import { buttonVariants } from '@/components/ui/button-variants';
import { cn } from '@/lib/utils';

/**
 * The 404 — app/not-found.tsx
 *
 * WHAT WAS HERE BEFORE: Next.js's built-in default, a bare "404: This page could not be found."
 * on a white page in the framework's own type, with no branding and no way out. On a public
 * product that is what a candidate sees after a mistyped URL or a stale link from a friend, and
 * it reads as a broken deployment rather than as a wrong address — which is a materially
 * different thing to conclude about a product you were about to pay for.
 *
 * It says nothing about the deployment. `route-boundaries.test.ts` asserts that of every error
 * boundary in the app for a reason: a stack frame, a hostname or an internal path on an error
 * screen is a free map of the infrastructure, handed to whoever typed the wrong URL.
 *
 * TWO ROUTES OUT, because the reader is in one of two situations and they need different
 * things: signed in and mis-navigated (the dashboard), or arrived from outside on a dead link
 * (the front page). Guessing which and offering only that one strands the other.
 *
 * A server component: it holds no state and needs no interactivity, so it ships no JavaScript.
 */
export default function NotFound() {
  return (
    <main className="mx-auto flex min-h-[70vh] max-w-xl flex-col justify-center px-6 py-16">
      <Link href="/" aria-label={`${BRAND.name} home`} className="mb-10 w-fit">
        <Lockup width={200} />
      </Link>

      {/* The only lit element, because it is the only element — docs/DESIGN-LANGUAGE §1. */}
      <div className="lit rounded-2xl p-8">
        <p className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.18em] text-accent-coral-ink">
          <span aria-hidden className="h-px w-3.5 shrink-0 bg-accent-coral" />
          404
        </p>

        <h1 className="mt-3 text-2xl font-medium tracking-[-0.02em]">
          That seat doesn&apos;t exist
        </h1>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          The page you asked for isn&apos;t here. It may have moved, or the link may have been
          typed slightly wrong — nothing is broken on our side.
        </p>

        <div className="mt-7 flex flex-wrap gap-2">
          <Link href="/dashboard" className={cn(buttonVariants({ size: 'md' }))}>
            Go to your dashboard
          </Link>
          <Link
            href="/"
            className={cn(buttonVariants({ variant: 'secondary', size: 'md' }))}
          >
            Back to the front page
          </Link>
        </div>
      </div>
    </main>
  );
}
