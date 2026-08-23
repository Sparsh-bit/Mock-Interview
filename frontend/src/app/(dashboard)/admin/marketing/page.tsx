'use client';

/*
 * REQUIRED BY CLOUDFLARE PAGES, and its absence breaks the deploy rather than this page.
 * `next build` passes without it and @cloudflare/next-on-pages refuses to produce a build,
 * naming the route — so the whole frontend stops deploying while every later commit looks
 * merged. See app/edge-runtime.test.ts, which fails on any route missing this line.
 */
export const runtime = 'edge';

/**
 * Admin — the mailing list. /admin/marketing
 *
 * "i want the activity and what is left in each user id as the information for me to mail them
 * for marketing."
 *
 * THIS SCREEN HAS ONE JOB: turn the user base into five groups of people who should each get a
 * different email, and get them out of the browser and into a mail merge. Everything on it is
 * in service of that and nothing else — it is not an analytics page, it does not trend
 * anything, and it deliberately shows no interview content.
 *
 * WHY IT IS NOT MORE COLUMNS ON /admin. That screen is access control: it exists to deactivate
 * an account and to grant admin, it is already a wide table, and it is read at a completely
 * different moment. The two share every rule they have in common on the server (`/admin/users`
 * and `/admin/marketing` call the same helpers for balances and activity) and nothing in the UI.
 *
 * THE SEGMENT IS THE PRODUCT OF THE PAGE. Each account lands in exactly one of five groups,
 * decided server-side in one function so the row and its segment cannot disagree, and each
 * group carries the one-line pitch that says what to write to it. Clicking a group filters to
 * it, and the export then covers exactly that group — which is how one screen becomes five
 * mailing lists without any of them being assembled by hand.
 *
 * THE WHOLE LIST ARRIVES IN ONE RESPONSE, unpaginated, on purpose. The file has to be the
 * whole thing: a "download" that silently covered page one only would be worse than no export
 * at all, because it would look right. So search and filtering happen here, over rows already
 * in memory, and the CSV is written from exactly the rows on screen. `truncated` says so out
 * loud in the unlikely event the server's cap is ever reached.
 *
 * REFETCHING IS OFF. This is the one endpoint in the product that returns every candidate's
 * email address in a single response; a window-focus refetch would pull the entire user base
 * every time the operator tabbed back from his email client. It is a list to be taken once and
 * worked from, with a visible Refresh for when that is wrong.
 */

import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  ClipboardCopy,
  Download,
  Mail,
  RefreshCw,
  Search,
  Users,
  Wallet,
} from 'lucide-react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { DataError } from '@/components/ui/data-error';
import { PageHeader } from '@/components/ui/page-header';
import { StatCard } from '@/components/ui/stat-card';
import { ApiError, getBrowserApiClient } from '@/lib/api';
import { cn } from '@/lib/utils';

import { CSV_BOM, csvFilename, toCsv, type MarketingListResponse, type MarketingRow } from './csv';

/**
 * Segment → badge colour, and the mapping is not decoration.
 *
 * `customer` is emerald and `report_waiting` is amber because those are the two groups an
 * operator scans for: one has already paid and must not be sent an offer, the other is the one
 * the ₹49 unlock is for. `finished_no_report` is coral because it is the only group whose
 * segment might mean something went wrong for that candidate, and reading it as a sales
 * opportunity would be the mistake.
 */
const SEGMENT_TONE: Record<string, 'success' | 'warning' | 'danger' | 'info' | 'neutral'> = {
  customer: 'success',
  report_waiting: 'warning',
  finished_no_report: 'danger',
  // `dropped_off` was split in two. The one that never got a question answered is coral, not
  // info, because it usually means something went wrong for that candidate — a slow first
  // question, a missing resume, a failure on start — and reading it as a sales opportunity
  // would be the mistake. The one who answered and stopped is a genuine nudge.
  left_before_answering: 'danger',
  stopped_partway: 'info',
  never_started: 'neutral',
};

/** Relative for the recent past, absolute once "42d ago" stops meaning anything. */
function when(iso: string | null): string {
  if (!iso) return 'never';
  const d = new Date(iso);
  const days = Math.floor((Date.now() - d.getTime()) / 86_400_000);
  if (days <= 0) return 'today';
  if (days === 1) return 'yesterday';
  if (days < 30) return `${days}d ago`;
  return d.toLocaleDateString();
}

export default function MarketingPage() {
  const [q, setQ] = useState('');
  const [segment, setSegment] = useState<string>('all');

  const list = useQuery({
    queryKey: ['admin', 'marketing'],
    queryFn: async () =>
      (await getBrowserApiClient().get('/api/v1/admin/marketing')).data as MarketingListResponse,
    retry: false,
    // See the note at the top of this file: pulling every email address in the product is not
    // something to do on a window focus event.
    refetchOnWindowFocus: false,
    staleTime: 5 * 60 * 1000,
  });

  const data = list.data;

  /**
   * The rows on screen, and therefore the rows in the file.
   *
   * Searching happens here rather than on the server even though the endpoint accepts `q`,
   * because the whole list is already in memory: a round trip per keystroke would re-pull the
   * user base to filter a few hundred rows the browser can filter instantly. The server-side
   * filter still exists and is still the same rule — it is what makes the endpoint usable
   * outside this screen.
   */
  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (data?.users ?? []).filter((r) => {
      if (segment !== 'all' && r.segment !== segment) return false;
      if (!needle) return true;
      return (
        r.email.toLowerCase().includes(needle) ||
        (r.full_name ?? '').toLowerCase().includes(needle)
      );
    });
  }, [data?.users, q, segment]);

  const status = list.error instanceof ApiError ? list.error.status : undefined;
  if (status === 403 || status === 401) {
    return (
      <div className="mx-auto max-w-xl py-16 text-center">
        <h1 className="text-lg font-medium">Not available</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          This area is limited to admin accounts.
        </p>
      </div>
    );
  }

  const download = () => {
    if (!data) return;
    // Built from `rows` — the filtered, searched set on screen — so the file and the table can
    // never be two different lists. The BOM is added here and not in `toCsv` so the tested
    // output is the CSV content itself; without it Excel decodes the file in the system code
    // page and mangles any name outside ASCII.
    const csv = CSV_BOM + toCsv(rows, data.features, data.segments);
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = csvFilename(new Date(), segment);
    // IN THE DOCUMENT, AND REVOKED ON THE NEXT TICK. Firefox ignores a click on a detached
    // anchor, and both Safari and Firefox have cancelled the download when the object URL is
    // revoked in the same tick as the click — the failure being a button that visibly does
    // nothing, which is indistinguishable from "the export is broken".
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
    toast.success(`${rows.length} ${rows.length === 1 ? 'account' : 'accounts'} exported`);
  };

  const copyEmails = async () => {
    const addresses = rows.map((r) => r.email).join(', ');
    if (!addresses) {
      toast.error('No accounts in this view');
      return;
    }
    try {
      await navigator.clipboard.writeText(addresses);
      toast.success(`${rows.length} addresses copied`);
    } catch {
      // Clipboard access is refused in plenty of legitimate situations (no permission, not a
      // secure context). Say so rather than appearing to have copied nothing.
      toast.error('The browser refused clipboard access — use the CSV instead');
    }
  };

  const activeSegment = data?.segments.find((s) => s.segment === segment);

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Admin"
        title="Mailing list"
        description="What each account has left, what they have done, and which email they should get."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="secondary" size="sm" onClick={() => list.refetch()} disabled={list.isFetching}>
              <RefreshCw className={cn('h-3.5 w-3.5', list.isFetching && 'animate-spin')} />
              Refresh
            </Button>
            <Button variant="secondary" size="sm" onClick={copyEmails} disabled={!rows.length}>
              <ClipboardCopy className="h-3.5 w-3.5" />
              Copy addresses
            </Button>
            <Button size="sm" onClick={download} disabled={!rows.length}>
              <Download className="h-3.5 w-3.5" />
              Export CSV
            </Button>
          </div>
        }
      />

      {list.isError && status !== 403 && status !== 401 && (
        <DataError
          title="Could not load the mailing list"
          error={list.error}
          onRetry={() => list.refetch()}
          retrying={list.isFetching}
        />
      )}

      {data && (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <StatCard
              label="Accounts"
              value={data.total}
              sub={`${data.returned} in this list`}
              icon={<Users className="h-4 w-4" />}
              color="blue"
            />
            <StatCard
              label="Report ready, unpaid"
              value={data.segments.find((s) => s.segment === 'report_waiting')?.count ?? 0}
              sub="the ₹50 unlock"
              icon={<Wallet className="h-4 w-4" />}
              color="amber"
            />
            <StatCard
              label="Paid before"
              value={data.segments.find((s) => s.segment === 'customer')?.count ?? 0}
              sub="do not send an offer"
              icon={<Mail className="h-4 w-4" />}
              color="emerald"
            />
            <StatCard
              label="Never started"
              value={data.segments.find((s) => s.segment === 'never_started')?.count ?? 0}
              sub="free trial untouched"
              icon={<Users className="h-4 w-4" />}
              color="violet"
            />
          </div>

          {data.truncated && (
            <Card variant="outline" className="border-accent-amber/30 bg-accent-amber-soft/40">
              <p className="text-sm">
                Showing the newest {data.returned} of {data.total} accounts — the server caps a
                single response. The export covers exactly what is on screen, so the older
                accounts are not in the file either.
              </p>
            </Card>
          )}

          {/* ── Segments, which are also the filter ───────────────────────────── */}
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setSegment('all')}
              className={cn(
                'rounded-full border px-3 py-1.5 text-xs font-medium transition-colors',
                segment === 'all'
                  ? 'border-accent-indigo bg-accent-indigo text-white'
                  : 'border-border text-muted-foreground hover:text-foreground',
              )}
            >
              Everyone · {data.returned}
            </button>
            {data.segments.map((s) => (
              <button
                key={s.segment}
                type="button"
                onClick={() => setSegment(s.segment === segment ? 'all' : s.segment)}
                title={s.pitch}
                className={cn(
                  'rounded-full border px-3 py-1.5 text-xs font-medium transition-colors',
                  segment === s.segment
                    ? 'border-accent-indigo bg-accent-indigo text-white'
                    : 'border-border text-muted-foreground hover:text-foreground',
                )}
              >
                {s.label} · {s.count}
              </button>
            ))}
          </div>

          {/* The pitch for whatever is selected, spelled out rather than left in a tooltip —
              it is the sentence that decides what the email says. */}
          {activeSegment && (
            <p className="text-sm text-muted-foreground">
              <span className="font-medium text-foreground">{activeSegment.label}:</span>{' '}
              {/* WHAT HAPPENED FIRST, then what to write. The pitch alone assumes the reader
                  already knows what the group did, which is exactly what the raw slug failed
                  to tell them. */}
              {activeSegment.what_happened} <span className="text-foreground/80">{activeSegment.pitch}</span>
            </p>
          )}

          <div className="relative max-w-sm">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search email or name…"
              className="w-full rounded-lg border border-border bg-surface-elevated py-2 pl-9 pr-3 text-sm focus:border-accent-indigo/40 focus:outline-none focus:ring-2 focus:ring-accent-indigo/20"
            />
          </div>

          <Card variant="outline" padding="none" className="overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px] text-sm">
                <thead>
                  <tr className="border-b border-border text-left font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                    <th className="px-5 py-2.5 font-normal">Account</th>
                    <th className="px-3 py-2.5 font-normal">Segment</th>
                    {data.features.map((f) => (
                      <th key={f.feature} className="px-3 py-2.5 text-right font-normal">
                        {f.label} left
                      </th>
                    ))}
                    <th className="px-3 py-2.5 text-right font-normal">Sessions</th>
                    <th className="px-3 py-2.5 text-right font-normal">Reports</th>
                    <th className="px-3 py-2.5 text-right font-normal">Paid</th>
                    <th className="px-5 py-2.5 text-right font-normal">Last active</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.length === 0 && (
                    <tr>
                      <td
                        colSpan={6 + data.features.length}
                        className="px-5 py-10 text-center text-sm text-muted-foreground"
                      >
                        {list.isLoading ? 'Loading…' : 'No accounts in this view.'}
                      </td>
                    </tr>
                  )}
                  {rows.map((r) => (
                    <Row key={r.user_id} row={r} features={data.features} segments={data.segments} />
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <p className="text-xs text-muted-foreground">
            Personal data. This list is admin-only and shows counts and flags only — never an
            answer, a transcript or a report. Taken {new Date(data.generated_at).toLocaleString()}.
          </p>
        </>
      )}
    </div>
  );
}

function Row({
  row,
  features,
  segments,
}: {
  row: MarketingRow;
  features: MarketingListResponse['features'];
  /** Passed so the badge can render the server's label and reason rather than the raw key. */
  segments: MarketingListResponse['segments'];
}) {
  const meta = segments.find((s) => s.segment === row.segment);
  return (
    <tr className={cn('border-b border-border/60 last:border-0', !row.is_active && 'opacity-60')}>
      <td className="px-5 py-3">
        <span className="font-medium">{row.full_name || row.email.split('@')[0]}</span>
        <span className="ml-2 text-xs text-muted-foreground">{row.email}</span>
        {!row.is_active && <span className="ml-2 text-[10px] uppercase text-accent-coral-ink">deactivated</span>}
      </td>
      <td className="px-3 py-3">
        {/* THE HUMAN LABEL, NOT THE KEY. This rendered `row.segment` — so the screen said
            `dropped_off`, which tells the person writing the email nothing about what the
            account actually did. The label and the reason both come from the server (see
            _SEGMENTS in api/v1/admin.py) so the screen cannot describe a segment differently
            from the rule that assigns it. `title` carries the full sentence for a hover;
            the label is what is readable at a glance down a column. */}
        <Badge
          variant={SEGMENT_TONE[row.segment] ?? 'neutral'}
          // The full sentence on hover. Falls back to the key only if the server ever sends a
          // segment this build has not heard of, which is better than rendering nothing.
          title={meta?.what_happened ?? row.segment}
        >
          {meta?.label ?? row.segment}
        </Badge>
      </td>
      {features.map((f) => (
        <td key={f.feature} className="px-3 py-3 text-right tabular-nums">
          {/* Operator accounts are not metered at all, so a number here would be a lie rather
              than a figure — the same reason the candidate's own balance says "unlimited". */}
          {row.unlimited ? (
            <span className="text-xs text-muted-foreground">∞</span>
          ) : (
            <span className={cn(row.remaining[f.feature] === 0 && 'text-muted-foreground')}>
              {row.remaining[f.feature] ?? 0}
            </span>
          )}
        </td>
      ))}
      <td className="px-3 py-3 text-right tabular-nums">
        {/* Started and completed together, because either one alone is misleading: five starts
            and no finishes is a different person from one start and one finish. */}
        {row.sessions_completed}
        <span className="text-muted-foreground">/{row.sessions_started}</span>
      </td>
      <td className="px-3 py-3 text-right tabular-nums">{row.reports}</td>
      <td className="px-3 py-3 text-right text-xs">
        {row.ever_paid ? (
          <span className="text-accent-emerald-ink">{when(row.last_paid_at)}</span>
        ) : (
          <span className="text-muted-foreground">no</span>
        )}
      </td>
      <td className="px-5 py-3 text-right text-xs text-muted-foreground">
        {when(row.last_active_at)}
      </td>
    </tr>
  );
}
