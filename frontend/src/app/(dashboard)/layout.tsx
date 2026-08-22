import { redirect } from 'next/navigation';
import { createClient } from '@/lib/supabase/server';
import { AppSidebar } from '@/components/layout/Sidebar';
import { AppHeader } from '@/components/layout/Header';

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();

  if (!user) {
    redirect('/login');
  }

  // `paper-grain` goes on this shell, not only on <body>. This div is opaque
  // and covers the viewport, so a body-level texture would be hidden behind it.
  // Here the grain is painted once into this element's layer and shows through
  // <main>, which has no background of its own — a static backdrop the scrolling
  // content moves over, costing nothing per frame. As a fixed overlay above
  // everything, it cost a full-viewport translucent blend on every scroll frame.
  /*
   * 100dvh, NOT h-screen (100vh). This shell is `overflow-hidden` and <main> below it is the
   * only scroller, so the shell's height IS the reachable area — and on mobile Safari and
   * Chrome `vh` is the height with the browser chrome HIDDEN. So a 100vh shell is permanently
   * taller than what the phone actually shows: <main>'s box extends under the address bar,
   * and because the shell cannot scroll there is no gesture that brings it back. Scrolling
   * <main> to its very end still leaves the last ~60-100px of every dashboard page — which is
   * wherever the page's final action happens to be — under the browser chrome forever.
   *
   * The session page and the GD round were converted to dvh for exactly this reason; this
   * shell, which every other page in the product renders inside, was missed at the time.
   * dvh tracks the real viewport, and on desktop it is identical to vh, so nothing moves
   * there.
   */
  return (
    <div className="flex h-[100dvh] overflow-hidden bg-background paper-grain">
      {/* Sidebar */}
      <AppSidebar user={user} />

      {/* Main content area.
          `min-w-0` IS LOAD-BEARING, and it is the horizontal twin of the dvh fix above.

          A flex item's automatic minimum size is its CONTENT width — "never narrower than the
          widest thing in me" — so a wide descendant on any page in this group pushes this
          column past the viewport, and the row above is `overflow-hidden`, which means that
          overflow is not a scrollbar. It is content off the right edge with no gesture that
          reaches it.

          It is also what makes the correct markup already on three pages actually work: the
          admin, marketing and AI-usage tables each sit in an `overflow-x-auto` wrapper around a
          `min-w-[820-900px]` table, and a wrapper like that only starts scrolling once its own
          width is constrained from above. Unconstrained, it sizes to its table and the shell
          gets pushed instead.

          HONEST NOTE ON WHY THIS WAS NOT THE LIVE BUG: `overflow-hidden` on this same element
          ALREADY resolves its automatic minimum size to zero — per CSS Flexbox, the
          content-based minimum does not apply to a box whose overflow is not `visible` — so
          the column does shrink today and those tables do scroll. `min-w-0` is here to say so
          explicitly and to survive somebody removing the `overflow-hidden` without knowing it
          was doing two jobs. Same reasoning for <main> one level down. */}
      <div className="flex flex-1 flex-col min-w-0 overflow-hidden">
        <AppHeader user={user} />
        {/* The content region. Inset on an 8pt rhythm and capped in width —
            a dashboard that stretches body text across a 2000px monitor is
            unreadable, and macOS apps always inset their content. */}
        <main className="min-w-0 flex-1 overflow-auto">
          <div className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-8 sm:py-8">{children}</div>
        </main>
      </div>
    </div>
  );
}
