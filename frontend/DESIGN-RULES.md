# Design rules

Written because "make it look professional, not AI-generated" is only actionable
if you name what the AI look actually *is*. Every rule here is something you can
look at a screen and verify.

## Scope — there are two systems, and this file covers both

This was written for one rebuild of one landing page, and it still says "the
page" in places where it now means "any surface". Since then the public site was
rebuilt again into a second, scoped system, so read every rule below with this
in mind:

| | the product | the public site |
| --- | --- | --- |
| where | `:root` in `src/app/globals.css` | `.mk` in `src/app/marketing.css` |
| tokens | `--background`, `--accent-*`… | all `--mk-` prefixed, **never** on `:root` |
| colour | six families, each bound to one meaning | one gold + two verdicts |
| type | Inter, JetBrains Mono | Fraunces (display) + DM Sans, self-hosted |
| applied by | the root layout | wrapping a page in `MarketingShell` |

**The `--mk-` prefix is not decoration.** It means "this token does not exist in
the product", so a component that reaches for one has said, in its own class
list, which system it belongs to. Removing the `.mk` wrapper returns a page to
the product theme with no other edit; that reversibility is the whole reason the
layer is scoped rather than global.

**`:where()` is load-bearing in `marketing.css` and absent from `globals.css`.**
Every element-targeting rule in the marketing layer wraps its scope in
`:where()`, which contributes zero specificity. `.mk p { color }` is (0,1,1) and
beats every Tailwind colour utility at (0,1,0) — which silently painted every
eyebrow and beat label in body brown until it was caught. The rule of thumb, and
it is in the stylesheet too: **if the selector names an ELEMENT, scope it with
`:where()`; if it names a class the markup opts into, do not.**

**There are two footers.** `layout/SiteFooter` is the product's and exports
`LEGAL_LINKS`; `marketing/MkFooter` is the public site's and imports it. Never
type a second copy of the legal routes — `legal-pages.test.ts` checks the list
against SiteFooter, so a hand-typed copy is four legal links nothing verifies.

**Inertial scrolling is public-only.** `MarketingShell` turns it on; the
dashboard does not get it, because a scroll there is somebody looking for a row
in a table and easing is latency between them and it.

## The tells — banned outright

These are what make a page read as machine-made. Not one of them appears on the
rebuilt page.

| Tell | Why it reads as AI |
|---|---|
| Floating gradient blobs / purple-blue orbs | The default output of every AI site builder since 2023. Instantly recognisable. |
| Symmetric 3-across icon → title → 2-line description grids | Nobody designing by hand lands on perfect symmetry three times in a row. It is what you get when a model fills a template. |
| Glassmorphic cards everywhere | One glass surface is a choice; six is a preset. |
| Emoji in headings | ✨🚀 |
| "Supercharge / Unlock / Elevate / Transform your X with AI" | Verb-noun-AI. Says nothing, appears everywhere. |
| Everything centred, everything rounded-2xl | Uniform radius and centre alignment across a whole page means no decisions were made. |
| Vague superlatives — "seamless", "powerful", "cutting-edge", "world-class" | Unfalsifiable. A human writes a number instead. |
| Rounded-up stats — "50+", "1000+", "10x" | We had two of these and both were false. |
| Three testimonials from invented people | We have no users yet. Inventing them is fraud, not design. |

## What we do instead

**Asymmetry, deliberately.** No section repeats the previous section's grid. If
one is a 7/5 split, the next is full-bleed, the next is 4/8 the other way. A page
designed by a person has an uneven rhythm because each section was solved on its
own terms.

**Specific nouns and real numbers.** Not "comprehensive company coverage" but
"Cognizant GenC Next, TCS Digital, Infosys Power Programmer". Not "detailed
feedback" but "12 pauses, 29 seconds of silence, 125 words per minute". Every
number on the page is counted from the code — see
`src/components/marketing/content.ts`, which declares itself the only place the
public site states a fact. (This used to point at `STATS` in `page.tsx`, a symbol
that no longer exists — a dead pointer in a rules file is how the rule stops
being followed.)

**Product artefacts, not icons.** A feature is proven by showing the actual thing:
the transcript with pauses marked in place, the score ring, the AI-authorship
flag. An icon next to a paragraph is a claim; the artefact is evidence.

**Six colours, each bound to one meaning — in the PRODUCT.** This rule used to
read "one accent, used sparingly", and taken literally it produced a page that
was effectively greyscale — which does not read as restraint, it reads as
unfinished. The discipline is not *less* colour, it is that colour is never
decorative:

> **The public site deliberately does the opposite, and the reason is the same
> rule.** Six information colours on a page whose job is to make somebody want an
> account is six colours carrying no information — there is no round to be in, no
> difficulty to signal, no verdict to report. So `marketing.css` ships ONE accent
> (gold, in four measured tones) plus two verdict colours held back for the film,
> where a verdict is actually being rendered. Same principle, opposite
> conclusion, because the surface has a different job. Do not "fix" one to match
> the other.
>
> Gold's four tones exist for the same reason the `-ink` split below does, and
> the numbers are measured rather than asserted: `--mk-gold` is 2.6:1 and is for
> brand and decorative fills only; `--mk-gold-graphic` clears 3:1 for a mark that
> IS the information; `--mk-gold-ink` clears 4.5:1 and is the only tone that may
> carry small text; `--mk-gold-glow` is the dark-stage tone. The first version of
> that comment claimed 3.1:1 and 5.4:1 and both were wrong — see the note under
> Non-negotiables.

| colour | means | where it comes from |
| --- | --- | --- |
| indigo | the product, primary actions, links | the navy shirt in the hero photo |
| amber | preparation, in progress, hours, effort | the oak desk and window light |
| emerald | verified, correct, passed, complete | the plants |
| coral | flagged, bluffing, wrong, needs work | the ring drawn round a score |
| teal | data, analytics, measurement | the chart in the report photo |
| plum | HR and behavioural rounds | — |

The palette is *sampled from the product's own photography*. That is what stops
the images looking pasted onto the interface, and it is why the ground is warm
paper (38°) rather than the cool near-white every generated template ships with.

Three tones each. `-ink` is the only one safe for text under ~18px — all are
≥4.5:1 on the paper ground. The bare tone is for fills, strokes and graphics.
`-soft` is the tinted background. `text-accent-amber` on body copy is a bug, not
a style choice: it measures 2.9:1.

The test for any new use of colour: *if this were greyscale, would information
be lost?* If no, it is decoration — take it out. Two adjacent shades of the same
hue in a gradient always fail this test.

**Never reproduce a third party's brand colour.** Recruiter brand hexes get run
through `lib/brand-accent.ts`, which keeps the hue and re-renders it at the
palette's saturation and lightness. Twelve full-chroma brand colours on a screen
is a rainbow, and a company's exact colour behind its own initials is a logo by
another route — which contradicts the position already taken on not using their
marks.

**Typographic hierarchy that actually steps.** Real jumps between levels, tight
tracking on display sizes, and a monospace register for anything numeric or
technical. Not four sizes of the same grey.

**Copy with a point of view.** "You won't fail because you didn't know the answer.
You'll fail because of how you said it." — a sentence someone believes, not a
feature summary.

## Must be represented — satisfied

This was a backlog: "the page currently advertises the product as it was several
versions ago". The rebuilt landing page covers all eight, and the list stays as
the checklist any future rewrite has to clear again:

- Target-company roadmap — pick from 12 recruiters, get a plan weighted by what
  that company really tests
- 48 subtopics, each with a verified video and reference
- Progress tracking, drawn as a road that only moves when you study
- Detailed analysis — your exact words, pauses marked, and the answer you should
  have given
- Standalone coding practice, with a review that flags AI-written work
- Resume upload — questions come from your own projects
- 12 companies, 24 interview tracks
- Group discussion, communication round, quizzes, the scored report

## Non-negotiables

- No 3D runtime. No WebGL. No Spline.
- No stock photography. Imagery is authored SVG/CSS or live product UI. The
  landing page now carries **no photograph at all** — its ground is an animated
  hairline fan drawn to canvas (`LineArt.tsx`) and its product shots are live
  components, not screenshots, so they cannot go stale or ship as pixels.
- **Shipped binary assets are an asset class this file did not anticipate**, and
  they need a reason each: `public/fonts/*.woff2` (three faces, ~118KB, so the
  build never needs the network to end up with the right type) and
  `public/video/landing-{1080,720}.mp4` + a poster (~4MB, the Remotion reel,
  fetched only when the observer decides it is about to be watched). Anything
  else added here should be able to justify itself the same way.
- **A contrast ratio written in a comment is a claim.** Add the assertion to
  `src/app/theme-contrast.test.ts` in the same commit. When that file was finally
  pointed at `marketing.css`, three of its stated ratios were wrong and one of
  them — the eyebrow gold on banded sections — was live text below AA.
- Every animation honours `prefers-reduced-motion`.
- Smooth on a mid-range Android phone.
- No claim the code cannot support.
