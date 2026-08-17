/**
 * Number formatting for the admin analytics screens.
 *
 * These live in `lib/` rather than inside a page because two admin pages now print the
 * same three kinds of number — money in dollars, money in rupees, and bytes — and a
 * formatter copied into a second page is a formatter that will eventually disagree with
 * the first about how many decimals a figure deserves. The AI cost page and the analytics
 * page are read side by side; a total that renders as "$1.23" on one and "$1.2300" on the
 * other reads as two different measurements.
 *
 * Every function here is total: no input produces `NaN` or `Infinity` on screen. An admin
 * page that renders "NaN B" has turned a missing figure into a bug report, and the figure
 * it was missing is usually the one worth knowing about.
 */

/**
 * Binary units, because the byte counts these format come from `pg_total_relation_size`,
 * which Postgres reports and `pg_size_pretty` renders in the same 1024-based steps. Using
 * decimal units here would put a number on screen that does not match what an operator
 * sees in psql for the same table.
 */
const BYTE_UNITS = ['B', 'KB', 'MB', 'GB', 'TB'] as const;

/**
 * Bytes, at the largest unit that keeps the number small.
 *
 * One decimal above bytes, none at bytes: a vector cache that has just been created holds
 * a few hundred bytes and "0.3 KB" is worse than "312 B", while a saturated one runs to
 * megabytes where the individual bytes are noise. 1536 reads as "1.5 KB" rather than a
 * rounded-away "2 KB", which matters because the table/index split is usually the point of
 * looking — rounding both halves to whole units can make them stop summing to the total.
 *
 * Negative and non-finite inputs collapse to "0 B" rather than propagating: a byte count
 * cannot be negative, so one is a broken read, and printing "-1.0 KB" invites someone to
 * explain it.
 */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';

  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < BYTE_UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }

  return unit === 0
    ? `${Math.round(value)} ${BYTE_UNITS[unit]}`
    : `${value.toFixed(1)} ${BYTE_UNITS[unit]}`;
}

/**
 * Rupees, grouped the Indian way.
 *
 * `en-IN` is not a cosmetic choice: it groups as 12,34,567 rather than 1,234,567, and this
 * product bills Indian students in rupees, so the Western grouping would make an operator
 * misread a lakh as a million at a glance.
 *
 * Takes the `_inr` value the API already computed. The server divides paise by 100 once
 * and rounds; doing that arithmetic again in the browser is how a total ends up as
 * ₹49.000000000000004, and float division of money in two places is two chances to round
 * differently. Paise never enters this function.
 *
 * Paise are dropped above ₹1,000, where they are noise against the total, and kept below
 * it, where a ₹49.50 item genuinely costs that.
 */
export function formatRupees(inr: number): string {
  if (!Number.isFinite(inr)) return '₹0';

  const digits = Math.abs(inr) >= 1000 || Number.isInteger(inr) ? 0 : 2;
  const grouped = new Intl.NumberFormat('en-IN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(inr);

  return `₹${grouped}`;
}

/**
 * Dollars, at the precision the number deserves.
 *
 * A single cross-question costs about $0.0004 and a month of totals runs to dollars.
 * Formatting both to two decimals turns every per-call figure into "$0.00", which reads as
 * free — and "free" is the one conclusion these pages exist to disprove.
 *
 * This was defined privately inside the AI cost page; the analytics page prints the same
 * per-call figures from the same ledger, so it moved here rather than being copied.
 */
export function usd(v: number): string {
  if (!Number.isFinite(v) || v === 0) return '$0';
  if (Math.abs(v) < 0.01) return `$${v.toFixed(5)}`;
  if (Math.abs(v) < 1) return `$${v.toFixed(4)}`;
  return `$${v.toFixed(2)}`;
}

/**
 * How full a feature's slice of the vector cache is, as a percentage of its LRU ceiling.
 *
 * Clamped at 100 because the ceiling is enforced by a trim that only runs on the write
 * path, every `_EVICT_EVERY` writes — a feature can legitimately sit slightly over its cap
 * between trims, and a progress bar that renders at 103% looks like a arithmetic bug
 * rather than the scheduling detail it is.
 *
 * An absent or zero ceiling yields 0 rather than dividing: "no ceiling configured" is not
 * "completely full", and Infinity is not a bar width.
 */
export function saturationPct(entries: number, maxRows: number): number {
  if (!Number.isFinite(entries) || !Number.isFinite(maxRows) || maxRows <= 0) return 0;
  if (entries <= 0) return 0;
  return Math.min(100, (entries / maxRows) * 100);
}
