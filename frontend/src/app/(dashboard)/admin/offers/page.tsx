'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2, Plus, ShieldCheck, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { OfferBannerControl, type OfferBanner } from '@/components/admin/OfferBannerControl';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { PageHeader } from '@/components/ui/page-header';
import { useStoreItems } from '@/hooks/useBilling';
import { formatDate } from '@/lib/format-date';
import { getBrowserApiClient } from '@/lib/api';
import { ApiError } from '@/lib/api/errors';
import { cn } from '@/lib/utils';

/*
 * REQUIRED BY CLOUDFLARE PAGES, and its absence broke the deploy.
 *
 * Every non-static route in this app must opt into the Edge Runtime — @cloudflare/next-on-pages
 * refuses to produce a build otherwise, and the failure names the route:
 *
 *     ERROR: Failed to produce a Cloudflare Pages build from the project.
 *         The following routes were not configured to run with the Edge Runtime:
 *           - /admin/offers
 *
 * `next build` passes without it, which is what makes it easy to miss: the whole frontend
 * stopped deploying the moment this page was added, so every fix after it sat unshipped
 * while looking merged. tests/edge-runtime.test.ts now fails on any route missing this.
 */
export const runtime = 'edge';

/**
 * Offers and promo codes — app/(dashboard)/admin/offers/page.tsx
 *
 * THE SWITCH IS THE POINT OF THIS PAGE. A private 100%-off code given to friends needs to be
 * turnable off and back on without losing who has already used it, and that is one toggle
 * here rather than a deploy. Turning it off stops it working for everybody on the next
 * request, including anyone already quoted a discount.
 *
 * DELETION IS REFUSED ONCE A CODE HAS BEEN USED, and the server enforces that — the
 * redemptions are the audit trail for revenue given away, and the foreign key cascades. The
 * button is hidden rather than shown-and-failing, but the server would refuse it anyway;
 * this page is a convenience over that rule, never the thing that holds it.
 *
 * EVERY FIELD THAT DECIDES MONEY IS SET AT CREATION AND NOT EDITABLE AFTERWARDS. Changing
 * what a code MEANS after people have used it makes the redemption rows a lie: they record
 * what was charged under the old terms while the offer claims different ones. Switch it off
 * and make a new code.
 */

interface Offer {
  id: string;
  code: string;
  label: string;
  kind: 'percent' | 'fixed' | 'free';
  value: number;
  applies_to: string[];
  enabled: boolean;
  is_public: boolean;
  starts_at: string | null;
  ends_at: string | null;
  max_redemptions: number | null;
  requires_captcha: boolean;
  redemptions: number;
  discount_given_rupees: number;
  /**
   * Why this offer refuses every purchase, or "" when nothing is wrong.
   *
   * Computed server-side because the cause is a server-side setting the browser cannot
   * see: an offer requiring a captcha on a deployment with no TURNSTILE_SECRET_KEY. The
   * backend knows both halves; the browser knows neither.
   */
  blocked_reason: string;
  /** The promo image for this offer, or null. See OfferBannerControl. */
  banner: OfferBanner | null;
}

/**
 * What a preview row looks like. Mirrors PreviewRow on POST /admin/offers/preview.
 *
 * The admin sees the same figures the created code would produce, because the endpoint prices
 * an unpersisted offer with the same two functions the till uses — `covers` for scope and
 * `charge_for` for the amount.
 */
interface PreviewRow {
  item_id: string;
  feature: string;
  name: string;
  quantity: number;
  price_paise: number;
  charged_paise: number;
  covered: boolean;
}

//: The three features a code can be scoped to. There is no report product — the unlock was
//: removed — so a fourth box here would be a scope over an item that does not exist, which,
//: because an empty scope means EVERY item, would silently produce an unrestricted code.
const FEATURES = [
  { id: 'interview', label: 'Mock interviews' },
  { id: 'gd', label: 'Group discussions' },
  { id: 'communication', label: 'Communication drills' },
] as const;

const BLANK = {
  code: '',
  label: '',
  kind: 'percent' as 'percent' | 'fixed' | 'free',
  value: 25,
  enabled: true,
  is_public: true,
  requires_captcha: false,
  max_redemptions: '' as string | number,
  starts_at: '',
  ends_at: '',
  /**
   * Which ITEMS the code covers. EMPTY MEANS EVERY ITEM.
   *
   * PER ITEM, NOT PER FEATURE, and the difference is money. A feature contains both the
   * single and the bundle — "mock interviews" is the ₹49 one AND the ₹199 five-pack — so a
   * feature-level scope cannot express "singles only". A flat ₹25 code scoped to the feature
   * prices the five-pack at ₹25 too, which sells five interviews for less than one.
   *
   * The empty default is the pre-existing behaviour of every offer ever created — `applies_to`
   * empty has always meant "applies to everything" — and it is also the trap: an admin who
   * ticks nothing has not made a narrow code, they have made a store-wide one. The form says
   * so in words rather than relying on them knowing it.
   */
  applies_to: [] as string[],
};

function describe(o: Offer): string {
  if (o.kind === 'free') return '100% off';
  if (o.kind === 'fixed') return `₹${Math.round(o.value / 100)} flat`;
  return `${o.value}% off`;
}

export default function AdminOffersPage() {
  const qc = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ ...BLANK });

  const offers = useQuery({
    queryKey: ['admin', 'offers'],
    queryFn: async () =>
      (await getBrowserApiClient().get('/api/v1/admin/offers')).data as Offer[],
  });

  // The real catalogue, so the scope list and the prices beside it come from the server
  // rather than a second copy of the price list living in an admin screen.
  const storeItems = useStoreItems();

  const invalidate = () => void qc.invalidateQueries({ queryKey: ['admin', 'offers'] });

  /*
   * WHAT THIS CODE WILL ACTUALLY DO, priced before it exists.
   *
   * "40% off, drills only" is a sentence. ₹19 becoming ₹11 is a decision, and it is the one
   * the admin is really making. Two mistakes this catches, both silent and both expensive: a
   * percentage that rounds to a figure nobody intended, and a scope that covers more than it
   * reads like it does — ticking nothing means EVERY feature, so "I did not choose" and "I
   * discounted the whole catalogue" are the same request.
   *
   * Keyed on exactly the three fields that decide money, so it re-runs when any of them
   * changes and not when the label or the dates do. The endpoint writes nothing.
   */
  const previewValue =
    form.kind === 'fixed' ? Math.round(Number(form.value) * 100) : Number(form.value);
  const preview = useQuery({
    queryKey: ['admin', 'offers', 'preview', form.kind, previewValue, form.applies_to],
    enabled: creating && Number.isFinite(previewValue) && previewValue >= 0,
    queryFn: async () =>
      (
        await getBrowserApiClient().post('/api/v1/admin/offers/preview', {
          kind: form.kind,
          value: previewValue,
          applies_to: form.applies_to,
        })
      ).data as PreviewRow[],
  });

  const toggleItem = (id: string) =>
    setForm((f) => ({
      ...f,
      applies_to: f.applies_to.includes(id)
        ? f.applies_to.filter((x) => x !== id)
        : [...f.applies_to, id],
    }));

  const setScope = (ids: string[]) => setForm((f) => ({ ...f, applies_to: ids }));

  const create = useMutation({
    mutationFn: async () => {
      const body: Record<string, unknown> = {
        code: form.code.trim().toUpperCase(),
        label: form.label.trim() || form.code.trim().toUpperCase(),
        kind: form.kind,
        // Rupees in the form, paise on the wire. Prices are integers in paise everywhere
        // server-side — a rupee figure as a float is a rounding bug waiting for ₹49.50.
        value: form.kind === 'fixed' ? Math.round(Number(form.value) * 100) : Number(form.value),
        enabled: form.enabled,
        is_public: form.is_public,
        requires_captcha: form.requires_captcha,
        max_redemptions: form.max_redemptions === '' ? null : Number(form.max_redemptions),
        starts_at: form.starts_at ? new Date(form.starts_at).toISOString() : null,
        ends_at: form.ends_at ? new Date(form.ends_at).toISOString() : null,
        // Item ids outright. `OfferTerms.scope` unions this with any features, and the
        // preview reads the same property, so what the admin approved is what gets written.
        applies_to: form.applies_to,
      };
      return (await getBrowserApiClient().post('/api/v1/admin/offers', body)).data;
    },
    onSuccess: () => {
      toast.success('Offer created.');
      setForm({ ...BLANK });
      setCreating(false);
      invalidate();
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : 'Could not create that offer.'),
  });

  const toggle = useMutation({
    mutationFn: async (args: { id: string; enabled: boolean }) =>
      (await getBrowserApiClient().patch(`/api/v1/admin/offers/${args.id}`, {
        enabled: args.enabled,
      })).data,
    onSuccess: (_d, args) => {
      toast.success(args.enabled ? 'Code is live.' : 'Code is off. Nobody can use it now.');
      invalidate();
    },
    onError: () => toast.error('Could not change that.'),
  });

  /*
   * THE CAPTCHA SWITCH, WHICH DID NOT EXIST AND LEFT OFFERS UNFIXABLE.
   *
   * `requires_captcha` could be SET when creating an offer and never cleared afterwards:
   * the create form had the checkbox, the list showed a badge, and the only PATCH this page
   * sent was `{enabled}`. The backend accepted the field the whole time.
   *
   * That is worse than a missing feature, because of how the flag fails. An offer requiring
   * a captcha on a deployment with no TURNSTILE_SECRET_KEY refuses every purchase — the
   * server is right to fail closed rather than waive a check the offer was priced on — so
   * the code is simultaneously live and unusable. With no way to clear the flag, the only
   * remedies were deleting the offer (refused once anyone has redeemed it, to protect the
   * single-use record) or a hand-written UPDATE against production, which is the exact
   * situation an admin panel exists to avoid.
   *
   * Turning it OFF is always safe. Turning it ON without Turnstile configured is what
   * created the trap, so that direction is confirmed rather than silent.
   */
  const captcha = useMutation({
    mutationFn: async (args: { id: string; requires: boolean }) =>
      (await getBrowserApiClient().patch(`/api/v1/admin/offers/${args.id}`, {
        requires_captcha: args.requires,
      })).data,
    onSuccess: (_d, args) => {
      toast.success(
        args.requires
          ? 'Captcha required. Purchases will refuse until Turnstile is configured.'
          : 'Captcha requirement removed. This code can be used now.',
      );
      invalidate();
    },
    onError: () => toast.error('Could not change that.'),
  });

  const remove = useMutation({
    mutationFn: async (id: string) =>
      (await getBrowserApiClient().delete(`/api/v1/admin/offers/${id}`)).data,
    onSuccess: () => {
      toast.success('Offer deleted.');
      invalidate();
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : 'Could not delete that offer.'),
  });

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
      <PageHeader
        eyebrow="Admin"
        tone="amber"
        title="Offers & promo codes"
        description="Festival offers, launch pricing, and private codes you can switch off."
      />

      <div className="mb-6 flex justify-end">
        <Button onClick={() => setCreating((c) => !c)} variant={creating ? 'secondary' : 'primary'}>
          <Plus className="h-4 w-4" /> {creating ? 'Cancel' : 'New offer'}
        </Button>
      </div>

      {creating && (
        <Card className="mb-8 p-5">
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="text-sm">
              <span className="mb-1 block font-medium">Code</span>
              <input
                value={form.code}
                onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase() })}
                placeholder="DIWALI25"
                className="w-full rounded-lg border border-border bg-surface-elevated px-3 py-2 font-mono uppercase tracking-wider"
              />
            </label>
            <label className="text-sm">
              <span className="mb-1 block font-medium">Label (admin only)</span>
              <input
                value={form.label}
                onChange={(e) => setForm({ ...form, label: e.target.value })}
                placeholder="Diwali 2026"
                className="w-full rounded-lg border border-border bg-surface-elevated px-3 py-2"
              />
            </label>

            <label className="text-sm">
              <span className="mb-1 block font-medium">Type</span>
              <select
                value={form.kind}
                onChange={(e) =>
                  setForm({ ...form, kind: e.target.value as typeof form.kind })
                }
                className="w-full rounded-lg border border-border bg-surface-elevated px-3 py-2"
              >
                <option value="percent">Percent off</option>
                <option value="fixed">Flat price (₹)</option>
                <option value="free">Free — 100% off</option>
              </select>
            </label>

            {form.kind !== 'free' && (
              <label className="text-sm">
                <span className="mb-1 block font-medium">
                  {form.kind === 'percent' ? 'Percent (1–100)' : 'Price in ₹'}
                </span>
                <input
                  type="number"
                  value={form.value}
                  onChange={(e) => setForm({ ...form, value: Number(e.target.value) })}
                  className="w-full rounded-lg border border-border bg-surface-elevated px-3 py-2 tabular-nums"
                />
              </label>
            )}

            <label className="text-sm">
              <span className="mb-1 block font-medium">Starts (optional)</span>
              <input
                type="datetime-local"
                value={form.starts_at}
                onChange={(e) => setForm({ ...form, starts_at: e.target.value })}
                className="w-full rounded-lg border border-border bg-surface-elevated px-3 py-2"
              />
            </label>
            <label className="text-sm">
              <span className="mb-1 block font-medium">Ends (optional)</span>
              <input
                type="datetime-local"
                value={form.ends_at}
                onChange={(e) => setForm({ ...form, ends_at: e.target.value })}
                className="w-full rounded-lg border border-border bg-surface-elevated px-3 py-2"
              />
            </label>

            <label className="text-sm">
              <span className="mb-1 block font-medium">Total uses allowed (blank = unlimited)</span>
              <input
                type="number"
                value={form.max_redemptions}
                onChange={(e) => setForm({ ...form, max_redemptions: e.target.value })}
                className="w-full rounded-lg border border-border bg-surface-elevated px-3 py-2 tabular-nums"
              />
            </label>
          </div>

          <div className="mt-4 flex flex-wrap gap-4 text-sm">
            {/* PUBLIC vs PRIVATE is the friends-code switch. A private code never appears in
                any public response — it exists only for whoever is told it. */}
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={form.is_public}
                onChange={(e) => setForm({ ...form, is_public: e.target.checked })}
              />
              Show publicly (uncheck for a private code)
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={form.requires_captcha}
                onChange={(e) => setForm({ ...form, requires_captcha: e.target.checked })}
              />
              Require captcha
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={form.enabled}
                onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
              />
              Live immediately
            </label>
          </div>

          {/* ── WHAT THE CODE APPLIES TO, PER ITEM ─────────────────────────────────────
              PER ITEM RATHER THAN PER FEATURE, because a feature holds both the single and
              the bundle and the difference between them is the whole point. "Mock interviews"
              is the ₹49 one AND the ₹199 five-pack; a flat ₹25 code scoped to the feature
              prices the five-pack at ₹25, selling five interviews for half the price of one.
              A percentage is safe either way, a flat price is not, and the form cannot know
              which the admin will pick — so the scope has to be able to say "singles only". */}
          <div className="mt-5 border-t border-border/60 pt-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className="text-sm font-medium text-foreground">Applies to</p>
              {/* The two scopes worth one tap. "Singles only" is the common case for a flat
                  code and the one that is dangerous to get wrong by hand. */}
              <div className="flex gap-3 text-xs">
                <button
                  type="button"
                  className="font-semibold text-primary hover:underline"
                  onClick={() =>
                    setScope((storeItems.data ?? []).filter((i) => i.quantity === 1).map((i) => i.id))
                  }
                >
                  Singles only
                </button>
                <button
                  type="button"
                  className="font-semibold text-primary hover:underline"
                  onClick={() => setScope([])}
                >
                  Everything
                </button>
              </div>
            </div>

            <div className="mt-2 space-y-3">
              {FEATURES.map((f) => {
                const items = (storeItems.data ?? []).filter((i) => i.feature === f.id);
                if (items.length === 0) return null;
                return (
                  <div key={f.id}>
                    <p className="text-[11px] font-mono uppercase tracking-[0.14em] text-muted-foreground">
                      {f.label}
                    </p>
                    <div className="mt-1 flex flex-wrap gap-x-5 gap-y-1.5 text-sm">
                      {items.map((i) => (
                        <label key={i.id} className="flex items-center gap-2">
                          <input
                            type="checkbox"
                            checked={form.applies_to.includes(i.id)}
                            onChange={() => toggleItem(i.id)}
                          />
                          <span>
                            {i.name}{' '}
                            {/* The price is shown because it is the thing being scoped, and
                                it comes from the server rather than being typed here. */}
                            <span className="text-muted-foreground">₹{i.price_rupees}</span>
                          </span>
                        </label>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* SAID OUT LOUD, because the default is the dangerous one. An empty scope has
                always meant every item, so an admin who ticks nothing has made a store-wide
                code — not a narrow one. */}
            <p className="mt-2 text-xs text-muted-foreground">
              {form.applies_to.length === 0
                ? 'Nothing ticked — this code will apply to EVERY product in the store, bundles included.'
                : `Only ${form.applies_to.length} product${form.applies_to.length === 1 ? '' : 's'}. Everything else stays at full price.`}
            </p>

            {/* THE ONE COMBINATION THAT LOSES MONEY, named while it can still be changed. A
                flat price reaching a bundle charges bundle-many sessions at single-item money.
                A warning rather than a block: "₹99 flat on the five-pack" is a legitimate
                thing to want, and only the person typing it knows which they meant. */}
            {form.kind === 'fixed' &&
              (form.applies_to.length === 0 ||
                (storeItems.data ?? []).some(
                  (i) => i.quantity > 1 && form.applies_to.includes(i.id),
                )) && (
                <p className="mt-2 rounded-lg border border-accent-amber/40 bg-accent-amber/10 px-3 py-2 text-xs leading-relaxed text-accent-amber-ink">
                  This is a FLAT price and it reaches a bundle. Every pack it covers will cost
                  ₹{Number(form.value) || 0} however many sessions it contains — check the
                  figures below before creating it.
                </p>
              )}
          </div>

          {/* ── WHAT EACH THING WILL COST ───────────────────────────────────────────────
              The whole catalogue under these terms, priced by the server with the same
              functions the till uses. This is the confirmation step: the admin sees the real
              figures before the code exists, rather than after somebody has redeemed it. */}
          <div className="mt-4 rounded-xl border border-border/60 bg-surface-elevated p-4">
            <p className="text-sm font-medium text-foreground">Price after this code</p>
            {preview.isLoading && (
              <p className="mt-2 text-xs text-muted-foreground">Pricing…</p>
            )}
            {preview.isError && (
              <p className="mt-2 text-xs text-accent-coral-ink">
                Could not price these terms. Check the value.
              </p>
            )}
            {preview.data && (
              <ul className="mt-2 space-y-1.5">
                {preview.data.map((row) => {
                  const from = Math.round(row.price_paise / 100);
                  const to = Math.round(row.charged_paise / 100);
                  return (
                    <li
                      key={row.item_id}
                      className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 text-sm"
                    >
                      <span className="min-w-0 text-muted-foreground">{row.name}</span>
                      <span className="tabular-nums">
                        {row.covered && to !== from ? (
                          <>
                            <span className="text-muted-foreground line-through">₹{from}</span>{' '}
                            <span className="font-semibold text-accent-emerald-ink">₹{to}</span>
                          </>
                        ) : (
                          /* Shown rather than hidden. A list of only the discounted items
                             cannot answer "what did I NOT discount", which is the half of the
                             question a scope is actually about. */
                          <span className="text-muted-foreground">₹{from} — unchanged</span>
                        )}
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          <p className="mt-4 text-xs leading-relaxed text-muted-foreground">
            The code, its type and its value cannot be edited afterwards — changing what a
            code means once people have used it makes the redemption record disagree with the
            offer. Switch it off and make a new one instead. Everything else here is editable.
          </p>

          <div className="mt-4 flex justify-end">
            <Button
              onClick={() => create.mutate()}
              loading={create.isPending}
              // Not creatable until the figures above have loaded. The button says "create
              // with these prices", so it must not be pressable before there are any.
              disabled={!form.code.trim() || preview.isLoading || !preview.data}
            >
              Create offer with these prices
            </Button>
          </div>
        </Card>
      )}

      {offers.isLoading ? (
        <div className="flex justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : offers.isError ? (
        /* A FAILED QUERY IS NOT AN EMPTY LIST, and conflating them here would tell a
           non-admin who navigated straight to this URL that there are no offers — implying
           they have access and there is simply nothing to see. The server refuses them with
           a 403; this says so. Every endpoint is gated by `AdminUser` regardless, so this is
           honesty about what happened rather than the thing enforcing it. */
        <Card className="p-10 text-center text-sm text-muted-foreground">
          {offers.error instanceof ApiError && offers.error.status === 403
            ? 'This page is for administrators.'
            : 'Could not load offers. Please try again.'}
        </Card>
      ) : !offers.data?.length ? (
        <Card className="p-10 text-center text-sm text-muted-foreground">
          No offers yet.
        </Card>
      ) : (
        <div className="space-y-3">
          {offers.data.map((o) => (
            <Card key={o.id} className="flex flex-wrap items-center gap-4 p-4">
              <div className="min-w-0 flex-1">
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  <span className="font-mono text-sm font-semibold tracking-wider">
                    {o.code}
                  </span>
                  <Badge variant={o.kind === 'free' ? 'violet' : 'primary'}>
                    {describe(o)}
                  </Badge>
                  {!o.is_public && <Badge variant="neutral">private</Badge>}
                  {o.requires_captcha && <Badge variant="warning">captcha</Badge>}
                  {o.ends_at && (
                    <span className="text-[11px] text-muted-foreground">
                      ends {formatDate(o.ends_at)}
                    </span>
                  )}
                </div>
                <p className="text-xs text-muted-foreground">
                  {o.label} · used {o.redemptions}
                  {o.max_redemptions ? ` / ${o.max_redemptions}` : ''} time
                  {o.redemptions === 1 ? '' : 's'}
                  {o.discount_given_rupees > 0 && ` · ₹${o.discount_given_rupees} given away`}
                </p>

                {/* WHY THIS CODE REFUSES EVERYONE, said on the row rather than left to be
                    discovered by a candidate who cannot act on it. `enabled` can be true
                    while this is set, and that combination is the trap: the row reads
                    healthy and every purchase fails. */}
                {o.blocked_reason && (
                  <p className="mt-2 rounded-md border border-accent-amber/40 bg-accent-amber/10 px-3 py-2 text-xs text-accent-amber-ink">
                    {o.blocked_reason}
                  </p>
                )}

                {/* THE BANNER, ONLY WHERE IT CAN DO ANYTHING.
                    A banner advertises a code to every candidate on the dashboard, so it only
                    makes sense on a PUBLIC offer — a private code shared with four friends
                    must not be posted product-wide, and the server enforces that by filtering
                    on `is_public` when it decides what to serve. Offering the upload on a
                    private offer would be offering something that could never appear. */}
                {o.is_public && <OfferBannerControl offerId={o.id} banner={o.banner} />}
              </div>

              {/* THE SWITCH. One tap, immediate, and it keeps the redemption history — which
                  is why it is a toggle rather than delete-and-recreate: recreating would
                  reset the single-use record and let everybody claim again. */}
              <button
                onClick={() => toggle.mutate({ id: o.id, enabled: !o.enabled })}
                disabled={toggle.isPending}
                className={cn(
                  'inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors',
                  o.enabled
                    ? 'border-accent-emerald/40 bg-accent-emerald/10 text-accent-emerald-ink'
                    : 'border-border text-muted-foreground hover:text-foreground',
                )}
              >
                <span
                  className={cn(
                    'h-1.5 w-1.5 rounded-full',
                    o.enabled ? 'bg-accent-emerald-ink' : 'bg-muted-foreground/50',
                  )}
                />
                {o.enabled ? 'Live' : 'Off'}
              </button>

              {/* Turning the requirement OFF needs no confirmation — it can only make a
                  refusing code work. Turning it ON while Turnstile is unconfigured is the
                  move that silently breaks an offer, so that direction asks first. */}
              <button
                onClick={() => {
                  if (
                    !o.requires_captcha &&
                    !window.confirm(
                      'Require a captcha for this code?\n\nIf Cloudflare Turnstile is not ' +
                        'configured on this deployment, every purchase using this code will ' +
                        'be refused until it is.',
                    )
                  ) {
                    return;
                  }
                  captcha.mutate({ id: o.id, requires: !o.requires_captcha });
                }}
                disabled={captcha.isPending}
                title={
                  o.requires_captcha
                    ? 'Buyers must pass a Cloudflare Turnstile check. Click to remove.'
                    : 'No human check. Click to require one.'
                }
                className={cn(
                  'inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors',
                  o.requires_captcha
                    ? 'border-accent-amber/40 bg-accent-amber/10 text-accent-amber-ink'
                    : 'border-border text-muted-foreground hover:text-foreground',
                )}
              >
                <ShieldCheck className="h-3.5 w-3.5" />
                {o.requires_captcha ? 'Captcha on' : 'Captcha off'}
              </button>

              {/* Hidden once used. The server refuses it too — this only avoids offering a
                  button that cannot work. */}
              {o.redemptions === 0 && (
                <button
                  onClick={() => remove.mutate(o.id)}
                  disabled={remove.isPending}
                  aria-label={`Delete ${o.code}`}
                  className="rounded-lg p-2 text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
