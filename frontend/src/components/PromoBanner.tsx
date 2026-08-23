'use client';

import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';

import { getBrowserApiClient } from '@/lib/api';

/**
 * The promo strip on the dashboard — components/PromoBanner.tsx
 *
 * An image the owner uploads against a live public offer. Clicking it goes to the pricing page
 * and lands on the box where the code is typed.
 *
 * IT RENDERS NOTHING MOST OF THE TIME, and that is the normal case rather than a failure. Most
 * days there is no live public offer with an image; the server returns null and this returns
 * null. Nothing here treats an absent banner as an error, and nothing shows a placeholder — a
 * skeleton that resolves into nothing is worse than no skeleton, because it pulls the eye to
 * the one thing on the page that is not the task the candidate came to do.
 *
 * THE SERVER DECIDES WHETHER THERE IS ANYTHING TO SHOW, and it decides on the OFFER: enabled,
 * public, inside its window. So switching a code off takes its advertisement down in the same
 * action, and there is no route to a dashboard promoting a code that refuses everybody who
 * types it. This component deliberately knows none of those rules.
 *
 * THE CONTAINER FIXES THE ASPECT RATIO, WHICH IS WHAT MAKES A BAD UPLOAD SURVIVABLE. The box
 * is `aspect-[3/1]` with `object-cover`, so an image that met the requirement lands exactly and
 * one that somehow did not is centre-cropped rather than stretched or pushing the page around.
 * The ratio comes from the server alongside the image, so the admin form, the validator and
 * this box cannot drift apart. There is no fixed height anywhere: the strip scales with the
 * column, which is what keeps it correct from a 320px phone to an ultrawide.
 */

interface PromoBannerData {
  image_url: string;
  alt_text: string;
  code: string;
  aspect_ratio: number;
}

export function PromoBanner() {
  const banner = useQuery({
    queryKey: ['promo-banner'],
    queryFn: async () => {
      const res = await getBrowserApiClient().get('/api/v1/billing/promo-banner');
      return (res.data ?? null) as PromoBannerData | null;
    },
    // A banner changes when the owner uploads one, not between page views. Five minutes keeps
    // the dashboard from re-asking on every navigation while still picking up a new one
    // without the candidate needing a hard reload.
    staleTime: 5 * 60 * 1000,
    // Silent on failure. This is decoration on somebody else's dashboard: if the request
    // fails, the right outcome is no strip, not a retry storm or an error card above the
    // thing they came to do.
    retry: false,
  });

  const data = banner.data;
  if (!data?.image_url) return null;

  return (
    <Link
      href="/pricing#apply-offer"
      // NAMED, because this is an image inside a link. Without an accessible name a screen
      // reader announces the URL, and the alt text is the only thing that says what the offer
      // is — which is why alt_text is NOT NULL in the database rather than optional.
      aria-label={`${data.alt_text} — apply this code on the pricing page`}
      className="group block overflow-hidden rounded-2xl border border-border/60 transition-shadow hover:shadow-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {/* eslint-disable-next-line @next/next/no-img-element -- the image is a Supabase public
          URL, which is not a configured next/image domain. Adding one would mean a build-config
          change plus an optimiser round trip for an asset that is already sized correctly by
          the upload validator. */}
      <img
        src={data.image_url}
        alt={data.alt_text}
        // Set from the SERVER's ratio rather than hardcoded, so the one fact lives in one
        // place. The Tailwind class is the fallback for the first paint before the inline
        // style applies.
        style={{ aspectRatio: String(data.aspect_ratio) }}
        className="aspect-[3/1] w-full object-cover transition-transform duration-300 group-hover:scale-[1.01]"
        // Loaded eagerly and given a fetch priority: it sits at the top of the dashboard, so
        // lazy-loading it would leave a visible gap that collapses after paint.
        loading="eager"
        decoding="async"
      />
    </Link>
  );
}

export default PromoBanner;
