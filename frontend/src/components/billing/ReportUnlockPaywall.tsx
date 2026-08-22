'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { motion } from 'framer-motion';
import {
  BookOpen,
  Clock,
  ListChecks,
  Lock,
  MessageSquareQuote,
  Receipt,
  Sparkles,
  Tag,
} from 'lucide-react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { FreeOrderSheet } from '@/components/billing/FreeOrderSheet';
import { Turnstile } from '@/components/billing/Turnstile';
import { useAuth } from '@/hooks/useAuth';
import { useCheckout, useQuote, useVerifyPayment, type StoreItem } from '@/hooks/useBilling';
import { ApiError } from '@/lib/api/errors';
import { describeOffer } from '@/lib/billing/describe-offer';
import {
  REPORT_UNLOCK_DEADLINE_LABEL,
  countdown,
  formatCountdown,
  rupees,
  type ReportLock,
} from '@/lib/billing/report-unlock';
import { openCheckout } from '@/lib/billing/razorpay-checkout';
import { fadeUp, staggerContainer } from '@/lib/motion';

/**
 * The report paywall — components/billing/ReportUnlockPaywall.tsx
 *
 * WHAT THE CANDIDATE IS LOOKING AT. They have just finished a FREE interview, their report
 * exists, and this screen stands between them and it. So the first thing it does is say what
 * they already got for nothing, because a paywall that opens with a price reads as a
 * bait-and-switch and this one genuinely is not: the interview — panel, coding round, scoring
 * — was free, and ₹49 buys the personalised report and study material that come out of it.
 *
 * IT NEVER RENDERS ON A PURCHASED INTERVIEW. A bought interview's report is included in what
 * was bought, so the server never marks one locked and the report page never reaches this
 * component. Nothing here needs to check that, and nothing here should learn to — see
 * `readReportLock`.
 *
 * IT IS ALLOWED TO SELL, AND THE SELLING HAS TO BE TRUE. Every claim on this screen names a
 * field that is actually in the withheld response: the per-question analysis, the four
 * competency scores, the roadmap with its resources, and — the one that matters most to
 * somebody who has just answered badly and knows it — `ideal_answer_summary`, the answer the
 * panel was listening for, per question. That is why the copy can promise "what you should
 * have said" without overselling: it is a real column in a real table. If a claim here ever
 * stops mapping to a field in ReportResponse, the claim is the thing that is wrong.
 *
 * IT IS NOT THE ENFORCEMENT. The server reduced the response before it reached the browser;
 * this renders what is left. Nothing here can be clicked, disabled or edited into revealing a
 * dimension score, because no dimension score was sent — see `ReportLock` in
 * lib/billing/report-unlock.ts, whose smallness is the actual security property. A paywall that
 * is also the enforcement is one `curl` away from not existing, which is the same reason
 * hooks/useBilling.ts opens with that sentence.
 *
 * EVERY MONEY DECISION IS SERVER-SIDE AND IS REACHED THROUGH THE EXISTING MACHINERY. The
 * coupon is validated by `useQuote`, which shares its validation with checkout so the two
 * cannot disagree; the order is opened by `useCheckout`, which sends an item id and never a
 * price; payment is confirmed by `useVerifyPayment`, which checks Razorpay's signature and
 * then asks Razorpay whether the money actually moved; and the entitlement is granted against
 * the credit ledger by the webhook. This component chose none of that and duplicates none of
 * it — it is the pricing page's flow pointed at one off-shelf item
 * (`plans.REPORT_UNLOCK_ITEM`), which is exactly why that item was defined as a normal `Item`.
 *
 * WHAT IS GENUINELY DIFFERENT FROM THE PRICING PAGE, and therefore why the sequence is here
 * rather than shared: the coupon is quoted against a KNOWN item, so the exact total can be
 * shown before they commit instead of "confirmed on the item you choose"; and success does not
 * end in a toast, it ends in a refetch of the report the candidate came here for.
 */

/**
 * The item's copy, local, and allowed to differ in wording from the receipt.
 *
 * `plans.REPORT_UNLOCK_ITEM.name` is what appears in payment history and on the Razorpay
 * statement, because that is the row the ledger wrote. This is what appears on a screen that
 * has already said "report" three times, so it says what is IN the report instead of naming
 * it again. They describe the same purchase; only one of them is a receipt.
 */
const UNLOCK_NAME = 'Your personalised report';
const UNLOCK_TAGLINE = 'Full scorecard, per-question breakdown and study plan.';

/**
 * What ₹49 actually buys, itemised.
 *
 * VAGUE VALUE IS WHAT MAKES A PAYWALL FEEL LIKE A TOLL, so each line names a specific thing
 * that is in the response the server withheld, and the first line is the one candidates
 * actually want: the answer that was being listened for, next to the one they gave. Every
 * entry here maps to a field on ReportResponse — `question_analysis[].ideal_answer_summary`,
 * `dimension_scores`, `performance_percentile`, `improvement_roadmap`. Adding a line that
 * maps to nothing turns honest copy into a lie, so don't.
 */
const INCLUDED: Array<{ icon: typeof ListChecks; text: string }> = [
  {
    icon: MessageSquareQuote,
    text: 'What you should have said — the answer the panel was listening for, next to yours, question by question',
  },
  { icon: ListChecks, text: 'Every answer scored, with the exact gap that cost you the marks' },
  {
    icon: Sparkles,
    text: 'Your four competency scores, and the percentile you would land in against this track',
  },
  { icon: BookOpen, text: 'A study plan with resources, ordered by what will move your score most' },
];

/** The quote fields this screen uses. Structural, so no hook types have to change. */
interface Quoted {
  original_paise: number;
  charged_paise: number;
  is_free: boolean;
  requires_captcha: boolean;
  label: string;
  kind: 'percent' | 'fixed' | 'free' | '';
  value: number;
}

export interface ReportUnlockPaywallProps {
  lock: ReportLock;
  /**
   * Ask the page to refetch the report.
   *
   * THE UNLOCK IS A REFETCH, and that is the whole benefit of gating delivery rather than
   * generation: the report was never not there. Once the ledger says this session is paid
   * for, the same request that returned a teaser returns everything.
   */
  onUnlocked: () => void;
}

export function ReportUnlockPaywall({ lock, onUnlocked }: ReportUnlockPaywallProps) {
  const { session } = useAuth();
  const quote = useQuote();
  const checkout = useCheckout();
  const verify = useVerifyPayment();

  //: The code the SERVER has already priced, not what is in the box. Only a checked code
  //: rides along with a purchase, so a half-typed one cannot.
  const [appliedCode, setAppliedCode] = useState('');
  const [codeInput, setCodeInput] = useState('');
  const [quoted, setQuoted] = useState<Quoted | null>(null);
  const [captchaToken, setCaptchaToken] = useState('');
  const [freeOrderOpen, setFreeOrderOpen] = useState(false);
  /*
   * PAID, BUT THE LEDGER HAS NOT CAUGHT UP YET.
   *
   * Entitlement is granted by Razorpay's webhook, and `POST /billing/verify` is a second
   * independent path precisely because a webhook can be late, blocked, or pointed at the
   * wrong URL. So a refetch immediately after payment can legitimately come back still
   * locked, and this component gets re-rendered with the paywall it just dismissed.
   *
   * That must not look like the payment failing. It is the one moment on this screen where
   * somebody has been charged and has nothing, so the copy switches to "confirmed, unlocking"
   * with a way to look again, and never back to "unlock for ₹50".
   */
  const [paidAwaitingUnlock, setPaidAwaitingUnlock] = useState(false);

  /*
   * THE CLOCK IS READ AFTER MOUNT, NEVER DURING RENDER.
   *
   * `null` until the first effect runs, which means the server-rendered HTML and the first
   * client render agree on a paywall with no countdown in it and the countdown appears a
   * frame later. Reading `Date.now()` during render compares an edge render at one instant
   * against a browser render at another, and that mismatch would land inside the one
   * component on the product that is asking somebody for money.
   */
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    setNow(Date.now());
    const timer = setInterval(() => {
      const t = Date.now();
      setNow(t);
      // Past the deadline the copy is gone for good, so stop waking the tab up every second
      // to render nothing. Nothing else about the paywall changes at this instant.
      if (t >= lock.deadline) clearInterval(timer);
    }, 1_000);
    return () => clearInterval(timer);
  }, [lock.deadline]);

  const ticking = now === null ? null : formatCountdown(countdown(now, lock.deadline));

  const listPaise = lock.pricePaise;
  const payPaise = quoted && appliedCode ? quoted.charged_paise : listPaise;
  const discounted = !!(quoted && appliedCode && payPaise < listPaise);

  /**
   * The unlock as a `StoreItem`, for the ₹0 confirmation sheet.
   *
   * Built from the lock rather than fetched, because this item is deliberately NOT on
   * `GET /billing/items` — see the "ITEMS IS THE SHELF" note in plans.py. A tile advertising
   * a report unlock to somebody who has never sat this interview is an offer they cannot use,
   * so the store does not list it and this screen is the only place it is sold.
   */
  const unlockItem: StoreItem = {
    id: lock.itemId,
    feature: 'report_unlock',
    quantity: 1,
    price_rupees: Math.round(listPaise / 100),
    price_paise: listPaise,
    name: UNLOCK_NAME,
    tagline: UNLOCK_TAGLINE,
  };

  /*
   * THE CODE IS CHECKED AGAINST THE REAL ITEM, and here that is possible.
   *
   * The pricing page has to quote with an empty item id because the candidate has not chosen
   * yet — quoting against an arbitrary item is what once refused a five-pack code while the
   * candidate was looking at the five-pack. Here there is exactly one thing for sale, so the
   * quote names it and comes back with the exact total, `is_free` for this item specifically,
   * and whether this offer wants a captcha before the button is pressed rather than after.
   */
  const applyCode = () => {
    const code = codeInput.trim();
    if (!code) return;
    quote.mutate(
      { itemId: lock.itemId, code },
      {
        onSuccess: (q) => {
          setAppliedCode(code.toUpperCase());
          setQuoted(q);
          toast.success(q.label ? `${q.label} applied.` : 'Code applied.');
        },
        onError: (err) => {
          setAppliedCode('');
          setQuoted(null);
          // An offer error carries a message the candidate can act on — "this offer has
          // expired" rather than "invalid code", which sends them hunting for a typo that is
          // not there. Surfaced verbatim; anything else gets a generic line.
          toast.error(
            err instanceof ApiError && err.status === 400
              ? err.message
              : 'Could not check that code.',
          );
        },
      },
    );
  };

  const clearCode = () => {
    setAppliedCode('');
    setQuoted(null);
    setCodeInput('');
    setCaptchaToken('');
  };

  /*
   * ONE FUNCTION CHECKS OUT, TWO CALL SITES REACH IT — pressing Unlock, and confirming a ₹0
   * order. TanStack's per-call `onSuccess` only fires for the call that passed it, so calling
   * `mutate` a second time from the sheet without repeating these handlers leaves the sheet
   * spinning forever with the item silently granted behind it. That exact bug is pinned by
   * components/billing/free-order.test.ts on the pricing page; this is the same shape, so it
   * gets the same single entry point.
   */
  const runCheckout = () => {
    checkout.mutate(
      { itemId: lock.itemId, code: appliedCode, captchaToken },
      {
        onSuccess: async (order) => {
          /*
           * A FULL-VALUE CODE HAS ALREADY GRANTED IT. Razorpay will not create an order below
           * ₹1, so a 100%-off unlock never becomes an order at all — there is nothing to pay
           * and no sheet to open, and opening the widget here would show a payment form for
           * ₹0. This is the same platform limit every large Indian checkout hits with a
           * full-value coupon, and it is why FreeOrderSheet exists.
           */
          if (order.granted) {
            setFreeOrderOpen(false);
            setPaidAwaitingUnlock(true);
            toast.success('Unlocked with your code. Nothing to pay.');
            onUnlocked();
            return;
          }

          if (!order.order_id || !order.key_id) {
            // Says nothing about WHY. "Add your Razorpay keys" is an instruction to the
            // operator that only ever reached candidates, and it names the provider and
            // admits the integration is unfinished; neither is a student's business. The
            // operator learns this from the logs, where it belongs.
            toast.error('Payments are temporarily unavailable. Please try again shortly.');
            return;
          }

          const opened = await openCheckout({
            orderId: order.order_id,
            amountPaise: order.amount_paise,
            keyId: order.key_id,
            itemName: UNLOCK_NAME,
            prefill: { email: session?.user?.email ?? undefined },
            onSuccess: (proof) => {
              /*
               * NOT PROOF OF PAYMENT, and not treated as any. The server checks Razorpay's
               * signature over these ids, then asks Razorpay whether the money actually
               * moved, then checks the amount against the item. The webhook grants
               * independently, and whichever path arrives second finds the payment already in
               * the ledger and does nothing.
               *
               * The report is refetched either way, because the entitlement may well have
               * landed via the webhook while this call was in flight.
               */
              setPaidAwaitingUnlock(true);
              verify.mutate(proof, {
                onSuccess: () => {
                  toast.success('Payment received — opening your report.');
                  onUnlocked();
                },
                onError: () => {
                  // The webhook is still coming. Saying "it failed" would be wrong and would
                  // send somebody who has just paid to support for something that resolves
                  // itself in seconds.
                  toast.success('Payment received. Your report unlocks in a moment.');
                  onUnlocked();
                },
              });
            },
            onDismiss: () => {
              // Closing the sheet without paying is an ordinary thing to do, not an error.
            },
            onFailure: (reason) => toast.error(reason),
          });

          if (!opened) {
            // A blocked CDN or an ad blocker. Saying so beats a button that appears dead.
            toast.error(
              'Could not load the payment window. Check your connection or any ad blocker, then try again.',
            );
          }
        },
        onError: (err) => {
          setFreeOrderOpen(false);
          const offerMessage = err instanceof ApiError && err.status === 400 ? err.message : null;
          const notConfigured = err instanceof ApiError && err.status === 503;
          toast.error(
            offerMessage ??
              (notConfigured
                ? 'Payments are temporarily unavailable. Please try again shortly.'
                : 'Could not start the payment. Please try again.'),
          );
        },
      },
    );
  };

  const unlock = () => {
    // A code that covers this item in full goes through the confirmation sheet instead of the
    // gateway. `is_free` is trustworthy here because the quote named this exact item.
    if (quoted?.is_free && appliedCode) {
      setFreeOrderOpen(true);
      return;
    }
    runCheckout();
  };

  return (
    <motion.div
      initial="hidden"
      animate="visible"
      variants={staggerContainer(0.08)}
      className="mx-auto max-w-3xl space-y-6 pb-12"
    >
      <motion.div variants={fadeUp}>
        <Card className="p-6">
          <div className="flex flex-col gap-6 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <div className="mb-3 flex flex-wrap items-center gap-2">
                {/* NOT THE DRIVE'S NAME. This screen used to carry the Cognizant Digital
                    Nurture eyebrow, from when the paywall was that one drive's. It is now
                    every free interview's, so a company name here would brand somebody's
                    unrelated practice run as a drive they never sat. What is true of all of
                    them is that the interview was free — so that is what the chip says. */}
                <Badge variant="primary">Free interview</Badge>
                {/* URGENCY COPY ONLY. When the deadline passes this chip disappears and
                    nothing else on this screen changes — same price, same coupon field, same
                    unlock. See lib/billing/report-unlock.ts for why that rule is absolute. */}
                {ticking && (
                  <span className="inline-flex items-center gap-1.5 rounded-full border border-accent-amber/30 bg-accent-amber-soft px-2.5 py-1 text-xs font-semibold tabular-nums text-accent-amber-ink">
                    <Clock className="h-3 w-3" aria-hidden />
                    {ticking} left
                  </span>
                )}
              </div>

              <h1 className="text-2xl font-semibold tracking-[-0.02em] sm:text-3xl">
                Your report is ready
              </h1>

              {/* THE FREE HALF, SAID FIRST AND SAID PLAINLY. This is the part that makes the
                  ask reasonable, and a candidate who reads only one sentence should read
                  this one. */}
              <p className="mt-2 max-w-xl text-sm leading-relaxed text-muted-foreground">
                The interview was free — the panel, the coding round and the scoring cost you
                nothing. The personalised report and study material are{' '}
                <strong className="font-semibold text-foreground">{rupees(listPaise)}</strong>,
                once, for this session.
              </p>

              {/* THE ONE SENTENCE THAT HAS TO LAND, and it is an argument rather than an
                  advertisement. A score on its own changes nothing: a candidate who reads
                  "68/100" and walks away has learnt that they are somewhere in the middle,
                  which they already suspected. What changes the next interview is knowing
                  WHICH answer lost the marks and what the panel wanted instead — and that is
                  precisely the part behind this wall. Saying so is fair; the report really
                  does contain it, per question.

                  Phrased against their own session, with their own numbers, because "unlock
                  your detailed report" is a category and "the 3 answers that cost you the
                  most" is their morning. The count comes from the server. */}
              <p className="mt-3 max-w-xl text-sm leading-relaxed text-foreground/90">
                You know your score. You don&apos;t yet know{' '}
                <strong className="font-semibold">which answers cost you the marks</strong> —
                or what the panel was waiting to hear instead.{' '}
                {lock.questionCount === null
                  ? 'That is what the report tells you, question by question.'
                  : `That is what the report tells you, for all ${lock.questionCount} of them.`}
              </p>
            </div>

            {/* THE TEASER, AND IT IS THE WHOLE TEASER. The score they already want to know,
                and how much report is behind it. Everything else in this response was
                withheld by the server, not hidden by this component. */}
            <div className="flex shrink-0 items-center gap-4 rounded-xl border border-border/60 bg-surface/50 p-4">
              <div className="flex flex-col items-center">
                <span className="text-3xl font-medium tracking-[-0.025em] text-primary tabular-nums">
                  {lock.overallScore === null ? '—' : Math.round(lock.overallScore)}
                </span>
                <span className="text-[10px] text-muted-foreground">/ 100 overall</span>
              </div>
              {lock.questionCount !== null && (
                <div className="flex flex-col items-center border-l border-border/60 pl-4">
                  <span className="text-3xl font-medium tracking-[-0.025em] tabular-nums">
                    {lock.questionCount}
                  </span>
                  <span className="text-[10px] text-muted-foreground">
                    question{lock.questionCount === 1 ? '' : 's'} scored
                  </span>
                </div>
              )}
            </div>
          </div>
        </Card>
      </motion.div>

      {/* PAID, WAITING ON THE LEDGER. Never shows the price again — somebody who has already
          been charged must not be asked a second time. */}
      {paidAwaitingUnlock ? (
        <motion.div variants={fadeUp}>
          <Card className="border-accent-emerald/30 bg-accent-emerald/[0.06] p-6">
            <p className="text-sm font-semibold text-accent-emerald-ink">
              Payment confirmed — your report is unlocking
            </p>
            <p className="mt-1 max-w-xl text-xs leading-relaxed text-muted-foreground">
              Nothing else is needed from you. Confirmation can take a few seconds to reach us,
              and your report opens as soon as it does. Your receipt is in your payment history
              either way.
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              <Button variant="secondary" size="sm" onClick={onUnlocked}>
                Open my report
              </Button>
              <Link
                href="/pricing"
                className="inline-flex items-center gap-1.5 self-center text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
              >
                <Receipt className="h-3.5 w-3.5" aria-hidden />
                Payment history
              </Link>
            </div>
          </Card>
        </motion.div>
      ) : (
        <motion.div variants={fadeUp}>
          <Card className="p-6">
            <div className="mb-5 flex items-center gap-2">
              <div className="flex h-9 w-9 items-center justify-center rounded-full bg-primary/10">
                <Lock className="h-4 w-4 text-primary" aria-hidden />
              </div>
              <h2 className="text-base font-semibold">What unlocking gives you</h2>
            </div>

            <ul className="mb-6 space-y-2.5">
              {INCLUDED.map(({ icon: Icon, text }) => (
                <li key={text} className="flex items-start gap-2.5 text-sm text-foreground/90">
                  <Icon className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden />
                  <span>{text}</span>
                </li>
              ))}
            </ul>

            {/* THE COUPON BOX.
                One box, above the button, because the code applies to the purchase rather
                than to a tile — the same placement and the same reasoning as the pricing
                page. Checked before the button is pressed so an unusable code is refused
                while they are still reading, not at the till. */}
            <div className="mb-6 rounded-2xl border border-border p-4">
              <label
                htmlFor="report-promo"
                className="mb-2 block text-xs font-semibold uppercase tracking-wider text-muted-foreground"
              >
                Have a code?
              </label>
              <div className="flex flex-wrap items-center gap-2">
                <input
                  id="report-promo"
                  value={codeInput}
                  onChange={(e) => setCodeInput(e.target.value.toUpperCase())}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') applyCode();
                  }}
                  placeholder="ENTER CODE"
                  // Uppercased as they type, because the server stores and compares
                  // uppercase. Seeing the code in the form it will actually be checked in
                  // avoids the "but I typed it correctly" class of support message.
                  className="min-w-0 flex-1 rounded-lg border border-border bg-surface-elevated px-3 py-2 font-mono text-sm uppercase tracking-wider focus:border-primary focus:outline-none"
                  maxLength={40}
                />
                <Button
                  variant="secondary"
                  onClick={applyCode}
                  loading={quote.isPending}
                  disabled={!codeInput.trim()}
                >
                  Apply
                </Button>
                {appliedCode && (
                  <button
                    onClick={clearCode}
                    className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                  >
                    Remove
                  </button>
                )}
              </div>

              {quoted && appliedCode && (
                <p className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
                  <span className="inline-flex items-center gap-1.5 font-semibold text-accent-emerald-ink">
                    <Tag className="h-3.5 w-3.5" aria-hidden />
                    {describeOffer(quoted)}
                  </span>
                  {/* THE EXACT TOTAL, because unlike the pricing page this quote named the
                      item. No "confirmed on the item you choose" hedge is needed when there
                      is only one thing for sale. */}
                  <span className="text-muted-foreground">
                    You pay{' '}
                    <strong className="font-semibold text-foreground tabular-nums">
                      {rupees(payPaise)}
                    </strong>
                    {discounted && (
                      <span className="ml-1.5 tabular-nums line-through">
                        {rupees(listPaise)}
                      </span>
                    )}
                  </span>
                </p>
              )}

              {/* Only when this particular offer asks for it, and before the button rather
                  than after — bouncing somebody back with a challenge once they think they
                  are done is how a working captcha loses a sale. */}
              {quoted?.requires_captcha && <Turnstile onToken={setCaptchaToken} />}
            </div>

            <Button
              className="w-full sm:w-auto"
              onClick={unlock}
              loading={checkout.isPending}
              size="lg"
            >
              <Lock className="h-4 w-4" aria-hidden />
              {payPaise === 0
                ? 'Unlock my report'
                : `Unlock my report — ${rupees(payPaise)}`}
            </Button>

            <p className="mt-4 text-xs leading-relaxed text-muted-foreground">
              One payment for this session&apos;s report — not a subscription, and nothing
              renews. Your receipt appears in your{' '}
              <Link
                href="/pricing"
                className="underline decoration-border underline-offset-2 hover:text-foreground"
              >
                payment history
              </Link>{' '}
              with the payment id, and a payment that fails is listed there too.
              {/* THE DEADLINE IS NAMED ONLY WHILE IT IS STILL TRUE, and it is deliberately
                  phrased as their interview slot rather than as a price that expires. The
                  price does not expire — nothing about this paywall changes when the clock
                  runs out — so a sentence promising otherwise would be a hidden expiry
                  advertised in copy, which is the exact thing lib/interview/drive.ts argues
                  at length against. Gated on `ticking` so it goes quiet with the chip
                  instead of standing there advertising a morning that has passed. */}
              {ticking
                ? ` Unlock it before your ${REPORT_UNLOCK_DEADLINE_LABEL} slot so you can revise from it.`
                : ''}
            </p>
          </Card>
        </motion.div>
      )}

      {/* The confirm step for a ₹0 order. Razorpay cannot open below ₹1, so this summary
          takes the payment sheet's place — see FreeOrderSheet for why that is the standard
          behaviour rather than a shortcut. */}
      <FreeOrderSheet
        open={freeOrderOpen}
        item={unlockItem}
        code={appliedCode}
        originalPaise={listPaise}
        confirming={checkout.isPending}
        onCancel={() => setFreeOrderOpen(false)}
        onConfirm={runCheckout}
      />
    </motion.div>
  );
}

export default ReportUnlockPaywall;
