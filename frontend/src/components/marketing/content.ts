/**
 * THE ONLY PLACE THE PUBLIC SITE STATES A FACT — components/marketing/content.ts
 *
 * Every number, name and price on the landing page is here, and each one is either counted
 * from the repository or read from the backend at runtime. That is not tidiness; it is the
 * rule that DESIGN-RULES.md sets out and that the previous landing page had to write a whole
 * finale about breaking. "50+ company tracks" and "2,000+ question bank" were both rounded up
 * until somebody counted, and the honest figures — 24 and 87 — are better copy anyway,
 * because a rounded number is a claim and a counted one is evidence.
 *
 * WHERE EACH FIGURE COMES FROM:
 *   RECRUITERS / TRACK_COUNT   backend/knowledge/companies/catalogue.yaml (12 companies, 24
 *                              programs). If you add a company there, add it here; the
 *                              marquee and the fit-list both read this array.
 *   QUESTION_COUNT             backend/app/data/java_fundamentals.py
 *   SUBTOPIC_COUNT             backend/knowledge/subtopics.yaml
 *   AI_SURFACE_COUNT           the number of screens that call an AI provider
 *
 * PRICES ARE DELIBERATELY NOT HERE. `services/billing/plans.py` is the single source of truth
 * for what anything costs, `/pricing` fetches it from `GET /billing/items`, and a price typed
 * into a marketing file is a price that will be wrong the first time one changes. The pricing
 * section on the landing page states the shape of the offer — free tier, pay per session, no
 * subscription — and sends you to `/pricing` for the figure.
 */

export const RECRUITERS = [
  { name: 'Cognizant', programs: 'GenC · GenC Next · Digital Nurture', tracks: 4 },
  { name: 'TCS', programs: 'NQT · Ninja · Digital', tracks: 3 },
  { name: 'Infosys', programs: 'SP · DSE · Power Programmer', tracks: 3 },
  { name: 'Wipro', programs: 'Elite NTH · Turbo', tracks: 3 },
  { name: 'Accenture', programs: 'ASE · Advanced App Engineer', tracks: 2 },
  { name: 'Capgemini', programs: 'Analyst · Senior Analyst', tracks: 2 },
  { name: 'HCLTech', programs: 'TechBee · Graduate Engineer', tracks: 2 },
  { name: 'Tech Mahindra', programs: 'Associate Software Engineer', tracks: 1 },
  { name: 'LTIMindtree', programs: 'Graduate Engineer Trainee', tracks: 1 },
  { name: 'IBM', programs: 'Associate System Engineer', tracks: 1 },
  { name: 'Deloitte', programs: 'Analyst · NLA', tracks: 1 },
  { name: 'Amazon', programs: 'SDE I · Support Engineer', tracks: 1 },
] as const;

export const COMPANY_COUNT = RECRUITERS.length;
export const TRACK_COUNT = RECRUITERS.reduce((n, r) => n + r.tracks, 0);
export const QUESTION_COUNT = 87;
export const SUBTOPIC_COUNT = 48;
export const AI_SURFACE_COUNT = 13;

/**
 * THE SIX ROUNDS — the film's six beats, and the same six the product actually runs.
 *
 * EACH ROUND USED TO CARRY A `tone` — its colour in the product's own six-colour system
 * (lib/tones.ts) — on the stated reasoning that "the film's chips agree with the sidebar a
 * visitor sees ten minutes later". Two things were wrong with that, and the second is why it
 * is gone rather than corrected:
 *
 *   1. Nothing rendered it. No component in `components/marketing/` ever read the field; the
 *      film's beats are gold on espresso and always were. It was six strings asserting an
 *      agreement that nothing drew.
 *   2. Two of the six were already wrong — communication was `coral` here and is `teal` in
 *      ROUTE_TONE; report was `emerald` here and is `teal` there. Nobody could have noticed,
 *      because there was no chip to look at.
 *
 * Dead data that disagrees with live data is worse than dead data: the next person to need a
 * round's colour finds this first, it looks authoritative, and the product acquires a second
 * answer. `lib/tones.ts` is the only answer. `tones.test.ts` now keeps the door shut — if a
 * `tone` is ever added back it must agree with ROUTE_TONE, and something must render it.
 */
export const ROUNDS = [
  {
    id: 'interview',
    n: '01',
    name: 'Interview',
    href: '/interview',
    label: 'It asks a follow-up when your answer is thin',
    blurb:
      'Adaptive questions drawn from real previous-year papers, and a cross-question the moment an answer sounds rehearsed.',
  },
  {
    id: 'gd',
    n: '02',
    name: 'Group discussion',
    href: '/gd',
    label: 'Three AI candidates who will talk over you',
    blurb:
      'Eight minutes against three panelists with their own opinions. Stay quiet and they move on without you.',
  },
  {
    id: 'coding',
    n: '03',
    name: 'Coding',
    href: '/practice',
    label: 'It runs your code, then judges the approach',
    blurb:
      'A real compiler, a verdict on complexity — and a flag on work that arrived too clean to have been written here.',
  },
  {
    id: 'communication',
    n: '04',
    name: 'Communication',
    href: '/communication',
    label: 'Every pause and filler, counted',
    blurb:
      'Spoken answers scored on pace, structure and filler. The failure nobody can see in themselves, made a number.',
  },
  {
    id: 'quiz',
    n: '05',
    name: 'Quiz',
    href: '/quiz',
    label: 'Timed MCQs, fresh or from the bank',
    blurb:
      'Generated for your target company, or drawn from the curated bank. Never charged, on any plan.',
  },
  {
    id: 'report',
    n: '06',
    name: 'Report',
    href: '/report',
    label: 'One score, four competencies, every topic ranked',
    blurb:
      'What the panel would have said about you, with the topic to fix first and the hours it will take.',
  },
] as const;

export type Round = (typeof ROUNDS)[number];

/**
 * WHAT EACH RECRUITER ACTUALLY WEIGHTS. Two are shown side by side on the landing page
 * because the contrast is the argument: the same candidate, prepared the same way, is
 * mis-prepared for one of these two. Figures are the ones `/prepare` builds its plan from.
 */
export const WEIGHTINGS = [
  {
    company: 'Amazon',
    rows: [
      { label: 'Data structures & algorithms', pct: 45 },
      { label: 'Problem solving', pct: 20 },
      { label: 'Leadership Principles', pct: 15 },
    ],
  },
  {
    company: 'TCS',
    rows: [
      { label: 'Aptitude & reasoning', pct: 25 },
      { label: 'C / Java / Python', pct: 20 },
      { label: 'Data structures', pct: 15 },
    ],
  },
] as const;

export const NAV_LINKS = [
  { href: '#rounds', label: 'How it works' },
  { href: '#proof', label: 'What it measures' },
  { href: '/pricing', label: 'Pricing' },
  { href: '/demo', label: 'Sample report' },
] as const;
