import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

/**
 * The palette is legible — theme-contrast.test.ts
 *
 * WHY THIS EXISTS. The theme was deepened to stop the interface reading as white-on-white, and
 * every one of those changes moves a contrast ratio. Deepening a `-soft` background reduces its
 * contrast with the `-ink` text that sits on it; deepening the ground changes every ratio on
 * the page at once. Those are exactly the edits that get made by eye and shipped illegible,
 * because the author is looking at a 27" display in a bright room and the candidate is on a
 * phone in a hostel corridor.
 *
 * SO THE RATIOS ARE COMPUTED FROM THE ACTUAL CSS, not asserted from the comments beside them.
 * Those comments were accurate when written and a colour change does not update them — a
 * number in a comment is a claim, and this is the check.
 *
 * The rule the design system states: `-ink` is the only tone safe for text under ~18px, and it
 * must clear 4.5:1. The bare tone is for fills and strokes, where 3:1 is the bar for a
 * meaningful graphic. `-soft` is a background and is never text.
 */

const CSS = readFileSync(join(process.cwd(), 'src/app/globals.css'), 'utf8');

/** Pull an `--name: H S% L%;` triple out of the `:root` block. */
function hsl(name: string): [number, number, number] {
  const m = CSS.match(new RegExp(`--${name}:\\s*([\\d.]+)\\s+([\\d.]+)%\\s+([\\d.]+)%`));
  if (!m) throw new Error(`token --${name} not found in globals.css`);
  return [Number(m[1]), Number(m[2]), Number(m[3])];
}

/** sRGB relative luminance, per WCAG 2.1. */
function luminance([h, s, l]: [number, number, number]): number {
  const S = s / 100;
  const L = l / 100;
  const c = (1 - Math.abs(2 * L - 1)) * S;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = L - c / 2;
  const [r1, g1, b1] =
    h < 60
      ? [c, x, 0]
      : h < 120
        ? [x, c, 0]
        : h < 180
          ? [0, c, x]
          : h < 240
            ? [0, x, c]
            : h < 300
              ? [x, 0, c]
              : [c, 0, x];
  const lin = (v: number) => {
    const n = v + m;
    return n <= 0.03928 ? n / 12.92 : ((n + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * lin(r1) + 0.7152 * lin(g1) + 0.0722 * lin(b1);
}

function ratio(a: string, b: string): number {
  const [x, y] = [luminance(hsl(a)), luminance(hsl(b))].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

const ACCENTS = ['indigo', 'amber', 'emerald', 'coral', 'teal', 'plum'] as const;

describe('the maths is right before it judges anything', () => {
  it('computes a known ratio correctly', () => {
    // Black on white is 21:1. If this is wrong every assertion below is meaningless — which is
    // the failure mode of a computed test that nobody sanity-checked.
    const black = luminance([0, 0, 0]);
    const white = luminance([0, 0, 100]);
    expect((white + 0.05) / (black + 0.05)).toBeCloseTo(21, 1);
  });

  it('finds the tokens it claims to check', () => {
    // A regex that stopped matching would make every test below pass by throwing nothing.
    expect(() => hsl('background')).not.toThrow();
    for (const a of ACCENTS) expect(() => hsl(`accent-${a}-ink`)).not.toThrow();
  });
});

describe('body text is legible on every ground it can land on', () => {
  it.each(['background', 'surface', 'surface-elevated', 'muted'])(
    'foreground on --%s',
    (ground) => {
      expect(ratio('foreground', ground)).toBeGreaterThanOrEqual(4.5);
    },
  );

  it('muted-foreground clears 4.5:1 on the ground and on cards', () => {
    // This is the one that breaks first when the ground is deepened, and it is used for every
    // secondary line in the product.
    expect(ratio('muted-foreground', 'background')).toBeGreaterThanOrEqual(4.5);
    expect(ratio('muted-foreground', 'surface-elevated')).toBeGreaterThanOrEqual(4.5);
  });
});

describe('every -ink tone is safe for small text', () => {
  it.each(ACCENTS)('accent-%s-ink on the paper ground', (name) => {
    expect(ratio(`accent-${name}-ink`, 'background')).toBeGreaterThanOrEqual(4.5);
  });

  it.each(ACCENTS)('accent-%s-ink on its own -soft background', (name) => {
    // THE PAIRING THAT ACTUALLY SHIPS. Chips, badges and callouts put ink text on the soft
    // tint of the same hue, so deepening the tint without checking this is how a badge becomes
    // unreadable while every isolated colour still passes.
    expect(ratio(`accent-${name}-ink`, `accent-${name}-soft`)).toBeGreaterThanOrEqual(4.5);
  });

  it('accent-amber-hot is safe too — it is a fourth tone, not a decoration', () => {
    expect(ratio('accent-amber-hot', 'background')).toBeGreaterThanOrEqual(4.5);
  });
});

describe('the surfaces are actually distinguishable', () => {
  it('the ground, the recessed surface and a card are three different values', () => {
    /*
     * THE WHOLE POINT OF THE RETHEME. These were 98%, 95% and 100% — five points of range,
     * with the "elevated" card LIGHTER than the ground it sits on by two. Nothing read as
     * layered, which is what made the interface feel flat and, in the user's word, boring.
     *
     * A ratio rather than a lightness difference, because lightness is not perceptually even:
     * five points near white is nearly invisible, five points at mid-grey is obvious.
     */
    const groundToSurface = ratio('background', 'surface');
    const groundToCard = ratio('background', 'surface-elevated');
    expect(groundToSurface).toBeGreaterThan(1.05);
    expect(groundToCard).toBeGreaterThan(1.05);
  });

  it('a card is lighter than the ground, and the recessed surface is darker', () => {
    // The direction matters as much as the amount: a "raised" card that is darker than its
    // ground reads as a hole.
    expect(luminance(hsl('surface-elevated'))).toBeGreaterThan(luminance(hsl('background')));
    expect(luminance(hsl('surface'))).toBeLessThan(luminance(hsl('background')));
  });

  it('the border is visible against both the ground and a card', () => {
    // A hairline that cannot be seen is a hairline that is not doing its job — and this theme
    // leans on borders rather than heavy shadows.
    expect(ratio('border', 'background')).toBeGreaterThan(1.2);
    expect(ratio('border', 'surface-elevated')).toBeGreaterThan(1.2);
  });
});

describe('the soft tints read as colour rather than as white', () => {
  it.each(ACCENTS)('accent-%s-soft is meaningfully off-white', (name) => {
    /*
     * The specific thing that made the product look boring: soft tints at 94-96% lightness
     * against a 98% ground are perceptually white, so six carefully chosen colours only ever
     * appeared as invisible washes.
     *
     * Checked against PURE WHITE rather than against the ground, because that is the
     * comparison the eye makes on a card — and it is the check that would have failed before
     * this retheme and passes after it.
     */
    const [, , l] = hsl(`accent-${name}-soft`);
    expect(l).toBeLessThanOrEqual(93);
  });

  it.each(ACCENTS)('accent-%s-soft still separates from the recessed surface', (name) => {
    // Deep enough to be seen, not so deep it collides with the neutral fill next to it.
    const soft = luminance(hsl(`accent-${name}-soft`));
    const surface = luminance(hsl('surface'));
    expect(Math.abs(soft - surface)).toBeGreaterThan(0.005);
  });
});

describe('the browser is told the same theme the page actually is', () => {
  /**
   * `viewport.themeColor` paints the Android address bar and the task-switcher card, and
   * `colorScheme` decides which palette the engine renders native form controls, scrollbars
   * and the canvas under the page in. Both are read at BUILD time from a plain object, so
   * neither can reference a CSS custom property — the hex has to be duplicated, and a
   * duplicated constant drifts.
   *
   * It had already drifted: both still described the dark theme the product had before the
   * retheme to warm paper. A near-black bar above a #F9F6F0 page, dark scrollbars, and a dark
   * flash before the stylesheet arrived — on the first screen anybody sees.
   *
   * A comment saying "keep these in sync" is a claim that nothing checks. This is the check.
   */
  /*
   * COMMENTS STRIPPED, and this is the third time in one sitting that a source-scanning
   * assertion has matched prose instead of code.
   *
   * The comment I wrote in layout.tsx explaining why `colorScheme: 'dark'` was wrong contains
   * the literal string `colorScheme: 'dark'`. The regex found that before it reached the real
   * declaration and reported the bug I had just fixed. An assertion that fails on correct code
   * is worse than no assertion — it trains you to "fix" things that were already right.
   *
   * So this is a helper rather than a fix at one call site: every scan of source text in this
   * repo should read code, and prose that discusses code is not code.
   */
  const stripComments = (src: string) =>
    src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');

  const LAYOUT = stripComments(
    readFileSync(join(process.cwd(), 'src/app/layout.tsx'), 'utf8'),
  );

  /** `H S% L%` → `#rrggbb`, via the same conversion the luminance helper uses. */
  function toHex([h, s, l]: [number, number, number]): string {
    const S = s / 100;
    const L = l / 100;
    const c = (1 - Math.abs(2 * L - 1)) * S;
    const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
    const m = L - c / 2;
    const [r, g, b] =
      h < 60
        ? [c, x, 0]
        : h < 120
          ? [x, c, 0]
          : h < 180
            ? [0, c, x]
            : h < 240
              ? [0, x, c]
              : h < 300
                ? [x, 0, c]
                : [c, 0, x];
    return (
      '#' +
      [r, g, b]
        .map((v) =>
          Math.round((v + m) * 255)
            .toString(16)
            .padStart(2, '0'),
        )
        .join('')
        .toUpperCase()
    );
  }

  it('converts a known colour correctly', () => {
    // Without this the two assertions below could agree on the same wrong answer.
    expect(toHex([0, 0, 100])).toBe('#FFFFFF');
    expect(toHex([0, 100, 50])).toBe('#FF0000');
  });

  it('finds a themeColor to check', () => {
    expect(LAYOUT).toMatch(/themeColor:\s*'#[0-9A-Fa-f]{6}'/);
  });

  it('themeColor is the actual --background', () => {
    const declared = LAYOUT.match(/themeColor:\s*'(#[0-9A-Fa-f]{6})'/)?.[1]?.toUpperCase();
    expect(declared).toBe(toHex(hsl('background')));
  });

  it('colorScheme matches which end of the range the ground sits at', () => {
    // A light ground with `colorScheme: 'dark'` is the specific bug this block was written
    // for: the page is light and every native control the browser draws is not.
    const declared = LAYOUT.match(/colorScheme:\s*'(\w+)'/)?.[1];
    const [, , lightness] = hsl('background');
    expect(declared).toBe(lightness > 50 ? 'light' : 'dark');
  });
});

describe('nothing sets text on a bare accent fill unless it is dark enough', () => {
  /**
   * THE GAP THIS FILE HAD, and it let a real bug through.
   *
   * Every test above checks the `-ink` tones, because `-ink` is the only tone the design
   * system permits for small text on a light ground. But there is a second, entirely legal
   * pairing — WHITE text on the SOLID accent, used for a selected chip or a filled button —
   * and nothing measured it. I shipped `bg-accent-amber text-white` on the quiz difficulty
   * chips at 3.02:1, well under the floor, and every existing assertion here passed.
   *
   * The palette is not uniform in lightness: indigo, teal and plum are dark enough to carry
   * white, and amber, coral and emerald are not. So this cannot be a blanket rule — it has to
   * be a measurement, and the code has to be checked against it.
   */
  const SOLID_TEXT = /(?:bg-accent-(\w+))(?=[^"'`]*\btext-white\b)/g;

  const WHITE: [number, number, number] = [0, 0, 100];

  function ratioTo(tone: string): number {
    const [x, y] = [luminance(hsl(tone)), luminance(WHITE)].sort((p, q) => q - p);
    return (x + 0.05) / (y + 0.05);
  }

  it('measures the tones correctly', () => {
    // Sanity: indigo is known-good for white and amber is known-bad. If both came out the
    // same the assertion below would be measuring nothing.
    expect(ratioTo('accent-indigo')).toBeGreaterThan(4.5);
    expect(ratioTo('accent-amber')).toBeLessThan(4.5);
  });

  it.each(['indigo', 'teal', 'plum'])('accent-%s is dark enough for white text', (name) => {
    expect(ratioTo(`accent-${name}`)).toBeGreaterThanOrEqual(4.5);
  });

  it('no component pairs text-white with a tone that cannot carry it', () => {
    /*
     * Scans the real source. Comments stripped first — the note in quiz/page.tsx explaining
     * this very bug contains the string `bg-accent-amber text-white`, and without stripping,
     * the file documenting the fix would be reported as committing it. That has happened
     * three separate times in this repo; see docs/MISTAKES.md P5.
     */
    const files = sourceFiles();
    expect(files.length).toBeGreaterThan(40); // the scan must actually find the app

    const offenders: string[] = [];
    for (const file of files) {
      const code = readFileSync(file, 'utf8')
        .replace(/\/\*[\s\S]*?\*\//g, '')
        .replace(/\/\/.*$/gm, '')
        .replace(/\{\/\*[\s\S]*?\*\/\}/g, '');
      for (const m of code.matchAll(SOLID_TEXT)) {
        const tone = `accent-${m[1]}`;
        // -soft and -ink are not solid fills; only the bare tone is in question here.
        if (m[1].endsWith('-soft') || m[1].endsWith('-ink') || m[1].endsWith('-hot')) continue;
        let r: number;
        try {
          r = ratioTo(tone);
        } catch {
          continue; // not a real token — a longer utility name that merely starts this way
        }
        if (r < 4.5) {
          offenders.push(`${file.replace(process.cwd() + '/', '')}: text-white on ${tone} is ${r.toFixed(2)}:1`);
        }
      }
    }
    expect(offenders, offenders.join('\n')).toEqual([]);
  });
});

/** Every .tsx under src, for the source scan above. */
function sourceFiles(): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir)) {
      const full = join(dir, entry);
      if (statSync(full).isDirectory()) walk(full);
      else if (entry.endsWith('.tsx')) out.push(full);
    }
  };
  walk(join(process.cwd(), 'src'));
  return out;
}

/* ═══ THE PUBLIC SITE'S PALETTE ══════════════════════════════════════════════
 *
 * Everything above measures `globals.css`, which is the signed-in product. The public
 * surfaces are themed by a second, scoped layer — `src/app/marketing.css`, under `.mk` — and
 * for its first weeks it was invisible to this file. That mattered more than a coverage gap
 * usually does, because that stylesheet states its own contrast ratios in prose, and when
 * they were finally measured THREE OF THEM WERE WRONG: gold-ink was documented at 5.4:1 and
 * is 4.50 on paper and 4.23 on the recessed band — below AA on live eyebrow text — and bare
 * gold was documented at 3.1:1 and is 2.56.
 *
 * That is exactly the failure this file's own docstring describes: a number in a comment is a
 * claim, and an unmeasured claim drifts. The tokens were corrected; these assertions are what
 * stop them drifting back.
 *
 * The tokens are HEX rather than the HSL triples globals.css uses, so this needs its own
 * parser. The duplication is deliberate — converting one file to the other's format to share
 * a helper would be changing production CSS to suit a test.
 */
const MK = readFileSync(join(process.cwd(), 'src/app/marketing.css'), 'utf8');

/** Pull a `--mk-name: #rrggbb;` hex out of the `.mk` block. */
function mk(name: string): [number, number, number] {
  const m = MK.match(new RegExp(`--mk-${name}:\\s*#([0-9a-fA-F]{6})`));
  if (!m) throw new Error(`token --mk-${name} not found in marketing.css`);
  const h = m[1];
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255) as [number, number, number];
}

function srgbLuminance([r, g, b]: [number, number, number]): number {
  const lin = (v: number) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

function mkRatio(a: string, b: string): number {
  const [x, y] = [srgbLuminance(mk(a)), srgbLuminance(mk(b))].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

describe('the marketing layer is measured, not asserted in a comment', () => {
  it('finds the tokens it claims to check', () => {
    // Same guard as above: a regex that stopped matching would make everything below pass by
    // throwing nothing.
    for (const t of ['paper', 'bg', 'ink', 'body', 'muted', 'gold', 'gold-ink', 'gold-graphic'])
      expect(() => mk(t)).not.toThrow();
  });

  /*
   * THE TWO LIGHT GROUNDS. `--mk-paper` is the page and `--mk-bg` is the recessed band that
   * every other section sits on, and they are different values — so any text tone has to clear
   * the bar on BOTH. Checking only the page ground is how gold-ink passed review at 4.50 while
   * failing at 4.23 on half the sections that use it.
   */
  const LIGHT_GROUNDS = ['paper', 'bg', 'surface'] as const;

  it.each(['ink', 'body', 'muted', 'gold-ink'])(
    '--mk-%s carries text on every light ground',
    (tone) => {
      for (const ground of LIGHT_GROUNDS) {
        expect(mkRatio(tone, ground), `--mk-${tone} on --mk-${ground}`).toBeGreaterThanOrEqual(
          4.5,
        );
      }
    },
  );

  it('--mk-gold-graphic clears the 3:1 bar for a mark that carries information', () => {
    // 1.4.11. The weight bars in MkProof are the case: their length is the fact and there is
    // no number-only fallback beside them.
    for (const ground of ['paper', 'bg'] as const) {
      expect(mkRatio('gold-graphic', ground)).toBeGreaterThanOrEqual(3);
    }
  });

  it('bare --mk-gold is NOT dark enough for either job, which is why the other two exist', () => {
    // A guard against somebody "simplifying" the four tones back into one. If this ever passes,
    // the split has been quietly undone and the eyebrows are failing AA again.
    expect(mkRatio('gold', 'paper')).toBeLessThan(3);
  });

  it.each(['on-dark', 'on-dark-muted', 'gold-glow'])(
    '--mk-%s carries text on the film stage',
    (tone) => {
      // The stage is a gradient between these two, so both ends have to hold.
      for (const ground of ['dark-top', 'dark-bot'] as const) {
        expect(mkRatio(tone, ground)).toBeGreaterThanOrEqual(4.5);
      }
    },
  );

  it.each([
    ['good', 'good-bg'],
    ['bad', 'bad-bg'],
  ])('--mk-%s reads on its own tinted panel', (ink, bg) => {
    expect(mkRatio(ink, bg)).toBeGreaterThanOrEqual(4.5);
    // And on a plain card, where the same two are used for the verdict chips.
    expect(mkRatio(ink, 'surface')).toBeGreaterThanOrEqual(4.5);
  });

  it('the two light grounds are actually different values', () => {
    // If they collapse, the band sections stop reading as bands and the whole page flattens —
    // the same failure globals.css records about its own 98/95/100 ladder.
    expect(Math.abs(srgbLuminance(mk('paper')) - srgbLuminance(mk('bg')))).toBeGreaterThan(0.005);
  });
});
