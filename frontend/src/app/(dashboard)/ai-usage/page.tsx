'use client';

/**
 * TEMPORARY — what each AI feature costs. /ai-usage
 *
 * Removed with the rest of the ledger once credits and subscriptions land; see
 * `TEMPORARY-token-counter.md` at the repo root.
 *
 * It exists to answer one question with arithmetic instead of a guess: what does
 * a user cost, and which feature is spending the money. The per-user median and
 * p95 at the bottom are the numbers a credit price has to cover.
 *
 * ADMIN ONLY. The endpoint returns 403 for a normal account and 404 when the
 * ledger is switched off, so this page renders a plain "not available" rather
 * than an error — a non-admin who guesses the URL learns nothing.
 *
 * NO CHART. A twelve-row table of money is faster to read as a table, and every
 * number here is one someone will want to copy into a spreadsheet. A bar chart
 * of twelve values with a long tail is harder to read than the sorted list it
 * was made from.
 */

import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { AlertTriangle, Coins, Percent, Trash2, TrendingDown } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { PageHeader } from '@/components/ui/page-header';
import { StatCard } from '@/components/ui/stat-card';
import { Badge } from '@/components/ui/badge';
import { ApiError, getBrowserApiClient } from '@/lib/api';
import { cn } from '@/lib/utils';

export const runtime = 'edge';

interface FeatureRow {
  feature: string;
  label: string;
  calls: number;
  input_tokens: number;
  cached_input_tokens: number;
  cache_write_tokens: number;
  output_tokens: number;
  cost_usd: number;
  avg_cost_per_call_usd: number;
  discarded_cost_usd: number;
  discarded_calls: number;
  share_pct: number;
}

interface UsageReport {
  temporary: boolean;
  note: string;
  window_days: number;
  totals: {
    calls: number;
    input_tokens: number;
    cached_input_tokens: number;
    cache_write_tokens: number;
    output_tokens: number;
    cost_usd: number;
    discarded_cost_usd: number;
    discarded_calls: number;
  };
  by_feature: FeatureRow[];
  by_model: { provider: string; model: string; calls: number; cost_usd: number }[];
  by_day: { day: string; calls: number; cost_usd: number }[];
  per_user: {
    users_with_spend: number;
    mean_cost_usd: number;
    median_cost_usd: number;
    p95_cost_usd: number;
    max_cost_usd: number;
    unattributed_cost_usd: number;
  };
  daily_budget_usd: number;
}

const WINDOWS = [7, 30, 90] as const;

/**
 * Money, at the precision the number deserves.
 *
 * A single cross-question costs about $0.0004 and a month of totals runs to
 * dollars. Formatting both to two decimals turns every per-call figure into
 * "$0.00", which reads as free — and "free" is the one conclusion this page
 * exists to disprove.
 */
function usd(v: number): string {
  if (v === 0) return '$0';
  if (v < 0.01) return `$${v.toFixed(5)}`;
  if (v < 1) return `$${v.toFixed(4)}`;
  return `$${v.toFixed(2)}`;
}

function tokens(v: number): string {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}k`;
  return String(v);
}

export default function AIUsagePage() {
  const [days, setDays] = useState<number>(30);

  const { data, isLoading, error } = useQuery({
    queryKey: ['ai-usage', days],
    queryFn: async () => {
      const r = await getBrowserApiClient().get(`/api/v1/ai-usage?days=${days}`);
      return r.data as UsageReport;
    },
    staleTime: 60_000,
  });

  // 403 (not an admin) and 404 (ledger off) are both "you should not be looking
  // at this", not failures. Anything else is a real error worth showing.
  const status = error instanceof ApiError ? error.status : undefined;
  if (status === 403 || status === 404) {
    return (
      <div className="mx-auto max-w-xl py-16 text-center">
        <h1 className="text-lg font-medium">Not available</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          This page shows internal AI cost data and is limited to admin accounts.
        </p>
      </div>
    );
  }

  const cacheSaving =
    data && data.totals.input_tokens + data.totals.cached_input_tokens > 0
      ? (data.totals.cached_input_tokens /
          (data.totals.input_tokens + data.totals.cached_input_tokens)) *
        100
      : 0;

  const wastePct =
    data && data.totals.cost_usd > 0
      ? (data.totals.discarded_cost_usd / data.totals.cost_usd) * 100
      : 0;

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Temporary · admin"
        title="AI cost by feature"
        description="What each AI-backed feature spends, so a credit price can be set from measurement rather than estimate. Removed once credits and subscriptions ship."
        actions={
          <div className="flex items-center gap-1 rounded-lg border border-border bg-surface-elevated p-1">
            {WINDOWS.map((w) => (
              <button
                key={w}
                type="button"
                onClick={() => setDays(w)}
                className={cn(
                  'rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
                  days === w
                    ? 'bg-accent-indigo text-white'
                    : 'text-muted-foreground hover:text-foreground',
                )}
              >
                {w}d
              </button>
            ))}
          </div>
        }
      />

      {/* Says out loud that this is scheduled for deletion, so nobody builds on it. */}
      <Card variant="flat" padding="sm" className="flex items-start gap-3">
        <Trash2 className="mt-0.5 h-4 w-4 shrink-0 text-accent-amber-ink" />
        <p className="text-xs leading-relaxed text-muted-foreground">
          <span className="font-medium text-foreground">Temporary instrumentation.</span>{' '}
          Costs are estimated from provider-reported token counts and the price sheet in{' '}
          <code className="text-[11px]">anthropic_provider._PRICE_PER_MTOK</code> — a close
          upper bound, not an invoice. This whole feature is removed when billing lands;
          see <code className="text-[11px]">TEMPORARY-token-counter.md</code>.
        </p>
      </Card>

      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}

      {error && status !== 403 && status !== 404 && (
        <Card variant="flat" className="border-accent-coral/25 bg-accent-coral-soft">
          <p className="text-sm text-accent-coral-ink">
            Could not load usage: {(error as Error).message}
          </p>
        </Card>
      )}

      {data && (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <StatCard
              label={`Spend · last ${data.window_days}d`}
              value={usd(data.totals.cost_usd)}
              sub={`${data.totals.calls.toLocaleString()} billed calls`}
              icon={<Coins className="h-4 w-4" />}
              color="blue"
            />
            <StatCard
              label="Cost per user"
              value={usd(data.per_user.median_cost_usd)}
              sub={`median · p95 ${usd(data.per_user.p95_cost_usd)}`}
              icon={<Percent className="h-4 w-4" />}
              color="emerald"
            />
            <StatCard
              label="Wasted on discards"
              value={usd(data.totals.discarded_cost_usd)}
              sub={`${wastePct.toFixed(1)}% of spend · ${data.totals.discarded_calls} calls`}
              icon={<AlertTriangle className="h-4 w-4" />}
              color={data.totals.discarded_cost_usd > 0 ? 'red' : 'emerald'}
            />
            <StatCard
              label="Served from cache"
              value={`${cacheSaving.toFixed(0)}%`}
              sub="of input tokens, billed at 0.1x"
              icon={<TrendingDown className="h-4 w-4" />}
              color="cyan"
            />
          </div>

          {/* ── The main table ─────────────────────────────────────────────── */}
          <Card variant="outline" padding="none" className="overflow-hidden">
            <div className="border-b border-border px-5 py-4">
              <h2 className="text-sm font-semibold">By feature</h2>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Sorted by total spend. Cost per call is what to optimise on; share is
                what to optimise first.
              </p>
            </div>

            {/* Money tables must scroll inside themselves rather than widen the page. */}
            <div className="overflow-x-auto">
              <table className="w-full min-w-[820px] text-sm">
                <thead>
                  <tr className="border-b border-border text-left font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                    <th className="px-5 py-2.5 font-normal">Feature</th>
                    <th className="px-3 py-2.5 text-right font-normal">Calls</th>
                    <th className="px-3 py-2.5 text-right font-normal">In</th>
                    <th className="px-3 py-2.5 text-right font-normal">Out</th>
                    <th className="px-3 py-2.5 text-right font-normal">Per call</th>
                    <th className="px-3 py-2.5 text-right font-normal">Wasted</th>
                    <th className="px-3 py-2.5 text-right font-normal">Total</th>
                    <th className="px-5 py-2.5 text-right font-normal">Share</th>
                  </tr>
                </thead>
                <tbody>
                  {data.by_feature.length === 0 && (
                    <tr>
                      <td colSpan={8} className="px-5 py-10 text-center text-sm text-muted-foreground">
                        No AI calls recorded in this window.
                      </td>
                    </tr>
                  )}
                  {data.by_feature.map((f) => (
                    <tr key={f.feature} className="border-b border-border/60 last:border-0">
                      <td className="px-5 py-3">
                        <p className="font-medium">{f.label}</p>
                        <p className="mt-0.5 font-mono text-[10px] text-muted-foreground">
                          {f.feature}
                        </p>
                      </td>
                      <td className="px-3 py-3 text-right tabular-nums">{f.calls}</td>
                      <td className="px-3 py-3 text-right tabular-nums text-muted-foreground">
                        {tokens(f.input_tokens + f.cached_input_tokens)}
                      </td>
                      <td className="px-3 py-3 text-right tabular-nums text-muted-foreground">
                        {tokens(f.output_tokens)}
                      </td>
                      <td className="px-3 py-3 text-right tabular-nums">
                        {usd(f.avg_cost_per_call_usd)}
                      </td>
                      <td className="px-3 py-3 text-right tabular-nums">
                        {f.discarded_cost_usd > 0 ? (
                          <span className="text-accent-coral-ink">
                            {usd(f.discarded_cost_usd)}
                          </span>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </td>
                      <td className="px-3 py-3 text-right font-medium tabular-nums">
                        {usd(f.cost_usd)}
                      </td>
                      <td className="px-5 py-3 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <span className="tabular-nums text-muted-foreground">
                            {f.share_pct}%
                          </span>
                          {/* A bar per row, not a chart: it makes the ranking
                              scannable without a second reading of the numbers. */}
                          <span className="h-1.5 w-16 overflow-hidden rounded-full bg-border">
                            <span
                              className="block h-full rounded-full bg-accent-indigo"
                              style={{ width: `${Math.min(f.share_pct, 100)}%` }}
                            />
                          </span>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            {/* ── Pricing a credit ────────────────────────────────────────── */}
            <Card variant="outline">
              <h2 className="text-sm font-semibold">Cost per user</h2>
              <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                Price to the median and the tail loses money; price to the mean and it
                still does, because usage is long-tailed. p95 is what a flat monthly
                price has to survive.
              </p>
              <dl className="mt-4 space-y-2.5">
                {[
                  ['Users with spend', String(data.per_user.users_with_spend)],
                  ['Median', usd(data.per_user.median_cost_usd)],
                  ['Mean', usd(data.per_user.mean_cost_usd)],
                  ['p95', usd(data.per_user.p95_cost_usd)],
                  ['Most expensive user', usd(data.per_user.max_cost_usd)],
                  ['Unattributed (jobs, no request)', usd(data.per_user.unattributed_cost_usd)],
                ].map(([k, v]) => (
                  <div
                    key={k}
                    className="flex items-baseline justify-between gap-4 border-b border-border/60 pb-2 last:border-0"
                  >
                    <dt className="text-xs text-muted-foreground">{k}</dt>
                    <dd className="text-sm font-medium tabular-nums">{v}</dd>
                  </div>
                ))}
              </dl>
            </Card>

            {/* ── Where it went ──────────────────────────────────────────── */}
            <Card variant="outline">
              <h2 className="text-sm font-semibold">By model</h2>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Daily cap is {usd(data.daily_budget_usd)} across all users.
              </p>
              <dl className="mt-4 space-y-2.5">
                {data.by_model.length === 0 && (
                  <p className="text-xs text-muted-foreground">Nothing recorded.</p>
                )}
                {data.by_model.map((m) => (
                  <div
                    key={`${m.provider}/${m.model}`}
                    className="flex items-baseline justify-between gap-4 border-b border-border/60 pb-2 last:border-0"
                  >
                    <dt className="min-w-0">
                      <span className="font-mono text-xs">{m.model}</span>
                      <Badge variant="neutral" className="ml-2 align-middle">
                        {m.provider}
                      </Badge>
                    </dt>
                    <dd className="shrink-0 text-sm tabular-nums">
                      <span className="text-muted-foreground">{m.calls} · </span>
                      <span className="font-medium">{usd(m.cost_usd)}</span>
                    </dd>
                  </div>
                ))}
              </dl>
            </Card>
          </div>

          {/* ── Daily, so a spike has a date on it ─────────────────────────── */}
          {data.by_day.length > 0 && (
            <Card variant="outline">
              <h2 className="text-sm font-semibold">By day</h2>
              <div className="mt-4 flex items-end gap-1 overflow-x-auto pb-1">
                {(() => {
                  const max = Math.max(...data.by_day.map((d) => d.cost_usd), 0.000001);
                  return data.by_day.map((d) => (
                    <div key={d.day} className="group flex w-6 shrink-0 flex-col items-center gap-1">
                      <span
                        className="w-full rounded-sm bg-accent-indigo/80"
                        style={{ height: `${Math.max((d.cost_usd / max) * 72, 2)}px` }}
                        title={`${d.day} · ${usd(d.cost_usd)} · ${d.calls} calls`}
                      />
                      <span className="font-mono text-[9px] text-muted-foreground">
                        {d.day.slice(8)}
                      </span>
                    </div>
                  ));
                })()}
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
