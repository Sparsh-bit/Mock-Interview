/**
 * The direct-start drive link — lib/interview/drive.ts
 *
 * WHAT THIS IS FOR. A student sitting the Cognizant Digital Nurture 5.0 technical interview
 * wants one thing from this product on the morning of the drive: the same interview, now, to
 * practise on. Getting there today costs six deliberate gestures — pick "Technical", find
 * Cognizant among twenty-four company chips, pick "Digital Nurture — Java FSE" among its
 * programs, scroll past the resume box, press Build, press Start. Every one of those is a
 * chance to pick the wrong thing, and one of them (the program chip) silently threw away the
 * single most load-bearing fact in the whole request. See `driveHref` for that.
 *
 * WHY THE LOGIC LIVES HERE AND NOT IN THE COMPONENT. Two reasons, both about being able to
 * test it. The vitest environment in this workspace is `node`, not jsdom (see
 * frontend/vitest.config.ts) — there is no DOM, so a component that renders framer-motion and
 * next/link cannot be mounted in a test at all. And the parts worth pinning are not the
 * markup: they are the URL, the strict parse of `isTechnical`, and the rule that the date in
 * the copy is allowed to go quiet but never allowed to go wrong. Those are pure functions over
 * strings, so they live in a module with no React in it and get tested directly.
 *
 * WHAT IS DELIBERATELY *NOT* HERE. The link does not pre-fill the "Anything specific?" focus
 * box. It would be easy — "Java, OOP, React, SQL, Spring Boot, coding" is exactly the syllabus
 * — and it would be actively harmful. That box is a *steer*: naming a topic pulls plan slots
 * towards it and away from the rest. Naming every area steers towards nothing while looking
 * like a preference the candidate expressed, so the one field that is genuinely theirs would
 * arrive pre-answered on their behalf. The syllabus already covers all six areas by weight; a
 * blank focus box is the correct request, not an incomplete one.
 */

/**
 * The Cognizant Digital Nurture track, identified by SLUG rather than by id.
 *
 * NEVER HARDCODE THE TRACK UUID. Track rows are minted with `uuid.uuid4()` by the seeder
 * (backend/scripts/seed_db.py) and by the auto-seed in `app/api/v1/questions.py`, so the id
 * differs in every environment — dev, preview, production. A literal id copied out of a local
 * database would deep-link correctly on the machine it was copied from and, everywhere else,
 * fail the `tracks.some((t) => t.id === requestedTrackId)` check on the setup page and fall
 * through to `tracks[0]`, which is Accenture's "Advanced ASE" (the list is ordered by track
 * name across all companies, not per company). The candidate would land on a page that says
 * Cognizant and builds an Accenture interview — the exact failure the long comment at the top
 * of the setup page was written for.
 *
 * The slug pair is stable by contract: seed_db.py maps
 * `("cognizant", "Digital Nurture — Java FSE") -> "java-fse"` and carries a comment saying it
 * must not be renamed, because existing reports point at it.
 */
export const DRIVE_COMPANY_SLUG = 'cognizant';
export const DRIVE_TRACK_SLUG = 'java-fse';

/** The eyebrow line. Names the drive, so the title does not have to. */
export const DRIVE_EYEBROW = 'Cognizant Digital Nurture 5.0';

/*
 * THE DATE IS CONTENT, AND THESE TWO CONSTANTS ARE ONE FACT.
 *
 * EDIT THEM TOGETHER OR NOT AT ALL. `DRIVE_LABEL` is what a human reads; `DRIVE_UNTIL` is
 * when that sentence stops being true. Two literals for one fact drift, and the drifted state
 * is the worst one available: a card confidently advertising a date that has passed, which
 * tells a student the product is not maintained.
 *
 * They are not derived from each other on purpose. Deriving the label from the timestamp needs
 * `toLocaleDateString`, which formats differently on the Cloudflare edge runtime than in the
 * browser and would put a hydration mismatch inside the one string that must never look
 * broken. Two adjacent literals with this comment between them is the smaller risk.
 *
 * The timestamp is IST (+05:30) because this is an Indian campus drive and "the 24th" means
 * the 24th where the candidate is sitting, not in UTC — a naive parse would expire the label
 * five and a half hours early, i.e. mid-afternoon on the day it matters most.
 *
 * NOTHING BRANCHES ON THIS BUT THE SENTENCE. The href, the params, the syllabus, the plan and
 * the interview are identical before and after the date. It is not a feature flag with a
 * hidden expiry; it is a phrase that goes quiet. After the drive the card keeps working and
 * simply stops naming a day.
 */
export const DRIVE_LABEL = '24 August';
export const DRIVE_UNTIL = Date.parse('2026-08-24T23:59:59+05:30');

/** localStorage key for "I have seen this, stop showing it to me". */
export const DRIVE_DISMISS_KEY = 'interviewos:drive:cognizant-dn5';

/**
 * The minimum shape of a track this module needs.
 *
 * Structural rather than importing `Track` from hooks/useData so a test can build a two-field
 * fixture instead of a full API row, and so this module has no reason to import anything that
 * touches the query client.
 */
export interface DriveTrackShape {
  id: string;
  name: string;
  slug: string;
  company: { name: string; slug: string };
}

/**
 * The Cognizant Digital Nurture — Java FSE track out of the track list, or null.
 *
 * NULL IS A REAL ANSWER AND THE CALLER MUST RENDER NOTHING. The tracks endpoint auto-seeds on
 * first hit, so on a genuinely fresh database this returns null until something has asked for
 * the list; it also returns null while the query is still loading. Both cases must produce no
 * card rather than a card whose link cannot work. A dead CTA on the dashboard is worse than no
 * CTA, because the student clicks it during the ten minutes before their real interview.
 *
 * Matched on both slugs, not on the company alone: Cognizant has several programs in the
 * catalogue (GenC, GenC Next, …) and this link is only ever about one of them.
 */
export function findDriveTrack<T extends DriveTrackShape>(
  tracks: readonly T[] | undefined | null,
): T | null {
  const rows = tracks ?? [];
  const exact = rows.find(
    (t) => t.company.slug === DRIVE_COMPANY_SLUG && t.slug === DRIVE_TRACK_SLUG,
  );
  if (exact) return exact;

  /*
   * FALLBACK BY NAME, WITHIN COGNIZANT ONLY.
   *
   * The slug is the right primary key and `java-fse` is pinned by
   * `seed_db._LEGACY_TRACK_SLUGS` precisely so it cannot move. But that pin protects rows
   * the CURRENT seeder wrote, and a database that has been carrying this project for a
   * while may hold a Cognizant Digital Nurture row created before the catalogue seeding
   * existed, under whatever slug that older code chose. There is no way to tell from here,
   * and the failure is completely silent: `findDriveTrack` returns null, the component
   * renders nothing, and the student who came here on the morning of the drive sees no card
   * and no reason for its absence.
   *
   * So the slug miss falls back to the track NAME, and the name is a strong signal —
   * "Digital Nurture" appears on exactly one Cognizant program in the catalogue, and the
   * company slug is checked first, so this cannot reach into another recruiter's tracks.
   *
   * What it deliberately does NOT do is widen to "any Cognizant track". GenC, GenC Next and
   * GenC Pro are different interviews with different research and a different syllabus key,
   * and a card that says Digital Nurture and builds a GenC Next plan is worse than no card
   * — it is the class of bug that once greeted a sales candidate as an Accenture ASE.
   * Returning null when no Digital Nurture row exists remains the correct answer.
   */
  return (
    rows.find(
      (t) =>
        t.company.slug === DRIVE_COMPANY_SLUG &&
        t.name.toLowerCase().includes('digital nurture'),
    ) ?? null
  );
}

/**
 * The deep link into the existing /interview setup page.
 *
 * NO NEW ROUTE, DELIBERATELY. /interview is already `export const runtime = 'edge'` and
 * already wraps `useSearchParams` in a Suspense boundary, both of which a new route would have
 * to reproduce — and a missing edge export has broken this project's Cloudflare Pages build
 * before. Adding a param to a page that already reads params costs nothing and cannot break a
 * deploy.
 *
 * `program` IS THE POINT OF THIS FUNCTION. `syllabus.resolve(company, program)` in the backend
 * keys on the company and program STRINGS and — by explicit design, documented in its
 * docstring — takes no track id, so the carrier track cannot reach that decision. Which means
 * an empty `program` resolves to None, which means the Cognizant field research is skipped
 * entirely and the candidate gets the generic scenario-heavy plan they complained about. The
 * program is passed here as `track.name`, which is literally "Digital Nurture — Java FSE" and
 * slugifies to the exact key the syllabus index and its alias table both hold.
 *
 * The company is taken from `track.company.name` rather than written as the literal
 * "Cognizant" for the same reason the id is not hardcoded: the database row is the truth, and
 * it is what the company chip on the setup page would have set.
 *
 * `isTechnical=true` is a statement, not an inference. The backend can guess technical-ness
 * from the role title by keyword match, and this is a case where it does not need to guess.
 *
 * `autostart=1` asks the setup page to submit itself. It is a REQUEST, not a command — the
 * page gates it on a resume already being on file, because POST /plan charges an interview
 * credit before it generates anything. See the autostart effect on the setup page for why that
 * gate is not cosmetic.
 */
export function driveHref(track: DriveTrackShape): string {
  const params = new URLSearchParams({
    trackId: track.id,
    company: track.company.name,
    program: track.name,
    isTechnical: 'true',
    autostart: '1',
  });
  return `/interview?${params.toString()}`;
}

/**
 * The card's headline.
 *
 * `dateLive` is passed in rather than read from the clock here so the caller decides WHEN the
 * clock is read. That matters: the component reads it in an effect, after mount, so the
 * server-rendered HTML and the first client render agree on the evergreen sentence and only
 * then upgrade to the dated one. Calling `Date.now()` during render would compare an edge
 * render at one instant against a browser render at another and produce a hydration mismatch
 * across the drive boundary — a once-a-year bug that only ever fires on the day the card
 * matters.
 */
export function driveTitle(dateLive: boolean): string {
  return dateLive
    ? `Start practising now — ${DRIVE_LABEL} technical interview`
    : 'Start practising now — the technical interview';
}

/** Whether the drive date is still worth naming, as of `now`. */
export function driveDateLive(now: number): boolean {
  return now <= DRIVE_UNTIL;
}

/**
 * `?isTechnical=` parsed STRICTLY against two literals.
 *
 * Anything else — absent, empty, "1", "yes", "TRUE", a typo — returns null, which is the setup
 * page's "work it out from the role" default and therefore exactly today's behaviour. A
 * malformed link degrades to a guess instead of asserting a wrong answer, and asserting the
 * wrong answer here is expensive: `isTechnical` decides whether there is a code editor at all,
 * whether coding questions are asked, and whether the panel are engineers or their own field's
 * managers. A stray "?isTechnical=false" typo'd into a share link would hand a Java FSE
 * candidate an HR round.
 *
 * Not case-insensitive on purpose. The only writer of this param is `driveHref` above, so
 * broadening the parse buys nothing and widens what a hand-edited URL can assert.
 */
export function parseIsTechnical(raw: string | null): boolean | null {
  if (raw === 'true') return true;
  if (raw === 'false') return false;
  return null;
}
