'use client';

import { motion } from 'framer-motion';
import { createContext, useContext, useState } from 'react';

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

/**
 * The focus BEHAVIOUR, without the card markup.
 *
 * FocusCards below renders its own simple card, which is right for a list of names. Several
 * places in the dashboard already have rich cards — icon, badge, description, stats, a CTA —
 * and replacing those with a simple one to gain the dimming would be a downgrade dressed as a
 * feature. So the mechanic is available as a wrapper too, exactly like TimelineLayout: the
 * caller keeps its own content and gets the focus.
 *
 * Context, not prop drilling, because the group and the items are usually separated by a
 * `.map` and a motion wrapper.
 */
const FocusContext = createContext<{
  active: string | null;
  setActive: (id: string | null) => void;
} | null>(null);

export function FocusGroup({ children, className }: { children: React.ReactNode; className?: string }) {
  const [active, setActive] = useState<string | null>(null);
  return (
    <FocusContext.Provider value={{ active, setActive }}>
      <div className={className}>{children}</div>
    </FocusContext.Provider>
  );
}

export function FocusItem({
  id,
  children,
  className,
}: {
  id: string;
  children: React.ReactNode;
  className?: string;
}) {
  const ctx = useContext(FocusContext);
  // Usable outside a FocusGroup — it simply does nothing, rather than throwing. A layout
  // component that crashes when it is not perfectly nested is a component nobody reaches for.
  const dimmed = ctx ? ctx.active !== null && ctx.active !== id : false;

  return (
    <div
      onMouseEnter={() => ctx?.setActive(id)}
      onMouseLeave={() => ctx?.setActive(null)}
      // Focus follows hover so a keyboard user gets the same emphasis. Capture, because the
      // focus lands on a child link rather than this wrapper.
      onFocusCapture={() => ctx?.setActive(id)}
      onBlurCapture={() => ctx?.setActive(null)}
      className={cn(
        'transition-opacity duration-300',
        dimmed ? 'opacity-45' : 'opacity-100',
        className,
      )}
    >
      {children}
    </div>
  );
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
