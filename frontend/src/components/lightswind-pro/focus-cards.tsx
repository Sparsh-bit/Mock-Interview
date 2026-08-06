'use client';

import { motion } from 'framer-motion';
import { useState } from 'react';

import { cn } from '@/lib/utils';

/**
 * Focus cards — components/lightswind-pro/focus-cards.tsx
 *
 * Local implementation at the import path the brief named; `lightswind-pro` is not installed.
 * See the note in flip-words.tsx.
 *
 * WHAT "FOCUS" MEANS HERE. Hovering one card dims the others. That is the whole mechanic, and
 * it works because the eye is drawn to the bright thing — so a grid of twelve recruiters
 * stops being a wall and becomes one you are considering.
 *
 * It replaced a plain bordered list on the landing page. Deliberately restrained: no lift, no
 * shadow, no scale. The page it sits on is editorial, and a card that jumps under the cursor
 * would be the thing that makes it look generated rather than designed.
 *
 * KEYBOARD AND TOUCH. Focus does the same as hover, so a keyboard user gets the effect rather
 * than a dead grid. On touch there is no hover at all, and that is fine — nothing is hidden by
 * the dimming, so a tap-only user loses an emphasis, not information.
 */
export interface FocusCardItem {
  id: string;
  title: string;
  /** Optional line under the title — a track name, a programme, a count. */
  subtitle?: string;
  /** Optional leading index, rendered monospace. Keeps the "contents page" feel. */
  index?: string;
  href?: string;
}

export interface FocusCardsProps {
  items: FocusCardItem[];
  className?: string;
  /** Rendered inside each card, after the text. */
  renderExtra?: (item: FocusCardItem) => React.ReactNode;
}

export default function FocusCards({ items, className, renderExtra }: FocusCardsProps) {
  const [active, setActive] = useState<string | null>(null);

  return (
    <div className={cn('grid gap-3 sm:grid-cols-2 lg:grid-cols-4', className)}>
      {items.map((item) => {
        const dimmed = active !== null && active !== item.id;
        const Wrapper = item.href ? motion.a : motion.div;
        return (
          <Wrapper
            key={item.id}
            {...(item.href ? { href: item.href } : {})}
            onHoverStart={() => setActive(item.id)}
            onHoverEnd={() => setActive(null)}
            onFocus={() => setActive(item.id)}
            onBlur={() => setActive(null)}
            tabIndex={0}
            className={cn(
              'ease-out-expo group block rounded-xl border border-border/60 bg-card p-4',
              'outline-none transition-[border-color,opacity,filter] duration-300',
              'focus-visible:border-primary/50 focus-visible:ring-2 focus-visible:ring-primary/20',
              // Opacity, not scale or shadow. The dimming carries the whole effect and keeps
              // the page's editorial restraint.
              dimmed ? 'opacity-45' : 'opacity-100',
              !dimmed && active === item.id && 'border-primary/40',
            )}
          >
            <div className="flex items-baseline gap-3">
              {item.index && (
                <span className="font-mono text-[10px] tabular-nums text-accent-indigo">
                  {item.index}
                </span>
              )}
              <span className="text-sm font-medium">{item.title}</span>
            </div>
            {item.subtitle && (
              <p className="mt-1.5 text-[11px] leading-snug text-muted-foreground">
                {item.subtitle}
              </p>
            )}
            {renderExtra?.(item)}
          </Wrapper>
        );
      })}
    </div>
  );
}
