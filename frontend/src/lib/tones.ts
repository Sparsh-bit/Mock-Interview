/**
 * The six accents, resolved to classes — lib/tones.ts
 *
 * DESIGN-RULES binds each colour to exactly one meaning: indigo the product and its primary
 * actions, amber preparation and money, emerald verified and passed, coral flagged and wrong,
 * teal data and measurement, plum the behavioural rounds. This file is that table as code, so
 * the rail, the page headers and anything else that needs to say "you are in the analytics
 * part of the product" all reach for the same value.
 *
 * EVERY CLASS IS WRITTEN OUT IN FULL, and that is not verbosity. Tailwind compiles the classes
 * it can literally see in the source — `bg-accent-${tone}-soft` produces a string at runtime
 * that the compiler never encountered, so the class is not in the stylesheet and the colour
 * silently vanishes. It works in dev because the JIT has usually seen the class somewhere else;
 * it disappears in the production build. That has already cost this codebase a round of
 * "the colours are gone in prod", so: no interpolation, ever.
 */

export const TONES = {
  indigo: {
    icon: 'text-accent-indigo-ink',
    activeBg: 'bg-accent-indigo-soft',
    activeText: 'text-accent-indigo-ink',
    rail: 'bg-accent-indigo',
    soft: 'bg-accent-indigo-soft',
    ink: 'text-accent-indigo-ink',
    border: 'border-accent-indigo/30',
    ring: 'ring-accent-indigo/25',
  },
  amber: {
    icon: 'text-accent-amber-ink',
    activeBg: 'bg-accent-amber-soft',
    activeText: 'text-accent-amber-ink',
    rail: 'bg-accent-amber',
    soft: 'bg-accent-amber-soft',
    ink: 'text-accent-amber-ink',
    border: 'border-accent-amber/30',
    ring: 'ring-accent-amber/25',
  },
  emerald: {
    icon: 'text-accent-emerald-ink',
    activeBg: 'bg-accent-emerald-soft',
    activeText: 'text-accent-emerald-ink',
    rail: 'bg-accent-emerald',
    soft: 'bg-accent-emerald-soft',
    ink: 'text-accent-emerald-ink',
    border: 'border-accent-emerald/30',
    ring: 'ring-accent-emerald/25',
  },
  coral: {
    icon: 'text-accent-coral-ink',
    activeBg: 'bg-accent-coral-soft',
    activeText: 'text-accent-coral-ink',
    rail: 'bg-accent-coral',
    soft: 'bg-accent-coral-soft',
    ink: 'text-accent-coral-ink',
    border: 'border-accent-coral/30',
    ring: 'ring-accent-coral/25',
  },
  teal: {
    icon: 'text-accent-teal-ink',
    activeBg: 'bg-accent-teal-soft',
    activeText: 'text-accent-teal-ink',
    rail: 'bg-accent-teal',
    soft: 'bg-accent-teal-soft',
    ink: 'text-accent-teal-ink',
    border: 'border-accent-teal/30',
    ring: 'ring-accent-teal/25',
  },
  plum: {
    icon: 'text-accent-plum-ink',
    activeBg: 'bg-accent-plum-soft',
    activeText: 'text-accent-plum-ink',
    rail: 'bg-accent-plum',
    soft: 'bg-accent-plum-soft',
    ink: 'text-accent-plum-ink',
    border: 'border-accent-plum/30',
    ring: 'ring-accent-plum/25',
  },
} as const;

export type Tone = keyof typeof TONES;

/**
 * Which colour each destination owns.
 *
 * ONE PLACE, because the whole value of the scheme is that the rail entry, the page header and
 * any card pointing at a page all agree. Two of them disagreeing is worse than no colour at
 * all: it teaches the reader that the colours mean nothing.
 *
 * Profile and Settings are deliberately absent. They are not features, they are the account —
 * giving them a colour of their own would put them on the same footing as the rounds, and
 * there are only six colours to spend.
 */
export const ROUTE_TONE: Record<string, Tone> = {
  '/dashboard': 'indigo',
  '/prepare': 'amber',
  '/interview': 'indigo',
  '/quiz': 'amber',
  '/communication': 'teal',
  '/gd': 'plum',
  '/report': 'teal',
  // Measurement, like the reports and the analytics it sits beside: the deck review
  // produces a score out of 100 against a fixed rubric. Not amber — amber is effort
  // and preparation, and this measures a finished artefact rather than practising one.
  '/deck': 'teal',
  '/tracks': 'indigo',
  '/analytics': 'teal',
  '/achievements': 'emerald',
  '/pricing': 'amber',
  '/ai-usage': 'teal',
};

/**
 * HOW HARD SOMETHING IS, in colour — the heat scale from docs/DESIGN-LANGUAGE §2.
 *
 * Heat means difficulty and only difficulty: teal is a warm-up, amber is the real thing, coral
 * is the round that decides it. It is deliberately NOT the emerald/coral pair the score bands
 * use for passed and failed, because **hard is not bad** — a candidate choosing the hard set is
 * doing the right thing, and colouring that choice like a failure is telling them otherwise.
 *
 * IT LIVES HERE BECAUSE IT WAS ABOUT TO EXIST THREE TIMES. The tracks page had one, the quiz
 * page had another for its selected chip, and the practice page was using
 * `Badge variant={hard ? 'danger' : easy ? 'success' : 'warning'}` — the pass/fail vocabulary
 * applied to difficulty, which is exactly the confusion this scale exists to prevent. Three
 * private copies of a colour rule is how the score bands ended up with five.
 *
 * Every class is written out in full. Tailwind compiles the classes it can literally see, so
 * an interpolated one survives dev and vanishes from the production build with no error.
 */
export const HEAT = {
  easy: {
    label: 'Warm-up',
    chip: 'bg-accent-teal-soft text-accent-teal-ink',
    dot: 'bg-accent-teal',
    border: 'border-accent-teal',
  },
  medium: {
    label: 'Standard',
    chip: 'bg-accent-amber-soft text-accent-amber-ink',
    dot: 'bg-accent-amber',
    border: 'border-accent-amber',
  },
  hard: {
    label: 'Runs hot',
    chip: 'bg-accent-coral-soft text-accent-coral-ink',
    dot: 'bg-accent-coral',
    border: 'border-accent-coral',
  },
} as const;

export type HeatLevel = keyof typeof HEAT;

/**
 * The heat for a difficulty string, or null when it is absent or unrecognised.
 *
 * Null rather than a guess: a difficulty the backend adds later should render as an honest
 * unlabelled item rather than being silently miscoloured as something it is not.
 */
export function heatFor(difficulty: string | null | undefined) {
  if (!difficulty) return null;
  return HEAT[difficulty.toLowerCase() as HeatLevel] ?? null;
}
