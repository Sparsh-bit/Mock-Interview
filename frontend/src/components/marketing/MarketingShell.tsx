'use client';

import type { ReactNode } from 'react';

import { useSmoothScroll } from './useSmoothScroll';

/**
 * THE PUBLIC THEME BOUNDARY — components/marketing/MarketingShell.tsx
 *
 * Two jobs, and they are both boundaries rather than decoration.
 *
 * 1. IT APPLIES `.mk`. Everything in marketing.css is scoped to that class and nothing in it
 *    touches `:root`. Wrap a page in this and it is cream, espresso and gold; take the
 *    wrapper away and the page is exactly the product's warm-paper theme again, with no other
 *    edit. That is what makes it safe to retheme the public site without going near the
 *    fourteen signed-in pages or the two test files that pin their tokens.
 *
 * 2. IT TURNS ON INERTIAL SCROLLING. Here and nowhere else. Easing the wheel is right for a
 *    landing page built around a scrubbed film and wrong for a dashboard, where a scroll is
 *    somebody looking for a row in a table and every millisecond of easing is latency between
 *    them and it. Putting the hook in the shell rather than in the root layout is what keeps
 *    that distinction from quietly eroding.
 *
 * It is a client component because the hook needs the wheel, and `children` passes straight
 * through — so every section inside it stays a server component unless it declares otherwise,
 * and only the sections that actually animate ship JavaScript.
 */
export function MarketingShell({ children }: { children: ReactNode }) {
  useSmoothScroll();

  return <div className="mk relative min-h-screen">{children}</div>;
}
