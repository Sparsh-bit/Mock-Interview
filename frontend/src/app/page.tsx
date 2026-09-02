import type { Metadata } from 'next';

import { MarketingShell } from '@/components/marketing/MarketingShell';
import { MkClose } from '@/components/marketing/MkClose';
import { MkFilm } from '@/components/marketing/MkFilm';
import { MkFooter } from '@/components/marketing/MkFooter';
import { MkHero } from '@/components/marketing/MkHero';
import { MkNav } from '@/components/marketing/MkNav';
import { MkPricing } from '@/components/marketing/MkPricing';
import { MkProof } from '@/components/marketing/MkProof';
import { MkReel } from '@/components/marketing/MkReel';
import { MkShowcase } from '@/components/marketing/MkShowcase';
import { BRAND } from '@/lib/brand';

/**
 * THE LANDING PAGE — app/page.tsx
 *
 * ── WHAT CHANGED AND WHY ─────────────────────────────────────────────────────────────────
 * The previous version of this file was 604 lines of markup with its own nav, its own
 * annotation components and its own photography rules, and `docs/REDESIGN.md` recorded that
 * it was deliberately left out of the pass that redesigned the fourteen signed-in pages. So
 * it was the last surface still speaking the old dialect, and the first surface anybody sees.
 *
 * This version is a composition of eight sections and nothing else. Every section owns its
 * own markup, its own motion and its own copy; the page's only job is to put them in an
 * order and to decide that the order is the argument.
 *
 * ── THE ORDER, AND WHY IT IS THIS ORDER ──────────────────────────────────────────────────
 *   HERO       one sentence and one button. No product shot, because the next full viewport
 *              is the product at forty times the size and a still would spend the reveal.
 *   FILM       the takeover. Six rounds, scrubbed by scroll, on a dark stage. This is the
 *              page's centre of gravity: everything above it exists to get you here and
 *              everything below it exists because you arrived.
 *   PROOF      the first thing after the spectacle is the arithmetic — two recruiters'
 *              weightings side by side, then four numbers counted from the repository.
 *              Deliberately unglamorous, and deliberately immediately after the film, because
 *              that is where a sceptical reader starts looking for the catch.
 *   SHOWCASE   four real surfaces, live rather than screenshotted.
 *   REEL       the 34-second rendered film. After the showcase and not before it, because a
 *              3MB video is the heaviest thing on the page and it should be the last thing
 *              anybody pays for — by this point they have chosen to keep reading.
 *   PRICING    before the close, not after it. A visitor who has read this far has one
 *              question left and it is what it costs; making them scroll past a call to
 *              action to find out is how you lose them at the last step.
 *   CLOSE      the second dark band. Same subject as the film, so the ask reads as the same
 *              thing rather than as a new one.
 *
 * ── STRUCTURE ────────────────────────────────────────────────────────────────────────────
 * This file is a server component and stays one. `MarketingShell` is the only client boundary
 * at the top level; the sections that animate (`MkNav`, `MkHero`, `MkFilm`, `MkShowcase`,
 * `MkProof`) declare `'use client'` themselves, and `MkPricing`, `MkClose` and `MkFooter` do
 * not — so three of the eight sections ship no JavaScript at all.
 */

export const metadata: Metadata = {
  /* Self-referencing canonical. The root layout already sets one, and repeating it here means
     this page keeps it if the layout's default is ever narrowed. */
  alternates: { canonical: '/' },
  description: BRAND.promise,
};

export default function LandingPage() {
  return (
    <MarketingShell>
      <MkNav />
      <main>
        <MkHero />
        <MkFilm />
        <MkProof />
        <MkShowcase />
        <MkReel />
        <MkPricing />
        <MkClose />
      </main>
      <MkFooter />
    </MarketingShell>
  );
}
