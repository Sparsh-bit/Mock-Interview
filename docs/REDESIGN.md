# Redesign tracker

Every signed-in surface, what it needs, and whether it is done. The landing page is
deliberately **out of scope** — it stays as it is.

Two columns matter and they are different questions:

- **Redesigned** — does it look like someone chose it?
- **Still works** — does every button, form and mutation on it still do what it did?

A page is only done when both are ticked. The second column exists because a retheme that
breaks a payment button is worse than a boring page that takes money.

- Related: [[DESIGN-RULES]] · [[MISTAKES]] · [[KNOWN-GOOD]] · [[index]]

---

## Shared surfaces

These appear on every page, so they are worth the most and are done first.

| Surface | Redesigned | Still works | Notes |
|---|---|---|---|
| `layout/Sidebar.tsx` | ✅ | ✅ 720 tests | Per-feature colour; tinted travelling pill |
| `layout/Header.tsx` | ☐ | | Branding, the new name, plan chip |
| `globals.css` tokens | ✅ | ✅ 35 contrast tests | Deepened ground, 6 accent families |

## Pages

| Page | Lines | Redesigned | Still works | The one thing it must keep doing |
|---|---|---|---|---|
| `dashboard` | 361 | ☐ | | Nudges, resume CTA, stats load |
| `interview` (setup) | 966 | ☐ | | Starting an interview charges once |
| `gd` | 1071 | ☐ | | Slide-to-confirm ends the round |
| `admin` | 639 | ☐ | | Admin-only routes stay admin-only |
| `prepare` | 564 | ☐ | | Timeline roadmap renders |
| `quiz` | 550 | ☐ | | Quizzes are never charged |
| `communication` | 484 | ☐ | | Charges 1 credit, not 0 or 2 |
| `achievements` | 415 | ☐ | | |
| `ai-usage` | 393 | ☐ | | Real numbers, not placeholders |
| `report` | 330 | ☐ | | Scores print; stars submit once |
| `profile` | 227 | ☐ | | Floating labels save the right values |
| `settings` | 155 | ☐ | | Export and delete still guarded |
| `tracks` | 100 | ☐ | | |
| `analytics` | 91 | ☐ | | |

## Cross-cutting

| Item | Done | Notes |
|---|---|---|
| New product name chosen | ☐ | Candidates below |
| Pricing visible where it decides something | ☐ | Not a wall of tiers on every page |
| Lightswind components reach signed-in pages | ☐ | Today: only `focus-cards`, `timeline-layout`, `slide-to-confirm`, `floating-label-input` |
| Icons chosen per feature, not per whim | ☐ | |
| `npm test` green (baseline 720) | ✅ | Re-check after every page |
| `tsc --noEmit` + `next lint` clean | ✅ | Re-check after every page |

## Verification, per page

Not "it compiled". For each page, in the browser: the primary action completes, the
empty state renders, and the error state renders. Recorded here as it happens.
