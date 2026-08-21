import { describe, it, expect } from 'vitest';
import {
  DRIVE_COMPANY_SLUG,
  DRIVE_LABEL,
  DRIVE_TRACK_SLUG,
  DRIVE_UNTIL,
  driveDateLive,
  driveHref,
  driveTitle,
  findDriveTrack,
  parseIsTechnical,
  type DriveTrackShape,
} from './drive';

/**
 * The drive link, pinned.
 *
 * Vitest runs in the `node` environment here (no jsdom), so the CARD cannot be mounted — but
 * the card is markup. What can go wrong and cost something is in this module: a link that
 * silently starts the wrong company's interview, an `isTechnical` param that asserts the wrong
 * answer, and a date in the copy that goes stale rather than quiet. Those are what these tests
 * are for.
 */

const cognizant: DriveTrackShape = {
  id: 'e4d1a9f0-0000-4000-8000-000000000001',
  name: 'Digital Nurture — Java FSE',
  slug: 'java-fse',
  company: { name: 'Cognizant', slug: 'cognizant' },
};

// The row that `tracks[0]` actually is in production: /api/v1/questions/tracks orders by track
// name across ALL companies, and "Advanced ASE" is alphabetically first in the whole catalogue.
// Every "must not fall through" assertion below is about this row specifically.
const accenture: DriveTrackShape = {
  id: 'e4d1a9f0-0000-4000-8000-000000000002',
  name: 'Advanced ASE',
  slug: 'advanced-ase',
  company: { name: 'Accenture', slug: 'accenture' },
};

const cognizantGenC: DriveTrackShape = {
  id: 'e4d1a9f0-0000-4000-8000-000000000003',
  name: 'GenC',
  slug: 'genc',
  company: { name: 'Cognizant', slug: 'cognizant' },
};

describe('findDriveTrack', () => {
  it('finds the Digital Nurture track regardless of its position in the list', () => {
    expect(findDriveTrack([accenture, cognizantGenC, cognizant])).toBe(cognizant);
  });

  it('returns null while the track list is still loading', () => {
    // The card must render nothing here. A card is better absent than present-and-wrong.
    expect(findDriveTrack(undefined)).toBeNull();
    expect(findDriveTrack(null)).toBeNull();
  });

  it('returns null rather than falling back to the first track', () => {
    // The whole point. A missing Cognizant track must NOT yield Accenture's Advanced ASE, which
    // is exactly what the setup page's own `tracks[0]` fallback used to do.
    expect(findDriveTrack([accenture])).toBeNull();
    expect(findDriveTrack([])).toBeNull();
  });

  it('does not settle for a different Cognizant program', () => {
    // GenC is the same company and the wrong interview. Matching on the company alone is the
    // `or rows[0]` bug in a different costume.
    expect(findDriveTrack([cognizantGenC])).toBeNull();
  });

  it('keys on the slugs the seeder pins, not on display names', () => {
    expect(DRIVE_COMPANY_SLUG).toBe('cognizant');
    expect(DRIVE_TRACK_SLUG).toBe('java-fse');
  });
});

describe('driveHref', () => {
  const href = driveHref(cognizant);
  const query = new URLSearchParams(href.split('?')[1]);

  it('deep-links into the existing /interview route', () => {
    // No new route: /interview already has `export const runtime = 'edge'` and a Suspense
    // boundary, and a missing edge export has broken the Cloudflare build before.
    expect(href.startsWith('/interview?')).toBe(true);
  });

  it('carries the track id from the data, never a literal', () => {
    expect(query.get('trackId')).toBe(cognizant.id);
  });

  it('carries the program, which is the only thing syllabus.resolve can key on', () => {
    // resolve(company, program) takes no track id by design, so an empty program here means the
    // Cognizant syllabus is skipped entirely and the candidate gets the generic plan.
    expect(query.get('program')).toBe('Digital Nurture — Java FSE');
    expect(query.get('company')).toBe('Cognizant');
  });

  it('states the interview kind instead of leaving it to keyword inference', () => {
    expect(query.get('isTechnical')).toBe('true');
  });

  it('requests autostart', () => {
    expect(query.get('autostart')).toBe('1');
  });

  it('does not pre-fill the focus box', () => {
    // Naming every area is not a preference, and this field belongs to the candidate.
    expect(query.get('focus')).toBeNull();
  });

  it('percent-encodes the em dash so the program survives the round trip', () => {
    // "Digital Nurture — Java FSE" contains a literal em dash, and the backend's slugify keys
    // on it. A raw dash in a query string is the kind of thing that survives four hops and dies
    // on the fifth.
    expect(href).not.toContain('—');
    expect(new URLSearchParams(href.split('?')[1]).get('program')).toContain('—');
  });
});

describe('parseIsTechnical', () => {
  it('accepts exactly the two literals it writes', () => {
    expect(parseIsTechnical('true')).toBe(true);
    expect(parseIsTechnical('false')).toBe(false);
  });

  it('degrades anything else to null, meaning "work it out from the role"', () => {
    // null is today's behaviour. Asserting the wrong value instead would decide whether there
    // is a code editor at all — a typo'd share link must not hand a Java FSE candidate an HR
    // round.
    for (const raw of [null, '', '1', '0', 'yes', 'no', 'TRUE', 'True', 'technical', ' true']) {
      expect(parseIsTechnical(raw)).toBeNull();
    }
  });
});

describe('the drive date is content, not logic', () => {
  it('goes quiet rather than stale once the drive has passed', () => {
    const after = driveTitle(false);
    expect(after).toContain('Start practising now');
    // The critical assertion: no stale date. A card advertising a day that has gone is worse
    // than a card that names no day.
    expect(after).not.toContain(DRIVE_LABEL);
  });

  it('names the day while the day is still ahead', () => {
    expect(driveTitle(true)).toContain(DRIVE_LABEL);
  });

  it('treats the drive window as Indian time, not UTC', () => {
    // 23:59 IST on the 24th is still live; one second later is not. A naive parse would expire
    // the label 5h30m early — i.e. mid-afternoon on the day it matters most, which is what the
    // third assertion pins: 18:00Z is 23:30 in Kolkata and must still name the day.
    expect(driveDateLive(Date.parse('2026-08-24T23:59:59+05:30'))).toBe(true);
    expect(driveDateLive(Date.parse('2026-08-25T00:00:00+05:30'))).toBe(false);
    expect(driveDateLive(Date.parse('2026-08-24T18:00:00Z'))).toBe(true);
    // And the corresponding UTC-naive mistake, stated explicitly: 19:00Z is already the 25th in
    // Kolkata, so it must be dead even though the UTC date still reads "the 24th".
    expect(driveDateLive(Date.parse('2026-08-24T19:00:00Z'))).toBe(false);
  });

  it('keeps the human label and the timestamp describing the same day', () => {
    // The two constants are one fact and must be edited together. This test is the thing that
    // notices when only one of them was.
    const labelled = new Date(DRIVE_UNTIL).toLocaleDateString('en-GB', {
      day: 'numeric',
      month: 'long',
      timeZone: 'Asia/Kolkata',
    });
    expect(labelled).toBe(DRIVE_LABEL);
  });
});

describe('finding the track when the slug is not what this build expects', () => {
  /*
   * "i cannot see the poster of 24th august interview for cognizant".
   *
   * The card renders nothing when `findDriveTrack` returns null, and it returns null on any
   * miss — which is right when there genuinely is no Digital Nurture track, and silent and
   * wrong when there is one under an older slug. A database that has carried this project
   * for a while can hold a row created before the catalogue seeding existed; the current
   * `java-fse` pin in seed_db only governs rows the current seeder wrote.
   *
   * The failure had no symptom at all: no card, no console line, nothing to look at. These
   * pin the fallback, and — more importantly — pin what it must NOT do.
   */
  const cognizant = { name: 'Cognizant', slug: 'cognizant' };

  it('still finds the track when the slug is an older one', () => {
    const tracks = [
      { id: 't1', name: 'Digital Nurture — Java FSE', slug: 'cognizant-digital-nurture-java-fse', company: cognizant },
    ];
    expect(findDriveTrack(tracks)?.id).toBe('t1');
  });

  it('prefers the pinned slug when both are somehow present', () => {
    const tracks = [
      { id: 'old', name: 'Digital Nurture — Java FSE', slug: 'cognizant-digital-nurture', company: cognizant },
      { id: 'new', name: 'Digital Nurture — Java FSE', slug: 'java-fse', company: cognizant },
    ];
    expect(findDriveTrack(tracks)?.id).toBe('new');
  });

  it('never falls back to a different Cognizant programme', () => {
    // A card that says Digital Nurture and builds a GenC Next plan is worse than no card:
    // different research, different syllabus key, different interview. This is the same
    // class of bug that once greeted a sales candidate as an Accenture ASE.
    const tracks = [
      { id: 'gn', name: 'GenC Next', slug: 'genc-next', company: cognizant },
      { id: 'gp', name: 'GenC Pro', slug: 'genc-pro', company: cognizant },
    ];
    expect(findDriveTrack(tracks)).toBeNull();
  });

  it('never reaches into another company', () => {
    const tracks = [
      { id: 'x', name: 'Digital Nurture — Java FSE', slug: 'java-fse', company: { name: 'Infosys', slug: 'infosys' } },
    ];
    expect(findDriveTrack(tracks)).toBeNull();
  });
});
