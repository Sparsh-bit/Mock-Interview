'use client';

/**
 * Admin — user management. /admin
 *
 * Who is using the product, what they cost, and the two switches that matter.
 *
 * WHY CONFIRMATION DIALOGS. Deactivating someone signs them out everywhere and
 * 403s every request they make. Granting admin hands over this page. Both are one
 * misclick away on a table of similar-looking rows, so both ask first and both
 * name the account in the question — "Deactivate someone" is easy to click
 * through, "Deactivate priya@college.edu" is not.
 *
 * The two self-destructive actions are refused by the server: you cannot
 * deactivate your own account or revoke your own admin. The buttons are also
 * disabled on your own row, so the rule is visible before you click rather than
 * explained afterwards in a toast — but the server is the actual guarantee, since
 * a disabled button is a suggestion.
 *
 * COST IS TEMPORARY DATA IN A PERMANENT PAGE. The spend column comes from the
 * ai_usage ledger, which is deleted when credits ship. `cost_data_available`
 * tells us whether to render the column at all, so it disappears rather than
 * showing a row of zeroes that look like real measurements.
 */

import Link from 'next/link';
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Ban,
  CheckCircle2,
  ChevronRight,
  Mail,
  Search,
  Shield,
  ShieldOff,
  Trash2,
  Users,
  Wallet,
} from 'lucide-react';
import { toast } from 'sonner';
import { formatDate } from '@/lib/format-date';
import { ApiError, getBrowserApiClient } from '@/lib/api';
import { useAuth } from '@/hooks/useAuth';
import { Card } from '@/components/ui/card';
import { Button, buttonVariants } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { PageHeader } from '@/components/ui/page-header';
import { StatCard } from '@/components/ui/stat-card';
import { cn } from '@/lib/utils';


interface UserRow {
  id: string;
  email: string;
  full_name: string | null;
  is_active: boolean;
  is_admin: boolean;
  created_at: string;
  sessions: number;
  last_session_at: string | null;
  ai_cost_usd: number;
  ai_calls: number;
}

interface Overview {
  total_users: number;
  active_users: number;
  deactivated_users: number;
  admins: number;
  new_users_7d: number;
  total_sessions: number;
  ai_spend_7d_usd: number;
  cost_data_available: boolean;
  daily_budget_usd: number;
}

interface UserDetail {
  user: { id: string; email: string; full_name: string | null; is_active: boolean; is_admin: boolean };
  window_days: number;
  cost_data_available: boolean;
  ai_cost_usd: number;
  by_feature: { feature: string; calls: number; cost_usd: number; input_tokens: number; output_tokens: number }[];
  recent_sessions: { id: string; status: string; created_at: string; questions_asked: number }[];
}

type Sort = 'cost' | 'sessions' | 'recent' | 'email';

/** Sub-cent per-call costs need more than two decimals or they all read as $0.00. */
function usd(v: number): string {
  if (v === 0) return '$0';
  if (v < 0.01) return `$${v.toFixed(5)}`;
  if (v < 1) return `$${v.toFixed(4)}`;
  return `$${v.toFixed(2)}`;
}

function when(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  const days = Math.floor((Date.now() - d.getTime()) / 86_400_000);
  if (days === 0) return 'today';
  if (days === 1) return 'yesterday';
  if (days < 30) return `${days}d ago`;
  return formatDate(d);
}

export default function AdminPage() {
  const qc = useQueryClient();
  // Which row is me. Matched on email because that is what both the JWT and the
  // admin list carry; the app's user id is not exposed to the browser.
  const { user: me } = useAuth();
  const [q, setQ] = useState('');
  const [sort, setSort] = useState<Sort>('cost');
  const [activeOnly, setActiveOnly] = useState<boolean | null>(null);
  const [openUser, setOpenUser] = useState<string | null>(null);

  const overview = useQuery({
    queryKey: ['admin', 'overview'],
    queryFn: async () => (await getBrowserApiClient().get('/api/v1/admin/overview')).data as Overview,
    retry: false,
  });

  const params = new URLSearchParams({ sort, per_page: '50' });
  if (q.trim()) params.set('q', q.trim());
  if (activeOnly !== null) params.set('active', String(activeOnly));

  const users = useQuery({
    queryKey: ['admin', 'users', sort, q, activeOnly],
    queryFn: async () =>
      (await getBrowserApiClient().get(`/api/v1/admin/users?${params}`)).data as {
        users: UserRow[];
        total: number;
        cost_data_available: boolean;
      },
    retry: false,
  });

  const detail = useQuery({
    queryKey: ['admin', 'user', openUser],
    queryFn: async () =>
      (await getBrowserApiClient().get(`/api/v1/admin/users/${openUser}`)).data as UserDetail,
    enabled: !!openUser,
  });

  const update = useMutation({
    mutationFn: async (v: { id: string; is_active?: boolean; is_admin?: boolean }) => {
      const { id, ...body } = v;
      return (await getBrowserApiClient().patch(`/api/v1/admin/users/${id}`, body)).data;
    },
    onSuccess: (_d, v) => {
      toast.success(
        v.is_active === false
          ? 'Account deactivated and signed out everywhere'
          : v.is_active === true
            ? 'Account reactivated'
            : v.is_admin
              ? 'Admin access granted'
              : 'Admin access revoked',
      );
      qc.invalidateQueries({ queryKey: ['admin'] });
    },
    // The server refuses the self-destructive cases; surface its reason verbatim
    // rather than a generic failure, because the reason is the useful part.
    onError: (e: Error) => toast.error(e.message),
  });

  /**
   * Permanent deletion, gated behind typing the address.
   *
   * A CONFIRM DIALOG IS NOT ENOUGH FOR THIS ONE. Deactivation is reversible and a
   * `window.confirm` naming the account is proportionate to it. Deletion removes the Supabase
   * login, the uploaded files and every row, and cannot be undone — so it asks the admin to
   * TYPE the email, which is the only prompt that forces them to look at which row they are
   * on. `window.prompt` rather than a modal because this page has no modal primitive and
   * inventing one for a destructive action is the wrong place to debut new UI; the guarantee
   * is the server checking the address against the row anyway.
   */
  const destroy = useMutation({
    mutationFn: async (u: UserRow) => {
      const typed = window.prompt(
        `PERMANENTLY delete ${u.email}?\n\n` +
          'This removes their login, their uploaded resume, and every interview, report and ' +
          'payment record. It cannot be undone.\n\n' +
          'Type the email address to confirm:',
      );
      // Cancelled. Not an error and must produce no toast — the admin changed their mind,
      // which is the prompt working.
      if (typed === null) return null;
      // POST, not DELETE: this carries the typed confirmation, and a body on a DELETE is
      // permitted to be dropped by intermediaries — this app is served through Cloudflare, and
      // a confirmation that can vanish in transit is worse than none at all.
      const res = await getBrowserApiClient().post(`/api/v1/admin/users/${u.id}/delete`, {
        confirm_email: typed.trim(),
        reason: 'Deleted from the admin users page',
      });
      return res.data as { deleted: boolean; email: string; resume_files_removed: number };
    },
    onSuccess: (data) => {
      if (!data) return;
      toast.success(`${data.email} deleted permanently.`);
      void qc.invalidateQueries({ queryKey: ['admin'] });
    },
    onError: (err) => {
      // The server's message is the useful one — "the email you typed does not match this
      // account. Nothing was deleted." — so it is shown verbatim.
      toast.error(
        err instanceof ApiError && err.message ? err.message : 'Could not delete that account.',
      );
    },
  });

  const status = overview.error instanceof ApiError ? overview.error.status : undefined;
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

  const o = overview.data;
  const costOn = users.data?.cost_data_available ?? false;

  const act = (u: UserRow, change: { is_active?: boolean; is_admin?: boolean }, question: string) => {
    if (!window.confirm(question)) return;
    update.mutate({ id: u.id, ...change });
  };

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Admin"
        title="Users"
        description="Who is using the product, what they cost, and who can get in."
        actions={
          /* This page is access control — deactivate an account, grant admin. "What has this
             person got left and what should I mail them" is a different question asked at a
             different moment, so it is a different screen rather than six more columns on an
             already-wide table. The link is here because this is where an admin starts. */
          <Link
            href="/admin/marketing"
            className={cn(buttonVariants({ variant: 'secondary', size: 'sm' }))}
          >
            <Mail className="h-3.5 w-3.5" />
            Mailing list
          </Link>
        }
      />

      {o && (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatCard
            label="Users"
            value={o.total_users}
            sub={`${o.new_users_7d} joined this week`}
            icon={<Users className="h-4 w-4" />}
            color="blue"
          />
          <StatCard
            label="Active"
            value={o.active_users}
            sub={o.deactivated_users ? `${o.deactivated_users} deactivated` : 'none deactivated'}
            icon={<CheckCircle2 className="h-4 w-4" />}
            color="emerald"
          />
          <StatCard
            label="Admins"
            value={o.admins}
            sub="can reach this page"
            icon={<Shield className="h-4 w-4" />}
            color="violet"
          />
          <StatCard
            label="AI spend · 7d"
            value={o.cost_data_available ? usd(o.ai_spend_7d_usd) : '—'}
            sub={`cap ${usd(o.daily_budget_usd)}/day`}
            icon={<Wallet className="h-4 w-4" />}
            color="amber"
          />
        </div>
      )}

      {/* ── Controls ──────────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[220px] flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search email or name…"
            className="w-full rounded-lg border border-border bg-surface-elevated py-2 pl-9 pr-3 text-sm focus:border-accent-indigo/40 focus:outline-none focus:ring-2 focus:ring-accent-indigo/20"
          />
        </div>

        <div className="flex items-center gap-1 rounded-lg border border-border bg-surface-elevated p-1">
          {(
            [
              [null, 'All'],
              [true, 'Active'],
              [false, 'Deactivated'],
            ] as const
          ).map(([v, label]) => (
            <button
              key={label}
              type="button"
              onClick={() => setActiveOnly(v)}
              className={cn(
                'rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
                activeOnly === v
                  ? 'bg-accent-indigo text-white'
                  : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {label}
            </button>
          ))}
        </div>

        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as Sort)}
          className="rounded-lg border border-border bg-surface-elevated px-3 py-2 text-sm focus:outline-none"
        >
          <option value="cost">Sort: cost</option>
          <option value="sessions">Sort: sessions</option>
          <option value="recent">Sort: most recent</option>
          <option value="email">Sort: email</option>
        </select>
      </div>

      {/* ── Table ─────────────────────────────────────────────────────────── */}
      <Card variant="outline" padding="none" className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] text-sm">
            <thead>
              <tr className="border-b border-border text-left font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                <th className="px-5 py-2.5 font-normal">Account</th>
                <th className="px-3 py-2.5 text-right font-normal">Sessions</th>
                <th className="px-3 py-2.5 text-right font-normal">Last active</th>
                {costOn && <th className="px-3 py-2.5 text-right font-normal">AI cost</th>}
                <th className="px-3 py-2.5 text-center font-normal">State</th>
                <th className="px-5 py-2.5 text-right font-normal">Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.isLoading && (
                <tr>
                  <td colSpan={6} className="px-5 py-10 text-center text-sm text-muted-foreground">
                    Loading…
                  </td>
                </tr>
              )}
              {users.data?.users.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-5 py-10 text-center text-sm text-muted-foreground">
                    No accounts match.
                  </td>
                </tr>
              )}
              {users.data?.users.map((u) => (
                <tr
                  key={u.id}
                  className={cn(
                    'border-b border-border/60 last:border-0',
                    !u.is_active && 'bg-accent-coral-soft/40',
                  )}
                >
                  <td className="px-5 py-3">
                    <button
                      type="button"
                      onClick={() => setOpenUser(openUser === u.id ? null : u.id)}
                      className="group flex items-center gap-1.5 text-left"
                    >
                      <span>
                        <span className="font-medium">{u.full_name || u.email.split('@')[0]}</span>
                        <span className="ml-2 text-xs text-muted-foreground">{u.email}</span>
                      </span>
                      <ChevronRight
                        className={cn(
                          'h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform',
                          openUser === u.id && 'rotate-90',
                        )}
                      />
                    </button>
                  </td>
                  <td className="px-3 py-3 text-right tabular-nums">{u.sessions}</td>
                  <td className="px-3 py-3 text-right text-muted-foreground">
                    {when(u.last_session_at)}
                  </td>
                  {costOn && (
                    <td className="px-3 py-3 text-right tabular-nums">
                      {usd(u.ai_cost_usd)}
                      <span className="ml-1 text-[10px] text-muted-foreground">
                        {u.ai_calls ? `(${u.ai_calls})` : ''}
                      </span>
                    </td>
                  )}
                  <td className="px-3 py-3 text-center">
                    <div className="flex items-center justify-center gap-1.5">
                      <Badge variant={u.is_active ? 'success' : 'danger'}>
                        {u.is_active ? 'Active' : 'Deactivated'}
                      </Badge>
                      {u.is_admin && <Badge variant="violet">Admin</Badge>}
                    </div>
                  </td>
                  <td className="px-5 py-3">
                    <div className="flex items-center justify-end gap-1.5">
                      {u.is_active ? (
                        <Button
                          variant="secondary"
                          size="sm"
                          disabled={u.email === me?.email}
                          title={
                            u.email === me?.email
                              ? 'You cannot deactivate your own account'
                              : undefined
                          }
                          onClick={() =>
                            act(u, { is_active: false }, `Deactivate ${u.email}? They will be signed out everywhere and blocked from every request.`)
                          }
                        >
                          <Ban className="h-3.5 w-3.5" />
                          Deactivate
                        </Button>
                      ) : (
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => act(u, { is_active: true }, `Reactivate ${u.email}?`)}
                        >
                          <CheckCircle2 className="h-3.5 w-3.5" />
                          Reactivate
                        </Button>
                      )}
                      {u.is_admin ? (
                        <Button
                          variant="secondary"
                          size="sm"
                          disabled={u.email === me?.email}
                          title={
                            u.email === me?.email
                              ? 'You cannot revoke your own admin access'
                              : undefined
                          }
                          onClick={() =>
                            act(u, { is_admin: false }, `Revoke admin access for ${u.email}?`)
                          }
                        >
                          <ShieldOff className="h-3.5 w-3.5" />
                        </Button>
                      ) : (
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() =>
                            act(
                              u,
                              { is_admin: true },
                              `Grant admin to ${u.email}? They will be able to see every account, all cost data, and deactivate other users — including you.`,
                            )
                          }
                        >
                          <Shield className="h-3.5 w-3.5" />
                        </Button>
                      )}

                      {/* LAST, AND SEPARATED. Everything to its left is reversible; this is
                          not. Sitting it flush against Deactivate is how a tired admin
                          deletes an account they meant to suspend, so it gets its own group
                          and the only destructive styling on the row. Disabled on your own
                          row — the server refuses it too, but a disabled button states the
                          rule before the click rather than explaining it in a toast after. */}
                      <span className="ml-1.5 border-l border-border/70 pl-1.5">
                        <Button
                          variant="ghost"
                          size="sm"
                          loading={destroy.isPending}
                          disabled={u.email === me?.email}
                          title={
                            u.email === me?.email
                              ? 'You cannot delete your own account'
                              : `Permanently delete ${u.email}`
                          }
                          aria-label={`Permanently delete ${u.email}`}
                          className="text-destructive hover:bg-destructive/10"
                          onClick={() => destroy.mutate(u)}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* ── Drill-down ────────────────────────────────────────────────────── */}
      {openUser && detail.data && (
        <Card variant="outline">
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <h2 className="text-sm font-semibold">
              {detail.data.user.email}
              <span className="ml-2 text-xs font-normal text-muted-foreground">
                last {detail.data.window_days} days
              </span>
            </h2>
            {detail.data.cost_data_available && (
              <span className="text-sm font-medium tabular-nums">
                {usd(detail.data.ai_cost_usd)} total
              </span>
            )}
          </div>

          <div className="mt-5 grid gap-6 lg:grid-cols-2">
            <div>
              <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                AI cost by feature
              </p>
              {!detail.data.cost_data_available ? (
                <p className="mt-3 text-xs text-muted-foreground">Cost tracking is off.</p>
              ) : detail.data.by_feature.length === 0 ? (
                <p className="mt-3 text-xs text-muted-foreground">No AI calls in this window.</p>
              ) : (
                <dl className="mt-3 space-y-2">
                  {detail.data.by_feature.map((f) => (
                    <div
                      key={f.feature}
                      className="flex items-baseline justify-between gap-4 border-b border-border/60 pb-1.5 last:border-0"
                    >
                      <dt className="font-mono text-xs">{f.feature}</dt>
                      <dd className="shrink-0 text-xs tabular-nums">
                        <span className="text-muted-foreground">{f.calls} · </span>
                        <span className="font-medium">{usd(f.cost_usd)}</span>
                      </dd>
                    </div>
                  ))}
                </dl>
              )}
            </div>

            <div>
              <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                Recent sessions
              </p>
              {detail.data.recent_sessions.length === 0 ? (
                <p className="mt-3 text-xs text-muted-foreground">None yet.</p>
              ) : (
                <ul className="mt-3 space-y-2">
                  {detail.data.recent_sessions.slice(0, 8).map((s) => (
                    <li
                      key={s.id}
                      className="flex items-baseline justify-between gap-4 border-b border-border/60 pb-1.5 last:border-0"
                    >
                      <span className="text-xs">
                        {formatDate(s.created_at)}
                        <span className="ml-2 text-muted-foreground">{s.status}</span>
                      </span>
                      <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                        {s.questions_asked} questions
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </Card>
      )}

      <AuditTrail />
    </div>
  );
}

/**
 * Admin actions only, not the whole event log — audit_logs also carries every
 * interview and report event, which would bury the handful of entries anyone
 * opens this for.
 */
function AuditTrail() {
  const { data } = useQuery({
    queryKey: ['admin', 'audit'],
    queryFn: async () =>
      (await getBrowserApiClient().get('/api/v1/admin/audit?limit=25')).data as {
        entries: {
          at: string;
          action: string;
          actor: string | null;
          target: string | null;
          before: Record<string, boolean> | null;
          after: Record<string, boolean> | null;
          ip: string | null;
        }[];
      },
    retry: false,
  });

  if (!data?.entries.length) return null;

  const changed = (b: Record<string, boolean> | null, a: Record<string, boolean> | null) => {
    if (!b || !a) return '';
    return Object.keys(a)
      .filter((k) => b[k] !== a[k])
      .map((k) => `${k}: ${b[k]} → ${a[k]}`)
      .join(', ');
  };

  return (
    <Card variant="outline">
      <h2 className="text-sm font-semibold">Recent admin actions</h2>
      <p className="mt-0.5 text-xs text-muted-foreground">
        Append-only. Every change to someone&apos;s access is recorded with who made it.
      </p>
      <ul className="mt-4 space-y-2">
        {data.entries.map((e, i) => (
          <li
            key={`${e.at}-${i}`}
            className="flex flex-wrap items-baseline gap-x-2 gap-y-1 border-b border-border/60 pb-2 text-xs last:border-0"
          >
            <span className="font-mono text-[10px] text-muted-foreground">
              {new Date(e.at).toLocaleString()}
            </span>
            <span className="font-medium">{e.actor ?? 'unknown'}</span>
            <span className="text-muted-foreground">→</span>
            <span>{e.target ?? '—'}</span>
            <span className="text-muted-foreground">{changed(e.before, e.after)}</span>
            {e.ip && <span className="font-mono text-[10px] text-muted-foreground">{e.ip}</span>}
          </li>
        ))}
      </ul>
    </Card>
  );
}
