/**
 * Opening the Razorpay payment sheet — lib/billing/razorpay-checkout.ts
 *
 * THIS WAS THE MISSING HALF. The server side has been complete for a while: the order is
 * opened with a server-resolved amount, and the webhook that grants the items is
 * signature-verified, amount-checked and idempotent. The browser never loaded Razorpay's
 * SDK, so pressing Buy produced an order id and a toast saying so. Everything was ready
 * except the part the candidate touches.
 *
 * THE SDK IS LOADED ON DEMAND, not in the document head. It is ~100KB of third-party
 * JavaScript that only matters to somebody who has decided to pay, and this product's users
 * are on phones and metered data — every visitor to the pricing page paying for it is a real
 * cost for a script most of them will never invoke.
 *
 * PAYMENT SUCCESS HERE IS NOT ENTITLEMENT. The sheet's success callback means the candidate
 * finished the form; the items are granted by the WEBHOOK, server-side, after Razorpay
 * confirms capture. Treating the callback as proof of payment would let anyone who can call
 * a JavaScript function grant themselves interviews. The callback's only job is to tell the
 * candidate what happened and refresh the balance.
 *
 * CSP: `checkout.razorpay.com` is allow-listed in script-src and frame-src, and
 * `api.razorpay.com` in connect-src — see next.config.ts. Without all three the sheet opens
 * and dies silently, with a console error the candidate never sees.
 */

const SDK_URL = 'https://checkout.razorpay.com/v1/checkout.js';

interface RazorpayInstance {
  open: () => void;
  on: (event: string, handler: (payload: unknown) => void) => void;
}

declare global {
  interface Window {
    Razorpay?: new (options: Record<string, unknown>) => RazorpayInstance;
  }
}

let loading: Promise<boolean> | null = null;

/**
 * Load the SDK once, and remember the promise rather than the result.
 *
 * Remembering the PROMISE is what makes two rapid clicks share one network request instead
 * of racing to append two script tags — the second click joins the first load.
 */
function loadSdk(): Promise<boolean> {
  if (typeof window === 'undefined') return Promise.resolve(false);
  if (window.Razorpay) return Promise.resolve(true);
  if (loading) return loading;

  loading = new Promise<boolean>((resolve) => {
    const script = document.createElement('script');
    script.src = SDK_URL;
    script.async = true;
    script.onload = () => resolve(Boolean(window.Razorpay));
    script.onerror = () => {
      // Reset, so a later attempt can retry rather than being stuck with a rejected promise
      // for the rest of the session. A blocked CDN, an ad blocker, or a dropped connection
      // are all recoverable and all common on a student's network.
      loading = null;
      resolve(false);
    };
    document.head.appendChild(script);
  });
  return loading;
}

export interface OpenCheckoutArgs {
  orderId: string;
  amountPaise: number;
  keyId: string;
  itemName: string;
  /** Prefills the form so the candidate is not retyping what we already know. */
  prefill?: { name?: string; email?: string; contact?: string };
  /**
   * Called with the ids Razorpay hands back when the sheet succeeds.
   *
   * These are what `POST /billing/verify` needs. The webhook remains the primary granting
   * path; this is the second, independent one, because a webhook can be pointed at the wrong
   * URL, signed with the wrong secret, blocked or simply late — and every one of those
   * presents to the candidate as "my money left and nothing arrived".
   */
  onSuccess: (proof: {
    razorpay_payment_id: string;
    razorpay_order_id: string;
    razorpay_signature: string;
  }) => void;
  onDismiss: () => void;
  onFailure: (reason: string) => void;
}

/**
 * Open the payment sheet. Resolves once it has been opened, not once it has been paid.
 *
 * Returns false when the SDK could not be loaded at all, so the caller can say something
 * useful instead of leaving a button that appears to do nothing.
 */
export async function openCheckout(args: OpenCheckoutArgs): Promise<boolean> {
  const ready = await loadSdk();
  if (!ready || !window.Razorpay) return false;

  const rzp = new window.Razorpay({
    key: args.keyId,
    order_id: args.orderId,
    // Shown in the sheet. Razorpay charges the ORDER's amount regardless of what is passed
    // here — this is display only, and the order was created server-side.
    amount: args.amountPaise,
    currency: 'INR',
    name: 'Hotseat',
    description: args.itemName,
    prefill: args.prefill ?? {},
    theme: { color: '#4f46e5' },
    modal: {
      // Closing the sheet without paying is an ordinary thing to do and must not look like
      // an error. Without this the caller is left with a spinner and no event.
      ondismiss: args.onDismiss,
    },
    handler: (response: {
      razorpay_payment_id?: string;
      razorpay_order_id?: string;
      razorpay_signature?: string;
    }) => {
      // The candidate completed the form. STILL NOT PROOF OF PAYMENT — the ids and signature
      // are handed to the server, which checks the signature and then asks Razorpay whether
      // the money actually moved. Nothing is granted on the strength of this callback alone;
      // it is a JavaScript function anyone could call.
      args.onSuccess({
        razorpay_payment_id: response?.razorpay_payment_id ?? '',
        razorpay_order_id: response?.razorpay_order_id ?? '',
        razorpay_signature: response?.razorpay_signature ?? '',
      });
    },
  });

  rzp.on('payment.failed', (payload: unknown) => {
    const reason =
      (payload as { error?: { description?: string } })?.error?.description ??
      'The payment did not go through.';
    args.onFailure(reason);
  });

  rzp.open();
  return true;
}
