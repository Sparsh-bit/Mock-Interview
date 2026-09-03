# InterviewOS — the design language

`DESIGN-RULES.md` says what *not* to do. This says what *this product is*, now that
it has a name that means something. Read both.

**Scope.** Everything below describes the SIGNED-IN product. The public site — the
landing page, `/welcome`, anything wrapped in `MarketingShell` — is a second,
scoped system under `.mk` in `src/app/marketing.css`, and it departs from two of
the rules here on purpose:

- **§1, one lit element.** It has none. On the landing page the film *is* the
  subject and it occupies a quarter of the page; on `/welcome` the subject is a
  sequence, and lighting one step of four would be lighting the wrong thing.
- **§6, six colours.** It uses one gold and two verdicts, for the reason §6 gives
  rather than against it: colour carries information, and a page with no round to
  be in and no verdict to report has none to carry.

What the two systems *do* share, and this is the part that matters: the same
ground, the same espresso ink, the same warm border family, the same mono
numerals, the same 14px rule before an eyebrow. A visitor crossing from the
landing page into the dashboard should not be able to name what changed.

- Related: [[REDESIGN]] · [[DESIGN-RULES]] · [[MISTAKES]] · [[VOICES]] · [[index]]

---

## The idea, in one line

**InterviewOS does not name the preparation. It names the chair.**

Two strangers, one room, and every gap in what you know about to be found in the
next twenty minutes. The product exists because of that specific feeling. It does
not soothe it — it lets you sit in it on a Tuesday, for ₹49, when nothing is
riding on it.

Everything below follows from taking that literally.

---

## 1. One thing is lit. Everything else is dim.

A hotseat is *lit*. There is a light on the person in it and the rest of the room
falls away. That is not a mood — **it is the hierarchy rule**, and it is the fix
for the complaint that started this work: every page was a stack of identical
white cards, so nothing on any page was more important than anything else.

So, on every page:

- **Exactly one element is "in the light."** It gets `.lit` — elevated ground, a
  warm gradient falling from its top edge, a real shadow. One per page. Two is
  none.
- **Everything else is on paper.** Flat, hairline-bordered, quiet.
- The lit element is the thing the page is *for* — the rating on the dashboard,
  the start control on the interview page, the score on a report. Not the first
  card. Not a banner.

If you cannot name what should be lit, the page has no point yet and no amount of
colour will give it one.

**`.lit` is defined once in `globals.css`.** Never hand-roll it, and never put it
on two things in one view.

## 2. Heat is intensity, and only intensity

The name gives us a temperature scale, and a scale is only worth having if it
means exactly one thing. Heat means **how hard this is**, nowhere else:

| | |
|---|---|
| cool (teal) | easy · warm-up · low stakes |
| warm (amber) | medium · the real thing |
| hot (coral) | hard · pressure · the round that decides it |

Quiz difficulty, question difficulty, round intensity. **Heat is never used for
"good" or "bad"** — that is what emerald and coral already do on the score bands,
and a colour that means two things means nothing. If a use of warmth is not
answering *how hard is this*, it is decoration.

## 3. The room is warm, and now there is a reason

The ground was already warm paper at 38°, which every generated template gets
wrong by shipping cool near-white. Under this name it stops being a taste and
becomes a fact about the room: it is lit, and lit rooms are warm.

Real mockingbird-grey restraint still applies — **the room is quiet and the light
is where the meaning is**:

- Colour arrives at the moment it carries information — a verdict, a rank, a
  destination, a difficulty, a warning.
- Never as a wash. Never as a mood. Never as "this section needed something."
- **More colour therefore means more places where colour is load-bearing**, not
  more tinted panels.

A page that is 90% paper with decisive colour reads as designed. A page that is
40% tinted panels reads as a template — and it is the *same amount of colour*.

**The test, unchanged from DESIGN-RULES:** if this were greyscale, would
information be lost? If no, it is decoration — take it out.

## 4. The vocabulary

The cheapest way to stop a product sounding machine-written is to stop it using
machine words. Copy only — no logic, no routes:

| Instead of | Say | Because |
|---|---|---|
| "No sessions yet" | **You haven't taken the seat yet** | Names what a session *is*. |
| "Loading interviewers…" | **The panel is taking their seats** | They are people with names ([[VOICES]]), not a resource being fetched. |
| "Session history" | **Rounds you've sat** | |
| "Difficulty: hard" | **Hard** — and it runs hot | The scale is already visible; the word confirms it. |
| "Start interview" | **Start interview** | Unchanged. |
| "Analytics" | **Analytics** | Unchanged. |

**Two hard limits.** Never rename a primary action; never rename a navigation
label. Cleverness in a button is a person not finding the button. The voice lives
in the writing *around* the controls.

And never let it get lurid. No flames, no "feel the heat", no sweat. The chair is
calm and well lit — that is what makes it unnerving. One overcooked line and the
product is a toy.

## 4a. The mark

The logo is a chair seen head-on, arms flaring open, with a flame in the bowl.
It says the whole proposition in one shape: the seat, and the heat of being in it.

**There are two of it, and which one is correct depends on size.**

`frontend/public/brand/mark.png` and `lockup.png` are the artwork — three flame
tongues, four-stop gradients, a pale light cone, three tapered legs. Rendered on a
size ladder from 16 to 128px it holds together from about **48px** and turns to
mud below that: the legs become single scratchy pixels and the tongues merge.

`<Brandmark>` in `components/brand/Brandmark.tsx` is an SVG of the same
silhouette with the detail that cannot survive **removed rather than shrunk** —
one flame, no cone, arms and legs thickened. It is not a second logo; it is the
same logo drawn for the size it is used at.

| where | what | why |
|---|---|---|
| navigation rail, drawer, header | `<Wordmark>` (SVG, 22px) | the artwork is illegible here |
| auth screens, 404, pricing header | `<Lockup>` (artwork, ≥180px) | there is room, and the descriptor is legible from 180px up |
| loading | `<BrandLoader>` (SVG) | must animate with no JavaScript |
| public nav, public footer, `/welcome` | `<Brandmark>` (28px) + live text | see below |
| browser tab | `src/app/icon.png`, `apple-icon.png` | see below |

**The public lockup is set, not drawn**, and it is the one place the mark is
paired with type rather than shipped as artwork: the 28px `<Brandmark>` beside
`Interview` in Fraunces with `OS` in `--mk-gold`. It is set because it has to sit
in a 40px-tall floating pill that inverts over the film's dark stage — artwork at
that size is illegible and cannot recolour. That gold `OS` is a **logotype**,
which is why it is allowed to be 2.6:1 when nothing else in the system may be:
WCAG 1.4.3 exempts brand names, and gold cannot clear the text bar without going
brown. It is also the reason gold is the first thing you meet above the fold — it
teaches the colour before the colour is asked to mean "press this".

**Colours are sampled from the artwork**, not chosen beside it — navy `#28344A`,
flame `#E85A1E → #FBA627`, cone `#FDECD0`, exported as `BRAND_COLORS`. The two
versions cannot drift into two brands.

**The mark never sits on a coloured tile.** Its negative space is open — the page
shows through inside the chair and behind the flame — because it was drawn for a
light ground. A filled tile behind it fills those gaps and destroys the
silhouette. The favicons are the one exception and carry their own paper ground,
because a browser tab may be dark and would otherwise show through the flame.

**Loading is the logo burning.** The chair holds perfectly still; the flame rises,
brightens and settles on uneven timing so it never lands on a beat. Nothing spins.
It is pure CSS on transform and opacity, because it renders during route
transitions when the page's JavaScript has not arrived — a loader that needs a
hydrated tree sits frozen for exactly as long as it is needed. Reduced motion
stops the burn and leaves the mark at full brightness rather than removing it.

## 5. Type

The mark's defining feature is the **long straight stroke** — the chair's back
post running unbroken to the floor. Its typographic equivalent is the **rule**:
the 14px coloured dash before every page eyebrow, the hairline under a section,
the ladder bar. Thin, straight, definite.

**Four faces, and each has one job.** Inter is the interface and DM Sans is the
public site's body — they are never mixed on one surface. JetBrains Mono is every
score, count, price and duration, with `tabular-nums`, so a number that ticks
over does not reflow the line it sits on.

**Fraunces is the display face and it is the only thing that crosses the
boundary.** It sets the hero, every section heading on the public site, and — via
`font-display` in `tailwind.config.ts` and `components/ui/page-header.tsx` — the
page title on all fourteen signed-in screens. That single shared face is most of
why the two systems read as one product. It is a variable serif with an optical
size axis, so one file holds its proportions from a 24px page title to a 100px
hero, and it is self-hosted from `public/fonts/` rather than fetched at build
time.

**The italic is load-bearing.** Exactly one clause per display heading is set in
Fraunces italic and gold, and that clause is always the *turn* in the sentence —
the point where the line stops describing and starts arguing. "Practise the real
thing, *before the real thing.*" If a heading has no turn in it, it gets no
italic. This is the site's one recurring typographic move; using it twice in a
heading spends it.

Numbers are the other half. Every score, rating, count, price and duration is
monospace with `tabular-nums` — these are figures a candidate compares against
their own from last week, and proportional digits make two numbers of the same
length different widths.

## 6. What each colour owns

Unchanged from DESIGN-RULES. Half the value is that it never moves:

> Two things moved elsewhere and are worth naming here so the table stays
> trustworthy. **`--primary` is no longer indigo, it is espresso** — it used to be
> the same value as `--accent-indigo`, so "the primary action" and "an interview
> surface" were literally one colour and neither could be read as distinct. A
> filled button is now espresso everywhere in the product, matching
> `.mk-btn-primary` on the public site, `--ring` is gold, and indigo goes back to
> meaning only what this table says. **The rail's group labels are warm gold**
> (`Sidebar.tsx`) — that is a label on the furniture rather than on a
> destination, which is why it does not spend the amber meaning; it was
> previously grey at about 3:1 and read as disabled rather than as a heading.

| colour | means |
| --- | --- |
| indigo | the product, primary actions, links |
| amber | preparation, in progress, effort, money, *medium heat* |
| emerald | verified, correct, passed, complete |
| coral | flagged, bluffing, wrong, needs work, *high heat* |
| teal | data, analytics, measurement, *low heat* |
| plum | HR and behavioural rounds |

Bound in code at `frontend/src/lib/tones.ts`; rail-versus-header agreement pinned
by `tones.test.ts`. Score bands are `lib/score-bands.ts`, pinned against the
backend's own thresholds by `score-bands.test.ts` — the colour of a score and the
word printed beside it must never disagree.

## 7. What every page owes

Checked page by page in [[REDESIGN]]:

1. **An eyebrow in its own tone**, so the top-left says where you are.
2. **At most one lit element**, and one wherever the page has a subject. See §1.
   This is the thing most pages were missing.

   **Some pages genuinely have no subject, and must not fake one.** Settings is a
   list of independent controls; the admin tables and the AI-usage breakdown are
   dense operator surfaces where every row is a peer. Lighting one of those would
   claim an importance nothing supports, which is the same dishonesty as an
   invented statistic. Those pages get their hierarchy from typography, grouping
   and spacing instead — and `lit-hierarchy.test.ts` enforces the ceiling of one,
   never a floor of one, precisely so this stays a legitimate answer.

   **The live session is the deliberate exception, and it is worth naming.** It is
   a multi-pane workspace rather than a document: the panes are peers by design,
   and the current question — which *is* the subject — is a strip pinned outside
   the scroll container, whose layout is constrained by invariants that
   `mic-interlock.test.ts` pins. It already reads as the subject through indigo.
   Putting a warm top-down gradient and the system's largest shadow on a flush
   strip would fight the colour that is already doing that job and would risk a
   layout the tests exist to protect. Its hierarchy was solved before this rule
   existed, and it was solved correctly.

   The full list of pages with no lit element, all deliberate: `settings`,
   `admin`, `admin/analytics`, `admin/marketing`, `admin/offers`, `ai-usage`,
   `prepare` (its timeline carries the structure), `report/[id]/analysis`,
   `r/[reportId]`, `session/[id]`, the receipt, the four auth screens, and the
   two public surfaces — `/` and `/welcome` — for the reasons in the scope note
   at the top of this file. That list has to stay complete: a page missing from
   it is an undeclared exception, and `lit-hierarchy.test.ts` enforces a ceiling
   of one rather than a floor, so nothing will fail to tell you.
3. **A real empty state** — what to do, in this product's voice, with a route out.
4. **A real error state** that does not read as zero. `0/100` and "we could not
   load this" are opposite messages, and confusing them has already cost an
   incident.
5. **Numbers in mono, verdicts in colour, everything else quiet.**
