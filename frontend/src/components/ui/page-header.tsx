import * as React from 'react';
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
  className,
}: {
  eyebrow?: string;
  title: React.ReactNode;
  description?: React.ReactNode;
  /** Buttons or controls, right-aligned on desktop and wrapped underneath on mobile. */
  actions?: React.ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cn(
        'flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between sm:gap-6',
        className,
      )}
    >
      <div className="min-w-0">
        {eyebrow && (
          <p className="mb-2 font-mono text-[11px] uppercase tracking-[0.22em] text-muted-foreground">
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
