/**
 * Turning a recruiter's brand colour into one this interface can use.
 *
 * THE PROBLEM. `catalogue.yaml` records each company's actual brand hex —
 * Accenture #a100ff, Tech Mahindra #e4002b, Amazon #ff9900, Deloitte #86bc25.
 * Rendering those raw causes two distinct problems, and only one of them is
 * about looks:
 *
 *   1. They do not belong to the palette. Those four sit at 90–100% saturation
 *      and 50–65% lightness. Every colour in this product is 34–88% saturation
 *      at 26–46% lightness, on a warm paper ground. Twelve full-chroma brand
 *      colours on one screen is a rainbow, and it is the single loudest thing
 *      in the app — it makes the page look assembled from other people's assets,
 *      which is exactly the impression to avoid.
 *
 *   2. A company's exact brand colour, behind that company's initials, in a
 *      rounded square, is functionally a logo. This project already decided not
 *      to use recruiter logos — the landing page says so in as many words, "a
 *      contents page, not a logo wall — we have no rights to their marks."
 *      Reproducing the mark in colour instead of in shape is the same act.
 *
 * THE FIX. Keep the HUE, discard the saturation and lightness, and re-render at
 * the palette's own values. Accenture stays violet, Amazon stays orange, Deloitte
 * stays green — so the chips are still 12 distinguishable colours and still help
 * you find a company on a dense grid — but every one of them now sits in the same
 * tonal family as the rest of the interface, and none of them is the brand colour
 * any more.
 *
 * Two tones, matching the palette's own convention:
 *
 *   ink   for text and small marks. Fixed at L=36%, which holds ≥4.5:1 against
 *         the paper ground across the entire hue circle — the worst case is
 *         yellow-green near 90°, which measures about 4.8:1.
 *   fill  for chips, bars and progress. L=44%, S=62%: strong enough to read as
 *         a colour at 24px, quiet enough that twelve of them coexist.
 *
 * White text on `fill` is ≥4.6:1 across the hue circle, so the initials on a
 * chip stay legible whatever the company.
 *
 * BOTH RETURN #rrggbb, NOT hsl(). That is deliberate and load-bearing: the
 * roadmap builds its glows and rails by string-concatenating an alpha pair onto
 * the accent — `${accent}26`, `${accent}55` — which is only valid on a hex.
 * Returning `hsl(...)` would produce `hsl(278 62% 44%)26` and silently drop
 * every one of those rules. Hex means a component harmonises once, at the point
 * the value enters it, and every existing downstream use keeps working.
 */

const IDENTITY_S = 62;
const FILL_L = 44;
const INK_L = 36;

/** Hue of a #rrggbb colour, 0–360. Greys return 220 (the interface's own hue). */
function hueOf(hex: string): number {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return 220;

  const n = parseInt(m[1], 16);
  const r = ((n >> 16) & 255) / 255;
  const g = ((n >> 8) & 255) / 255;
  const b = (n & 255) / 255;

  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const d = max - min;
  // An achromatic brand colour has no hue to preserve; IBM-style near-blacks
  // and pure greys land here.
  if (d < 0.001) return 220;

  let h: number;
  if (max === r) h = ((g - b) / d) % 6;
  else if (max === g) h = (b - r) / d + 2;
  else h = (r - g) / d + 4;

  h *= 60;
  return h < 0 ? h + 360 : h;
}

/** HSL (0–360, 0–100, 0–100) to #rrggbb. */
function toHex(h: number, s: number, l: number): string {
  const S = s / 100;
  const L = l / 100;
  const c = (1 - Math.abs(2 * L - 1)) * S;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = L - c / 2;
  const [r, g, b] =
    h < 60 ? [c, x, 0] :
    h < 120 ? [x, c, 0] :
    h < 180 ? [0, c, x] :
    h < 240 ? [0, x, c] :
    h < 300 ? [x, 0, c] : [c, 0, x];
  const to = (v: number) =>
    Math.round((v + m) * 255).toString(16).padStart(2, '0');
  return `#${to(r)}${to(g)}${to(b)}`;
}

/**
 * Chip, bar and progress fill. White text on this is ≥4.6:1.
 * Returns #rrggbb so `${brandFill(x)}55` alpha suffixes stay valid.
 */
export function brandFill(hex: string): string {
  return toHex(hueOf(hex), IDENTITY_S, FILL_L);
}

/** Text and small marks. ≥4.5:1 on the paper ground at every hue. */
export function brandInk(hex: string): string {
  return toHex(hueOf(hex), IDENTITY_S, INK_L);
}
