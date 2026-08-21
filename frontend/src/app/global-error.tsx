'use client';

/**
 * The last boundary. Catches what the root layout itself throws.
 *
 * WHY IT EXISTS EVEN THOUGH TWO GROUP-LEVEL BOUNDARIES DO. A segment boundary lives INSIDE
 * the root layout, so it cannot catch a failure in that layout — the providers, the fonts,
 * the theme. When the root throws there is no shell left to render an error into, which is
 * why this file has to supply its own `<html>` and `<body>`: React has unmounted everything
 * above it.
 *
 * DELIBERATELY PLAIN, AND WITH NO IMPORTS. Every reason the root layout can fail is a reason
 * the component library, the Tailwind layer or the providers might also be unavailable, so
 * importing Card or Button here risks the error screen failing for the same cause as the
 * error. Inline styles rather than classes, for the same reason: if globals.css did not load,
 * a `text-muted-foreground` is invisible text on an unstyled page.
 *
 * A hard reload rather than `reset()`. If the root layout failed, re-rendering it is likely
 * to fail identically; replacing the document is the honest recovery.
 */
export default function GlobalError({
  error,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontFamily:
            'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
          background: '#0b0f19',
          color: '#e5e7eb',
          padding: '1.5rem',
        }}
      >
        <div style={{ maxWidth: '28rem', textAlign: 'center' }}>
          <h1 style={{ fontSize: '1.125rem', fontWeight: 600, margin: 0 }}>
            Something went wrong
          </h1>
          <p style={{ fontSize: '0.875rem', opacity: 0.75, marginTop: '0.75rem' }}>
            The app failed to start up. Reloading usually fixes it.
          </p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            style={{
              marginTop: '1.25rem',
              padding: '0.5rem 1rem',
              borderRadius: '0.75rem',
              border: '1px solid rgba(229,231,235,0.25)',
              background: 'transparent',
              color: 'inherit',
              font: 'inherit',
              cursor: 'pointer',
            }}
          >
            Reload
          </button>
          {error.digest && (
            <p
              style={{
                marginTop: '1rem',
                fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
                fontSize: '0.6875rem',
                opacity: 0.55,
              }}
            >
              ref {error.digest}
            </p>
          )}
        </div>
      </body>
    </html>
  );
}
