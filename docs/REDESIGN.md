# Redesign tracker

> Product is now **Hotseat**. See [[DESIGN-LANGUAGE]] for what that means visually.

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
| `layout/Header.tsx` | ✅ | ✅ | Wordmark below lg, live balance chip replaces the Plans button |
| `globals.css` tokens | ✅ | ✅ 35 contrast tests | Deepened ground, 6 accent families |

## Pages

| Page | Lines | Redesigned | Still works | The one thing it must keep doing |
|---|---|---|---|---|
| `dashboard` | 361 | ✅ | ✅ | Standing banner is lit; scores banded; the 🔥 emoji is gone |
| `interview` (setup) | 966 | ✅ | ✅ | PageHeader added; 3 exclusive views each lit; credit logic untouched |
| `gd` | 1071 | ✅ | ✅ | Plum throughout; score bars banded not gradient; slide-to-confirm intact |
| `admin` | 639 | ✅ | ✅ | Off-palette colours fixed in admin/analytics; no subject by design |
| `prepare` | 564 | ✅ | ✅ | Amber eyebrow rules; timeline kept |
| `quiz` | 550 | ✅ | ✅ | Heat scale on difficulty; setup panel lit; still never charged |
| `communication` | 484 | ✅ | ✅ | Stage + scorecard both lit (exclusive); stale-data error hole closed |
| `achievements` | 415 | ✅ | ✅ | Rating card lit; rank colour = height on the ladder |
| `ai-usage` | 393 | ✅ | ✅ | Already on-palette; no subject by design |
| `report` | 330 | ✅ | ✅ | Scores banded + mono; "Not scored yet" no longer looks like a zero |
| `profile` | 227 | ✅ | ✅ | Form is lit; target-company chip is amber |
| `settings` | 155 | ✅ | ✅ | Section tiles carry meaning; export/delete untouched |
| `tracks` | 100 | ✅ | ✅ | Lead track lit + full width; heat scale; "Active" badge gone |
| `analytics` | 91 | ✅ | ✅ | Average is lit; unbuilt-feature promise removed; retry added |

## Cross-cutting

| Item | Done | Notes |
|---|---|---|
| New product name chosen | ✅ | **Hotseat** — one source at `lib/brand.ts` |
| Pricing visible where it decides something | ✅ | Header balance chip; bundle lit on /pricing; paywall reframed |
| Lightswind components reach signed-in pages | ✅ | All 7 in use; `focus-cards` now also on tracks |
| Icons chosen per feature, not per whim | ✅ | Rail + drawer coloured from `ROUTE_TONE`; glyphs replaced with icons |
| `npm test` green | ✅ | **787** passing (was 720) |
| `tsc --noEmit` + `next lint` clean | ✅ | Re-check after every page |

## Verification, per page

Not "it compiled". For each page, in the browser: the primary action completes, the
empty state renders, and the error state renders. Recorded here as it happens.
