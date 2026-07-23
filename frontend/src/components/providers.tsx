'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';
import { useEffect, useState } from 'react';
import { ApiError } from '@/lib/api';

// Some browser extensions (translate / save-page tools) inject content
// scripts that throw "Cannot find menu item with id ..." on every page —
// it's the extension's bug, not ours, but it pollutes the console. Suppress
// ONLY those exact messages so real errors are unaffected.
const EXTENSION_NOISE = /Cannot find menu item with id/i;

function useSilenceExtensionNoise() {
  useEffect(() => {
    const onRejection = (e: PromiseRejectionEvent) => {
      const msg = typeof e.reason === 'string' ? e.reason : e.reason?.message ?? '';
      if (EXTENSION_NOISE.test(msg)) {
        e.preventDefault();
        e.stopImmediatePropagation();
      }
    };
    const onError = (e: ErrorEvent) => {
      if (EXTENSION_NOISE.test(e.message ?? '')) {
        e.preventDefault();
        e.stopImmediatePropagation();
      }
    };
    window.addEventListener('unhandledrejection', onRejection, true);
    window.addEventListener('error', onError, true);
    return () => {
      window.removeEventListener('unhandledrejection', onRejection, true);
      window.removeEventListener('error', onError, true);
    };
  }, []);
}

export function Providers({ children }: { children: React.ReactNode }) {
  useSilenceExtensionNoise();
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 60 * 1000, // 1 minute
            gcTime: 5 * 60 * 1000, // 5 minutes
            // Retry once, but never for errors a retry can't fix (auth,
            // not-found, validation) -- those just double the failed
            // requests and delay showing the real error state.
            retry: (failureCount, error) => {
              if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
                return false;
              }
              return failureCount < 1;
            },
            refetchOnWindowFocus: false,
          },
          mutations: {
            retry: 0,
          },
        },
      })
  );

  return (
    <QueryClientProvider client={queryClient}>
      {children}
      {process.env.NODE_ENV === 'development' && (
        <ReactQueryDevtools initialIsOpen={false} />
      )}
    </QueryClientProvider>
  );
}
