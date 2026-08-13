'use client';

import { useEffect, useRef } from 'react';

/**
 * Cloudflare Turnstile — components/billing/Turnstile.tsx
 *
 * Rendered only when an offer asks for it. A ₹1 launch offer or a 100%-off code is worth
 * farming with a script — accounts are free, so "one redemption per account" only limits how
 * many times one person can be bothered to make an email address — and this is the thing
 * that costs a script something.
 *
 * NOT ON EVERY PURCHASE. A captcha in front of everything trains people to click through it
 * without reading, which is how you end up with a control everybody satisfies and nobody
 * notices. `Offer.requires_captcha` decides, per offer, and the admin sets it.
 *
 * THE SITE KEY IS PUBLIC BY DESIGN, which is why it lives in NEXT_PUBLIC_. It identifies the
 * widget; the SECRET, which is what actually validates a token, is server-side only and is
 * never sent here. The token this produces is worthless without that secret.
 *
 * RENDERS NOTHING WITHOUT A SITE KEY. The server refuses offers that require a captcha when
 * Turnstile is unconfigured, so there is no case where a missing key should mean a waived
 * requirement — a blank space and a refusal is honest; an invisible widget that silently
 * passes is not.
 */

interface TurnstileApi {
  render: (el: HTMLElement, opts: Record<string, unknown>) => string;
  remove: (id: string) => void;
}

declare global {
  interface Window {
    turnstile?: TurnstileApi;
  }
}

const SDK_URL = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';

let loading: Promise<boolean> | null = null;

function loadSdk(): Promise<boolean> {
  if (typeof window === 'undefined') return Promise.resolve(false);
  if (window.turnstile) return Promise.resolve(true);
  if (loading) return loading;
  loading = new Promise<boolean>((resolve) => {
    const script = document.createElement('script');
    script.src = SDK_URL;
    script.async = true;
    script.defer = true;
    script.onload = () => resolve(Boolean(window.turnstile));
    script.onerror = () => {
      // Reset so a retry is possible. A blocked CDN is recoverable and common.
      loading = null;
      resolve(false);
    };
    document.head.appendChild(script);
  });
  return loading;
}

export interface TurnstileProps {
  /** Called with a token when the challenge passes, and with '' when it expires. */
  onToken: (token: string) => void;
}

export function Turnstile({ onToken }: TurnstileProps) {
  const boxRef = useRef<HTMLDivElement | null>(null);
  const widgetRef = useRef<string | null>(null);
  //: The callback in a ref, so re-rendering the parent does not tear down and re-render the
  //: widget — which would reset a challenge the candidate had already passed.
  const onTokenRef = useRef(onToken);
  onTokenRef.current = onToken;

  const siteKey = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY ?? '';

  useEffect(() => {
    if (!siteKey) return;
    let cancelled = false;

    void loadSdk().then((ready) => {
      if (cancelled || !ready || !boxRef.current || !window.turnstile) return;
      widgetRef.current = window.turnstile.render(boxRef.current, {
        sitekey: siteKey,
        callback: (token: string) => onTokenRef.current(token),
        // A token is single-use and short-lived. Clearing it on expiry means the purchase
        // fails with "please complete the verification" rather than with an opaque rejection
        // from Cloudflare after the candidate has pressed pay.
        'expired-callback': () => onTokenRef.current(''),
        'error-callback': () => onTokenRef.current(''),
        theme: 'auto',
      });
    });

    return () => {
      cancelled = true;
      if (widgetRef.current && window.turnstile) {
        window.turnstile.remove(widgetRef.current);
        widgetRef.current = null;
      }
    };
  }, [siteKey]);

  if (!siteKey) {
    // The server refuses these offers when Turnstile is unconfigured, so this states the
    // situation rather than rendering a gap the candidate cannot get past.
    return (
      <p className="text-xs text-muted-foreground">
        This offer needs human verification, which is not set up on this deployment yet.
      </p>
    );
  }

  return <div ref={boxRef} className="my-2" />;
}

export default Turnstile;
