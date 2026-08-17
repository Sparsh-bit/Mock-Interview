import { describe, expect, it } from 'vitest';

import { formatBytes, formatRupees, saturationPct, usd } from './admin-metrics';

/**
 * These formatters render figures nobody double-checks — an operator reads the storage
 * panel once, believes it, and decides whether the cache needs a bigger ceiling. So the
 * cases that matter are the ones where a plausible-looking string is wrong: an empty cache
 * that formats as "NaN", a lakh that groups as a million, a per-call cost that rounds to
 * "$0.00" and reads as free.
 */

describe('formatBytes', () => {
  it('keeps one decimal above bytes, so a half-unit survives', () => {
    // The case the panel is built on: table and index bytes are usually a fraction of a
    // unit apart, and rounding both to whole units stops them summing to the total.
    expect(formatBytes(1536)).toBe('1.5 KB');
    expect(formatBytes(1024)).toBe('1.0 KB');
    expect(formatBytes(1024 * 1024)).toBe('1.0 MB');
    expect(formatBytes(1024 * 1024 * 1024)).toBe('1.0 GB');
  });

  it('prints raw bytes without a decimal', () => {
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(1023)).toBe('1023 B');
  });

  it('renders an empty cache as 0 B, never NaN', () => {
    // An empty cache is a real state with a real meaning. "NaN B" would make it look like
    // the read failed, which is a different state entirely and handled elsewhere.
    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(Number.NaN)).toBe('0 B');
    expect(formatBytes(Number.POSITIVE_INFINITY)).toBe('0 B');
    expect(formatBytes(-1)).toBe('0 B');
  });

  it('stops at terabytes rather than inventing a unit', () => {
    expect(formatBytes(1024 ** 5)).toBe('1024.0 TB');
  });
});

describe('formatRupees', () => {
  it('groups the Indian way, not the Western one', () => {
    // 12,34,567 and 1,234,567 are the same number and look like different orders of
    // magnitude. This is the whole reason the locale is pinned.
    expect(formatRupees(1234567)).toBe('₹12,34,567');
    expect(formatRupees(100000)).toBe('₹1,00,000');
  });

  it('keeps paise on small amounts and drops them on large ones', () => {
    expect(formatRupees(49.5)).toBe('₹49.50');
    expect(formatRupees(499)).toBe('₹499');
    // Above a thousand the paise are noise against the total.
    expect(formatRupees(12345.67)).toBe('₹12,346');
  });

  it('renders no revenue as ₹0, never NaN', () => {
    expect(formatRupees(0)).toBe('₹0');
    expect(formatRupees(Number.NaN)).toBe('₹0');
  });
});

describe('usd', () => {
  it('does not round a per-call cost away to zero', () => {
    // $0.0004 formatted to two decimals is "$0.00", which reads as free. That conclusion
    // is exactly what the cost pages exist to disprove.
    expect(usd(0.0004)).toBe('$0.00040');
    expect(usd(0.0731)).toBe('$0.0731');
  });

  it('uses two decimals once the figure is dollars', () => {
    expect(usd(12.3456)).toBe('$12.35');
    expect(usd(1)).toBe('$1.00');
  });

  it('renders nothing-spent as $0, never NaN', () => {
    expect(usd(0)).toBe('$0');
    expect(usd(Number.NaN)).toBe('$0');
  });
});

describe('saturationPct', () => {
  it('reports a feature against its LRU ceiling', () => {
    expect(saturationPct(250, 1000)).toBe(25);
    expect(saturationPct(1000, 1000)).toBe(100);
  });

  it('clamps past the ceiling, because the trim only runs on writes', () => {
    // A feature can sit briefly over its cap between eviction passes. A 103% bar looks
    // like an arithmetic bug rather than the scheduling detail it actually is.
    expect(saturationPct(1030, 1000)).toBe(100);
  });

  it('treats a missing ceiling as 0, not as full', () => {
    expect(saturationPct(500, 0)).toBe(0);
    expect(saturationPct(500, Number.NaN)).toBe(0);
    expect(saturationPct(0, 1000)).toBe(0);
  });
});
