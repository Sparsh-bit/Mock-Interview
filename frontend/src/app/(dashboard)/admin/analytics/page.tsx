'use client';

/**
 * Admin analytics — revenue, the vector cache, and whether AI is getting cheaper.
 *
 * ADMIN ONLY, AND ENFORCED ON THE SERVER. Both endpoints behind this page take the
 * `AdminUser` dependency and answer 403 for an ordinary account, so the check below decides
 * what is RENDERED, never what is permitted. A non-admin who guesses the URL gets a plain
 * "not available" and learns nothing about what the page would have shown.
 *
 * THREE QUESTIONS, IN THE ORDER THEY MATTER:
 *
 *   1. What came in — gross revenue, per payment, from the credit ledger.
 *   2. What the shared cache costs to keep — disk, and how close each feature is to the
 *      ceiling that starts throwing entries away.
 *   3. Whether it is working — spend avoided, and the saturation signal that says whether
 *      the product gets cheaper per user as more people use it.
 *
 * Question 3 is the one a price depends on. The others are context for reading it.
 */

import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { AudioLines, Coins, Database, Gift, IndianRupee, Scale, TrendingDown, Users } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { PageHeader } from '@/components/ui/page-header';
import { StatCard } from '@/components/ui/stat-card';
import { ApiError, getBrowserApiClient } from '@/lib/api';
import { formatBytes, formatRupees, saturationPct, usd } from '@/lib/format/admin-metrics';
import { cn } from '@/lib/utils';


const WINDOWS = [7, 30, 90] as const;

interface RevenueReport {
  window_days: number;
  gross_paise: number;
  gross_inr: number;
  payments: number;
  paying_users: number;
  average_order_inr: number;
  free_grants: number;
  all_time_gross_inr: number;
  by_day: { day: string; inr: number; payments: number }[];
  by_item: { item_id: string; name: string; inr: number; payments: number }[];
  /**
   * What it cost to serve the window. AI comes from `ai_usage`; SPEECH comes from
   * `tts_usage`, which did not exist until the margin below needed it — speech was a Redis
   * float for the current UTC day with a 48-hour TTL and no attribution, so it could not be
   * joined to a month of revenue even in principle.
   */
  costs: {
    ai_usd: number;
    ai_available: boolean;
    tts_usd: number;
    tts_characters: number;
    tts_characters_cached: number;
    tts_cache_hit_pct: number;
    tts_available: boolean;
    tts_by_provider: { provider: string; cost_usd: number; characters: number; utterances: number }[];
    variable_usd: number;
    variable_inr: number;
    inr_per_usd: number;
  };
  contribution_inr: number;
  contribution_margin_pct: number;
  /** False when either ledger could not be read — the margin is then an upper bound. */
  contribution_complete: boolean;
}

/**
 * Only the blocks this page reads. The AI usage endpoint returns considerably more — spend
 * by feature, by model, per-user percentiles — and that is the /ai-usage page's job. Two
 * pages reading one endpoint is fine; two pages both claiming to be the cost report is not.
 */
interface UsageSlice {
  cache: {
    feature: string;
    entries: number;
    hits: number;
    never_hit: number;
    last_used: string | null;
  }[];
  cache_storage: {
    available: boolean;
    total_bytes: number;
    table_bytes: number;
    index_bytes: number;
    rows: number;
    hits: number;
    features: number;
    max_rows_per_feature: number;
    embedding_dim: number;
  };
  savings: {
    avoided_usd: number;
    would_have_cost_usd: number;
    avoided_pct: number;
    by_feature: {
      feature: string;
      hits: number;
      entries: number;
      never_hit: number;
      cost_per_call_usd: number;
      avoided_usd: number;
      hits_per_entry: number;
    }[];
  };
}

export default function AdminAnalyticsPage() {
  const [days, setDays] = useState<number>(30);

  const revenue = useQuery({
    queryKey: ['admin', 'revenue', days],
    queryFn: async () => {
      const r = await getBrowserApiClient().get(`/api/v1/admin/revenue?days=${days}`);
      return r.data as RevenueReport;
    },
    staleTime: 60_000,
  });

  const usage = useQuery({
    queryKey: ['admin', 'usage-slice', days],
    queryFn: async () => {
      const r = await getBrowserApiClient().get(`/api/v1/ai-usage?days=${days}`);
      return r.data as UsageSlice;
    },
    staleTime: 60_000,
  });

  /*
   * 403 means not an admin; 404 means the AI ledger is switched off. Neither is a failure,
   * and neither should render as one. Checked across BOTH queries because the AI ledger can
   * be disabled independently of admin rights — revenue would still load, and a page that
   * showed half its sections with no explanation would read as broken.
   */
  const blocked = [revenue.error, usage.error].find(
    (e) => e instanceof ApiError && (e.status === 403 || e.status === 404),
  );
  if (blocked) {
    return (
      <div className="mx-auto max-w-xl py-16 text-center">
        <h1 className="text-lg font-medium">Not available</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          This page shows internal revenue and infrastructure data, and is limited to admin
          accounts.
        </p>
      </div>
    );
  }

  const rev = revenue.data;
  const storage = usage.data?.cache_storage;
  const savings = usage.data?.savings;

  // The busiest day in the window, used to scale the bars. Falls back to 1 so a window with
  // no revenue divides by something rather than producing NaN widths.
  const peakDay = Math.max(1, ...(rev?.by_day ?? []).map((d) => d.inr));

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Admin"
        title="Analytics"
        description="Revenue, vector cache storage, and whether AI cost is falling per user."
        actions={
          <div className="flex gap-1 rounded-lg border border-border p-1">
            {WINDOWS.map((w) => (
              <button
                key={w}
                type="button"
                onClick={() => setDays(w)}
                className={cn(
                  'rounded-md px-3 py-1 text-sm transition-colors',
                  days === w
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:text-foreground',
                )}
              >
                {w}d
              </button>
            ))}
          </div>
        }
      />

      {/* ── Revenue ─────────────────────────────────────────────────────────────── */}
      <section className="space-y-4">
        <div className="flex items-baseline justify-between">
          <h2 className="text-base font-medium">Revenue</h2>
          <span className="text-xs text-muted-foreground">
            Gross, per payment. Before gateway fees and refunds — neither is recorded here.
          </span>
        </div>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            label={`Gross · ${days}d`}
            value={rev ? formatRupees(rev.gross_inr) : '—'}
            icon={<IndianRupee className="h-4 w-4" />}
            sub={rev ? `${rev.payments} payment${rev.payments === 1 ? '' : 's'}` : undefined}
            color="emerald"
          />
          <StatCard
            label="Paying users"
            value={rev ? rev.paying_users : '—'}
            icon={<Users className="h-4 w-4" />}
            sub={rev && rev.paying_users > 0 ? 'distinct accounts' : 'none yet'}
            color="blue"
          />
          <StatCard
            label="Average order"
            // A zero average is meaningless with no payments, so it reads as an em dash
            // rather than as "₹0", which would look like everything sold for nothing.
            value={rev && rev.payments > 0 ? formatRupees(rev.average_order_inr) : '—'}
            icon={<Coins className="h-4 w-4" />}
            color="violet"
          />
          <StatCard
            label="All time"
            value={rev ? formatRupees(rev.all_time_gross_inr) : '—'}
            icon={<TrendingDown className="h-4 w-4" />}
            sub={rev ? `${rev.free_grants} free grant${rev.free_grants === 1 ? '' : 's'}` : undefined}
            color="amber"
          />
        </div>

        {/* ── What it cost to serve ─────────────────────────────────────────────────
            THE FIGURE THIS PAGE DID NOT HAVE. Revenue sat here alone, and the only margin
            anybody could quote was plans.py's — computed against AI cost alone. Speech is a
            second variable cost, metered per character, and up to twelve times the AI cost
            of the same round on the wrong vendor. Leaving it out did not make the margin
            incomplete; it made it wrong, in the flattering direction. */}
        {rev && (
          <Card className="space-y-4 p-5">
            <div className="flex items-baseline justify-between gap-4">
              <h3 className="text-sm font-medium">Cost to serve, and what is left</h3>
              <span className="text-xs text-muted-foreground">
                ${'{'}rev.costs.inr_per_usd{'}'}/USD · before gateway fees, refunds and hosting
              </span>
            </div>

            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <StatCard
                label="AI cost"
                value={rev.costs.ai_available ? usd(rev.costs.ai_usd) : 'n/a'}
                icon={<Database className="h-4 w-4" />}
                sub={rev.costs.ai_available ? 'from ai_usage' : 'ledger unavailable'}
                color="blue"
              />
              <StatCard
                label="Speech cost"
                value={rev.costs.tts_available ? usd(rev.costs.tts_usd) : 'n/a'}
                icon={<AudioLines className="h-4 w-4" />}
                sub={
                  rev.costs.tts_available
                    ? `${rev.costs.tts_cache_hit_pct}% of characters cached`
                    : 'ledger unavailable'
                }
                color="violet"
              />
              <StatCard
                label="Total variable"
                value={formatRupees(rev.costs.variable_inr)}
                icon={<Coins className="h-4 w-4" />}
                sub={usd(rev.costs.variable_usd)}
                color="amber"
              />
              <StatCard
                label="Contribution"
                value={formatRupees(rev.contribution_inr)}
                icon={<Scale className="h-4 w-4" />}
                /* NOT "profit". Gross minus the two variable costs this system can measure —
                   no gateway fee, no refunds, no hosting, and none of the AI given away to
                   accounts that never buy. An upper bound, and the label says so. */
                sub={`${rev.contribution_margin_pct}% of gross`}
                color={rev.contribution_margin_pct < 0 ? 'red' : 'emerald'}
              />
            </div>

            {!rev.contribution_complete && (
              /* MISSING COST DATA IS SAID OUT LOUD, NEVER TREATED AS ZERO. A margin that
                 silently reads absent cost as no cost is the exact failure this block
                 exists to remove. */
              <p className="text-xs text-accent-amber-ink">
                One of the cost ledgers could not be read, so the contribution above is an
                upper bound rather than a figure.
              </p>
            )}

            {rev.costs.tts_by_provider.length > 0 && (
              <div className="space-y-1.5 border-t border-border/40 pt-4">
                {rev.costs.tts_by_provider.map((v) => (
                  <div key={v.provider} className="flex items-center gap-3 text-xs">
                    <span className="w-24 shrink-0 text-muted-foreground">{v.provider}</span>
                    <span className="flex-1 tabular-nums text-muted-foreground">
                      {v.utterances.toLocaleString()} utterances ·{' '}
                      {v.characters.toLocaleString()} chars
                    </span>
                    <span className="w-24 shrink-0 text-right tabular-nums">
                      {usd(v.cost_usd)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </Card>
        )}

        {rev && rev.by_day.length > 0 && (
          <Card className="p-5">
            <h3 className="mb-4 text-sm font-medium">Daily</h3>
            <div className="space-y-1.5">
              {rev.by_day.map((d) => (
                <div key={d.day} className="flex items-center gap-3 text-xs">
                  <span className="w-20 shrink-0 tabular-nums text-muted-foreground">
                    {d.day.slice(5)}
                  </span>
                  <div className="h-4 flex-1 overflow-hidden rounded bg-muted">
                    <div
                      /* Stock Tailwind green, off-palette, and it also read as "passed" — which emerald means
                         everywhere else in the product. Revenue is amber: money and effort. */
                      className="h-full rounded bg-accent-amber/70"
                      style={{ width: `${(d.inr / peakDay) * 100}%` }}
                    />
                  </div>
                  <span className="w-24 shrink-0 text-right tabular-nums">
                    {formatRupees(d.inr)}
                  </span>
                  <span className="w-16 shrink-0 text-right tabular-nums text-muted-foreground">
                    {d.payments}×
                  </span>
                </div>
              ))}
            </div>
          </Card>
        )}

        {rev && rev.by_item.length > 0 && (
          <Card className="overflow-x-auto p-5">
            <h3 className="mb-4 text-sm font-medium">By item</h3>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs text-muted-foreground">
                  <th className="pb-2 font-medium">Item</th>
                  <th className="pb-2 text-right font-medium">Payments</th>
                  <th className="pb-2 text-right font-medium">Gross</th>
                </tr>
              </thead>
              <tbody>
                {rev.by_item.map((i) => (
                  <tr key={i.item_id} className="border-b border-border/50 last:border-0">
                    <td className="py-2">{i.name}</td>
                    <td className="py-2 text-right tabular-nums">{i.payments}</td>
                    <td className="py-2 text-right tabular-nums">{formatRupees(i.inr)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}

        {rev && rev.payments === 0 && (
          <Card className="p-5 text-sm text-muted-foreground">
            No payments in this window. Free grants and 100%-off codes are counted separately
            and do not appear here — they are product given away, not money taken.
          </Card>
        )}
      </section>

      {/* ── Vector database ─────────────────────────────────────────────────────── */}
      <section className="space-y-4">
        <div className="flex items-baseline justify-between">
          <h2 className="text-base font-medium">Vector database</h2>
          <span className="text-xs text-muted-foreground">
            Shared AI cache. Sizes include the HNSW index, which is usually the larger half.
          </span>
        </div>

        {storage && !storage.available && (
          /*
           * "Could not read" is deliberately NOT rendered as zeroes. An empty cache and an
           * unreadable one both produce 0 rows, and they mean opposite things: one is a new
           * deployment, the other is a missing migration.
           */
          <Card className="p-5 text-sm text-muted-foreground">
            Could not read cache storage. The <code>ai_cache</code> table may not exist yet —
            migration 014 creates it. This is not the same as an empty cache.
          </Card>
        )}

        {storage?.available && (
          <>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <StatCard
                label="Total size"
                value={formatBytes(storage.total_bytes)}
                icon={<Database className="h-4 w-4" />}
                sub={`${formatBytes(storage.table_bytes)} table · ${formatBytes(storage.index_bytes)} index`}
                color="blue"
              />
              <StatCard
                label="Entries"
                value={storage.rows.toLocaleString()}
                icon={<Database className="h-4 w-4" />}
                sub={`across ${storage.features} feature${storage.features === 1 ? '' : 's'}`}
                color="violet"
              />
              <StatCard
                label="Lifetime hits"
                value={storage.hits.toLocaleString()}
                icon={<TrendingDown className="h-4 w-4" />}
                sub="generations avoided"
                color="emerald"
              />
              <StatCard
                label="Embedding"
                value={`${storage.embedding_dim}d`}
                icon={<Database className="h-4 w-4" />}
                sub="computed locally — no API cost"
                color="amber"
              />
            </div>

            {usage.data && usage.data.cache.length > 0 && (
              <Card className="p-5">
                <h3 className="mb-1 text-sm font-medium">Fill per feature</h3>
                <p className="mb-4 text-xs text-muted-foreground">
                  Eviction only runs on the write path, so a feature at its ceiling of{' '}
                  {storage.max_rows_per_feature.toLocaleString()} is discarding entries that
                  may still have been earning hits.
                </p>
                <div className="space-y-3">
                  {usage.data.cache.map((c) => {
                    const pct = saturationPct(c.entries, storage.max_rows_per_feature);
                    return (
                      <div key={c.feature} className="space-y-1">
                        <div className="flex items-center justify-between text-xs">
                          <span className="font-medium">{c.feature}</span>
                          <span className="tabular-nums text-muted-foreground">
                            {c.entries.toLocaleString()} / {storage.max_rows_per_feature.toLocaleString()}
                            {/* The `dark:` half of this was dead code — darkMode is
                                configured but globals.css defines no dark palette, so the
                                variant could never apply. */}
                            {c.never_hit > 0 && (
                              <span className="ml-2 text-accent-amber-ink">
                                {c.never_hit} never hit
                              </span>
                            )}
                          </span>
                        </div>
                        <div className="h-2 overflow-hidden rounded bg-muted">
                          <div
                            className={cn(
                              'h-full rounded',
                              // @not-a-score — this `pct` is CACHE SATURATION, how full a feature's cache table is
                              // against its row cap. It is an operational threshold, not a
                              // candidate's performance, so it must NOT use the score bands:
                              // 90% full is a warning, whereas a score of 90 is excellent.
                              pct >= 90 ? 'bg-accent-amber' : 'bg-accent-indigo/70',
                            )}
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </Card>
            )}
          </>
        )}
      </section>

      {/* ── Cost reduction ──────────────────────────────────────────────────────── */}
      <section className="space-y-4">
        <div className="flex items-baseline justify-between">
          <h2 className="text-base font-medium">AI cost avoided</h2>
          <span className="text-xs text-muted-foreground">
            Cache hits priced at what that feature actually costs per call, this window.
          </span>
        </div>

        {savings && (
          <>
            <div className="grid gap-4 sm:grid-cols-3">
              <StatCard
                label="Avoided"
                value={usd(savings.avoided_usd)}
                icon={<TrendingDown className="h-4 w-4" />}
                sub={`${savings.avoided_pct}% of what it would have cost`}
                color="emerald"
              />
              <StatCard
                label="Would have cost"
                value={usd(savings.would_have_cost_usd)}
                icon={<Coins className="h-4 w-4" />}
                sub="without the shared cache"
                color="amber"
              />
              <StatCard
                label="Actually spent"
                value={usd(Math.max(0, savings.would_have_cost_usd - savings.avoided_usd))}
                icon={<Gift className="h-4 w-4" />}
                color="blue"
              />
            </div>

            <Card className="overflow-x-auto p-5">
              <h3 className="mb-1 text-sm font-medium">Per feature</h3>
              <p className="mb-4 text-xs text-muted-foreground">
                <strong>Hits per entry</strong> is the number to watch. Climbing across
                releases means the key space is bounded and the cache is saturating — the
                product gets cheaper per user as it grows. Flat near 1.0 means it never will.
              </p>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted-foreground">
                    <th className="pb-2 font-medium">Feature</th>
                    <th className="pb-2 text-right font-medium">Entries</th>
                    <th className="pb-2 text-right font-medium">Hits</th>
                    <th className="pb-2 text-right font-medium">Hits / entry</th>
                    <th className="pb-2 text-right font-medium">Per call</th>
                    <th className="pb-2 text-right font-medium">Avoided</th>
                  </tr>
                </thead>
                <tbody>
                  {savings.by_feature.map((f) => (
                    <tr key={f.feature} className="border-b border-border/50 last:border-0">
                      <td className="py-2">
                        {f.feature}
                        {/* Entries with no hits are writes that bought nothing. Worth naming
                            rather than leaving to be inferred from two columns. */}
                        {f.hits === 0 && f.entries > 0 && (
                          <Badge variant="neutral" className="ml-2 text-[10px]">
                            no hits
                          </Badge>
                        )}
                      </td>
                      <td className="py-2 text-right tabular-nums">{f.entries.toLocaleString()}</td>
                      <td className="py-2 text-right tabular-nums">{f.hits.toLocaleString()}</td>
                      <td
                        className={cn(
                          'py-2 text-right tabular-nums',
                          // A cache earning its keep: emerald, which is 'verified/working' throughout.
                          f.hits_per_entry >= 2 && 'text-accent-emerald-ink',
                        )}
                      >
                        {f.hits_per_entry.toFixed(2)}
                      </td>
                      <td className="py-2 text-right tabular-nums text-muted-foreground">
                        {usd(f.cost_per_call_usd)}
                      </td>
                      <td className="py-2 text-right tabular-nums">{usd(f.avoided_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-4 text-xs text-muted-foreground">
                Hits are counted for the lifetime of each entry while spend is limited to this
                window, so a short window overstates the saving. Stated rather than silently
                corrected — the alternative is a write on every cache read to tidy a report.
              </p>
            </Card>
          </>
        )}
      </section>
    </div>
  );
}
