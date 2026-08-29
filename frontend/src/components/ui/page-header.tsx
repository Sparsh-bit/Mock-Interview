'use client';

import * as React from 'react';

import { usePathname } from 'next/navigation';

import { ROUTE_TONE, TONES, type Tone } from '@/lib/tones';
import { cn } from '@/lib/utils';

/**
 * The one header every screen in the app uses.
 *
 * Before this existed, ten screens each hand-rolled their own. They had four
 * different type treatments between them — `text-2xl font-bold tracking-tight`,
 * `text-2xl font-medium tracking-[-0.025em]`, bare `text-2xl font-bold`, and the
 * dashboard's own larger one — so moving between pages produced a small jump in
 * weight and letterspacing that reads as different people having built each
 * screen. Nothing else about those headers differed; only the styling drifted.
 *
 * The `eyebrow` is the same mono, uppercase, wide-tracked label the landing page
 * uses to number its sections. Carrying it into the app is what makes the two
 * halves of the product feel like one thing rather than a marketing site bolted
 * to a dashboard.
 *
 * Type matches the landing page's section headings: medium weight at -0.03em,
 * fluid between 1.5rem and 2rem. Bold at this size is shouting — the header is
 * already the largest thing on the page and does not also need the weight.
 */
export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  tone,
  className,
}: {
  eyebrow?: string;
  title: React.ReactNode;
  description?: React.ReactNode;
  /** Buttons or controls, right-aligned on desktop and wrapped underneath on mobile. */
  actions?: React.ReactNode;
  /**
   * Overrides the colour the eyebrow is drawn in. Almost never needed — the tone is derived
   * from the route, so a page cannot accidentally disagree with its own rail entry. Pass it
   * only for a surface that has no rail entry of its own.
   */
  tone?: Tone;
  className?: string;
}) {
  /*
   * THE EYEBROW IS THE COLOUR OF THE RAIL ENTRY THAT BROUGHT YOU HERE, derived from the path
   * rather than passed in — a prop would be one more thing for a new page to forget, and a
   * page whose header disagrees with its rail is worse than one with no colour, because it
   * teaches the reader that the colours mean nothing.
   *
   * It is wayfinding, not decoration: on a product with fourteen destinations that share one
   * layout, the top-left of the page is where you check which one you are in. Longest matching
   * prefix, so /report/<id> inherits /report.
   */
  const pathname = usePathname();
  const matched = Object.keys(ROUTE_TONE)
    .filter((r) => pathname === r || pathname.startsWith(r + '/'))
    .sort((a, b) => b.length - a.length)[0];
  const resolved = tone ?? (matched ? ROUTE_TONE[matched] : undefined);
  const t = resolved ? TONES[resolved] : null;

  return (
    <header
      className={cn(
        'flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between sm:gap-6',
        className,
      )}
    >
      <div className="min-w-0">
        {eyebrow && (
          <p
            className={cn(
              'mb-2 flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.22em]',
              t ? t.ink : 'text-muted-foreground',
            )}
          >
            {/* A 14px rule rather than a dot or an icon. It reads as a printed section mark,
                which is the register the rest of this type is in — and unlike an icon it needs
                no meaning of its own. */}
            {t && <span aria-hidden className={cn('h-px w-3.5 shrink-0', t.rail)} />}
            {eyebrow}
          </p>
        )}
        <h1 className="text-[clamp(1.5rem,2.6vw,2rem)] font-medium leading-[1.12] tracking-[-0.03em]">
          {title}
        </h1>
        {description && (
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">
            {description}
          </p>
        )}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}
