import { BRAND } from '@/lib/brand';
import { cn } from '@/lib/utils';

/**
 * The mark — components/brand/Brandmark.tsx
 *
 * A chair, seen from the side, standing in a cone of light.
 *
 * The chair is four strokes: the back and the rear leg are one continuous vertical, the seat
 * runs forward from it, the front leg drops from the seat's end. That is the fewest marks that
 * still reads as a chair rather than as a bracket, and at 15px — the size it actually renders
 * at in the rail — anything more becomes mud.
 *
 * THE CONE IS THE HALF THAT MAKES IT THE PRODUCT'S MARK rather than a furniture icon. A chair
 * alone is a seat; a chair under a light is a position, and being in that position is the
 * entire proposition. It is also the design language in miniature: one thing lit, everything
 * else dim (see docs/DESIGN-LANGUAGE.md).
 *
 * DRAWN RATHER THAN PICKED. An emoji or a stock glyph would sit at a different optical weight
 * from every other stroke on the page and would announce that nobody chose it. The strokes are
 * tuned to the same 1.9 weight the navigation icons use, so the mark belongs to the same set.
 */
export function Brandmark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      // Decorative: the wordmark beside it already carries the name, and a second copy in the
      // accessibility tree makes a screen reader say "Hotseat Hotseat".
      aria-hidden="true"
      focusable="false"
      className={cn('h-full w-full', className)}
    >
      {/* The light. Kept low enough that it never competes with the chair at small sizes —
          it should register as atmosphere, not as a second object. */}
      <path d="M11.4 1.6 L4.2 21.4 L19.4 21.4 Z" fill="currentColor" opacity="0.26" />
      <g
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        {/* Back and rear leg as one stroke — a chair's back post continues to the floor, and
            drawing it as two would put a join where a real chair has none. */}
        <path d="M8.6 5.4 V19.4" />
        <path d="M8.6 13.4 H16.4" />
        <path d="M16.4 13.4 V19.4" />
      </g>
    </svg>
  );
}

/**
 * Mark plus name. `collapsed` drops the wordmark for the narrow rail — the mark alone still
 * identifies the product, which is the entire reason a mark exists.
 */
export function Wordmark({
  collapsed = false,
  className,
}: {
  collapsed?: boolean;
  className?: string;
}) {
  return (
    <span className={cn('flex min-w-0 items-center gap-2', className)}>
      <span
        className={cn(
          'flex h-7 w-7 shrink-0 items-center justify-center rounded-[9px] text-surface-elevated',
          // The one gradient in the chrome, and it is spent here. Amber into coral is the
          // brand pair — the heat the name is about — and everything else on these pages is
          // flat by choice, so the mark is the only thing that catches light and the eye goes
          // to it without being told to.
          'bg-[linear-gradient(140deg,hsl(var(--accent-amber)),hsl(var(--accent-coral)))]',
          'shadow-[0_1px_2px_-1px_rgb(28_22_14/0.25)]',
        )}
      >
        <Brandmark className="h-[16px] w-[16px]" />
      </span>
      {!collapsed && (
        <span className="truncate text-[14px] font-semibold tracking-[-0.015em]">
          {BRAND.name}
        </span>
      )}
    </span>
  );
}
