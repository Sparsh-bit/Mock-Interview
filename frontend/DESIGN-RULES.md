# Landing page design rules

Written because "make it look professional, not AI-generated" is only actionable
if you name what the AI look actually *is*. These are the checks the rebuild must
pass. Every one of them is something you can look at a screen and verify.

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
number on the page is counted from the code — see `STATS` in `page.tsx`.

**Product artefacts, not icons.** A feature is proven by showing the actual thing:
the transcript with pauses marked in place, the score ring, the AI-authorship
flag. An icon next to a paragraph is a claim; the artefact is evidence.

**Six colours, each bound to one meaning.** This rule used to read "one accent,
used sparingly", and taken literally it produced a page that was effectively
greyscale — which does not read as restraint, it reads as unfinished. The
discipline is not *less* colour, it is that colour is never decorative:

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

## Must be represented

The page currently advertises the product as it was several versions ago. The
rebuild has to cover what actually shipped:

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
- No stock photography. Imagery is authored SVG/CSS or live product UI. The only
  real photograph on the site is the founder portrait already in `/public/img`.
- Every animation honours `prefers-reduced-motion`.
- Smooth on a mid-range Android phone.
- No claim the code cannot support.
