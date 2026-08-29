# Hotseat — the design language

`DESIGN-RULES.md` says what *not* to do and holds for every surface. This says what
*this product is*, now that it has a name that means something. Read both.

- Related: [[REDESIGN]] · [[MISTAKES]] · [[VOICES]] · [[index]]

---

## The idea, in one line

**Hotseat does not name the preparation. It names the chair.**

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

## 5. Type

The mark's defining feature is the **long straight stroke** — the chair's back
post running unbroken to the floor. Its typographic equivalent is the **rule**:
the 14px coloured dash before every page eyebrow, the hairline under a section,
the ladder bar. Thin, straight, definite.

Numbers are the other half. Every score, rating, count, price and duration is
monospace with `tabular-nums` — these are figures a candidate compares against
their own from last week, and proportional digits make two numbers of the same
length different widths.

## 6. What each colour owns

Unchanged from DESIGN-RULES. Half the value is that it never moves:

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
2. **Exactly one lit element.** See §1. This is the one most pages were missing.
3. **A real empty state** — what to do, in this product's voice, with a route out.
4. **A real error state** that does not read as zero. `0/100` and "we could not
   load this" are opposite messages, and confusing them has already cost an
   incident.
5. **Numbers in mono, verdicts in colour, everything else quiet.**
