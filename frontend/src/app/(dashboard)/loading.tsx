/**
 * What a dashboard navigation shows while the next page is still on the server.
 *
 * THE REPORT: "sometimes the main deployed software gets freezed and the sidebar options
 * does not respond". Nothing was frozen and no click was lost. There was no `loading.tsx`
 * anywhere in this app — not one file — and in the App Router that is not a missing nicety,
 * it is a missing Suspense boundary.
 *
 * WHAT ACTUALLY HAPPENED, precisely. Every page in this group is dynamic (`ƒ` in the build
 * output) and runs on the edge, so clicking a sidebar link fetches that segment's payload
 * from the server. Without a `loading.tsx` there is no boundary for React to suspend at, so
 * Next holds the CURRENT page on screen until the payload arrives and paints nothing in the
 * meantime:
 *
 *   - the old page stays up, fully rendered, so the app looks alive and idle
 *   - the sidebar highlight does not move, because it is driven by `usePathname()` and the
 *     pathname does not change until the navigation commits
 *   - so the click has no visible consequence whatsoever
 *
 * The user clicks again. Still nothing. That is the freeze, and it is indistinguishable
 * from a dead tab. It got much worse in production than in development for a reason that
 * has nothing to do with the frontend: the backend sleeps when idle, so the first
 * navigation after a quiet spell waits on a cold start.
 *
 * WHY THIS IS THE FIX RATHER THAN A SPINNER PER PAGE. A `loading.tsx` is the framework's
 * own answer: Next wraps the segment in `<Suspense fallback={this} />` automatically, so
 * EVERY route in this group — including the ones nobody has written yet — gets instant
 * feedback, and the navigation becomes interruptible. Adding `isLoading &&
 * <Spinner />` to fifteen pages would be fifteen chances to forget, would not cover the
 * server-render wait at all (which is the part that was slow), and is exactly the
 * per-call-site patchwork this codebase keeps paying for.
 *
 * IT MIRRORS THE SHELL, NOT A SPINNER. A centred spinner on a blank page reads as "the app
 * has gone away". Blocks in roughly the positions the content will occupy read as "it is
 * coming", and they stop the layout jumping when it lands. No text: a fallback that says
 * "Loading…" is a string to translate and a claim that can be wrong, and the shape says it
 * already.
 */
export default function DashboardLoading() {
  return (
    // aria-busy over aria-live: a screen reader should hear "busy" once, not have a
    // decorative skeleton read out block by block as it appears.
    <div className="animate-pulse space-y-6" aria-busy="true" aria-label="Loading">
      {/* The page heading. Two bars, because every page in this group opens with a title
          and a line of context under it — see components/ui/page-header.tsx. */}
      <div className="space-y-3">
        <div className="h-3 w-24 rounded bg-muted/40" />
        <div className="h-9 w-72 max-w-full rounded-lg bg-muted/50" />
        <div className="h-4 w-96 max-w-full rounded bg-muted/30" />
      </div>

      {/* The stat row. Four across on desktop, matching the dashboard's grid so the real
          cards land where these were rather than shifting the page as they arrive. */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-28 rounded-xl border border-border/50 bg-surface-elevated"
          />
        ))}
      </div>

      {/* The main content block, and a narrower column beside it on desktop. */}
      <div className="grid gap-4 lg:grid-cols-3">
        <div className="h-64 rounded-xl border border-border/50 bg-surface-elevated lg:col-span-2" />
        <div className="h-64 rounded-xl border border-border/50 bg-surface-elevated" />
      </div>
    </div>
  );
}
