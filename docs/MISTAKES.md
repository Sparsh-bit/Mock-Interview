# Mistakes ledger

Read this before editing. Add to it after.

A record of what I actually got wrong on this codebase, why each one cost time, and the
pattern underneath it. Not a style guide and not a list of best practices — a list of things
that *happened here*, so the same shapes get caught earlier next time.

**How to use it.** Before an edit, read [The patterns](#the-patterns) — they are the compressed
form and they are what generalises. After an edit, ask whether the change matches a known
pattern; if it does, that is a warning, not a coincidence. When something new goes wrong, add
it with its own entry and check whether it is really a new pattern or an old one wearing a
different hat.

**Reading it is not applying it.** Twice now a mistake has been committed in the very file
written to prevent that class of mistake — see [M14](#m14--i-re-committed-two-documented-mistakes-inside-the-test-written-to-prevent-drift)
and [M19](#m19--two-guards-that-fired-on-correct-code-in-the-test-written-to-catch-m18). Before
writing any assertion that scans source, ask the two questions this file keeps having to
re-learn: *can this match something outside the thing I mean?* and *would this fail on code
that is already correct?*

**Before saying anything is done, run the checklist at the bottom.** Most of the entries below
were found by one of those steps and would not have been found by the others.

- Related: [[KNOWN-GOOD]] · [[COMPLIANCE]] · [[index]]

---

## The patterns

The individual mistakes are below. These are what they have in common, ordered by how much
time they have cost.

### P1 — A guard that cannot fail is worse than no guard

**By far the most expensive pattern here.** Six separate times, a test passed while the thing
it named was broken. It is worse than no test because it *reports* coverage: nobody looks
again.

Every form it took:

| Form | Instance |
|---|---|
| Counting occurrences with slack | Asserted `session_id=` appeared N times; passed with one grant stripped |
| Matching anywhere in the file | `savedRupees > 0` matched a different line entirely |
| A window reaching a neighbour | Walked back 14 lines and found *another element's* `title=` |
| Testing the helper, not the call site | `safeRedirect` had 22 tests; reverting the call site left them all green |
| Iterating the wrong collection | `app.routes` returns 5 routes for an app serving 90 |
| Asserting an unreachable state | Expected two free interviews when the allowance was one |

**The countermeasure is not "write better tests". It is: break the thing on purpose and watch
the test fail.** Every guard in this repo that matters has been mutation-tested, and the ones
above were only found that way. If a mutation does not fail the test, either the test is
vacuous or the mutation is equivalent — and knowing which is the whole value.

**The largest instance of this pattern was CI itself.** It ran lint and typecheck and nothing
else — so 807 frontend and 1,890 backend tests, many of which exist *because* a bug reached
production once already, could not fail a build. A green tick meant "it compiles". Fixed:
`.github/workflows/ci.yml` now runs both suites (with Postgres and Redis service containers,
because most of the backend suite exercises real SQL that a mock cannot reproduce) and a
production build, which catches the one failure typecheck structurally cannot — a Tailwind
class assembled at runtime that vanishes from the emitted stylesheet.

### P2 — Fixing the mechanism does not fix the people already broken by it

Twice, a correct fix shipped and rescued nobody.

The retry cooldown was added so stuck reports could recover — but it aged rows by a timestamp
that legacy rows did not have, so every already-broken report stayed broken. The fix was
correct and its population was empty.

**Ask: who is already in the bad state, and does this reach them?** If the fix depends on data
written by the fix, it does not. That is what `_GENERATION_STRATEGY` exists for — a stamp that
lets already-failed rows be identified and retried exactly once.

### P3 — I re-introduce traps this codebase has already documented

`wait_for(gather(...))` discards work that already succeeded. This repo had *already* learned
that in the quiz path, and I wrote it again in report generation — then spent a long time
diagnosing "still timing out" when the split was working and my own wrapper was throwing the
results away.

**Before writing concurrency, transaction or retry code, read what the neighbouring module
already says about it.** The comments here are unusually dense precisely because they record
incidents. They are not decoration.

### P4 — Assuming my own tooling ran

I reported a set of mutation tests as passing. They had never executed — the shell was not
expanding the variable holding the command, so every run printed nothing and I read "no
failures" as "no output". I did the same thing a second time in the same session.

**Empty output is not a pass.** If a verification step produces nothing, that is the finding.
Check the exit code or make the command print something unconditionally.

### P5 — My assertions are often stricter than the property

Banned `..` anywhere in a filename — but `resume..v2.pdf` is legitimate and `_2f.._2fevil.pdf`
cannot climb. Banned `mutateAsync` file-wide — but a different component legitimately used it.

Both failed for the *wrong reason*, which wastes a debugging cycle and, worse, trains me to
"fix" working code.

**State the property, then assert the property.** For paths that is `normpath(p).startswith(
prefix)`, not a substring ban. If an assertion fails, first ask whether the assertion is wrong.

**The recurring sub-form: a source-scanning regex matching PROSE rather than CODE.** Three
times in a single sitting, an assertion found the string it was banning inside the comment
explaining why it is banned:

| Guard | What it actually matched |
|---|---|
| "no interpolated Tailwind class" | the comment in `Sidebar.tsx` warning against interpolating |
| "`colorScheme` matches the ground" | the comment in `layout.tsx` explaining why `'dark'` was wrong |
| "no `tone:` on Profile" | the *next item's* `tone:`, via a fixed-width window |

The first two are the same bug and it is now a helper, not a fix: **strip comments before
scanning source.** This codebase comments heavily and on purpose — every incident is written
down next to the code that caused it — so prose that discusses code is, here, guaranteed to
contain the exact strings a guard is looking for. A scanner that does not strip comments will
eventually fire on the documentation of the thing it is checking.

### P6 — Reaching for a smaller number during an incident

Mid-incident I cut `attempts_per_provider` from 2 to 1 to save money. The failure actually
happening was a 429 — the one error where a retry is exactly right. I made recovery worse
while trying to make it cheaper.

**Under pressure, change the thing the evidence names.** The log said "rate limited"; the
change was about cost.

### P7 — Declaring a thing fixed without exercising it

Several times I said "fixed" on the strength of a passing suite. Tests and typecheck do not
prove the app works — the report path passed its tests while producing 0/100 in production.

**Run the real thing.** One end-to-end call against the real endpoint has caught more than any
amount of green.

### P8 — Not checking the environment before believing the output

Twice, ~70 test ERRORs sent me looking for a regression. Docker was not running. asyncpg
raises from inside an SSL connection attempt, so the traceback points at the network layer
rather than at the missing container.

**Before diagnosing a mass failure, check whether the world is running.**

### P9 — A comment is a claim, and nothing type-checks a claim

I wrote `/* The bands are the ones the report itself uses */` beside a set of thresholds I had
just invented. They were not. The report used a different set, and the backend — which produces
the words the candidate actually reads — used a third. Three sets of numbers, no agreement,
and the only thing asserting they agreed was a sentence I typed.

This is the same failure as the hardcoded ₹49 ([M7](#m7--a-hardcoded-49-in-a-402-message)) but
one level worse, because the comment made the duplication look deliberate and checked.

**If a comment claims two things agree, either make them the same thing or write the test.**
The fix here was both: one `SCORE_BANDS` constant, and a test that reads the thresholds back
out of `composer.py` — because the realistic failure is somebody editing the Python with its
own tests passing, never opening a `.ts` file.

### P10 — I put a destructive command in a cleanup line and ran it without reading it

The single most expensive thing I have done to this repository, and it took one line.

Mutation-testing a guard means breaking the code, watching the test fail, and putting the code
back. For three mutations I restored from a `cp` backup. For the fourth — which had edited
**every page file** — I reached for `git checkout -- "src/app/(dashboard)"`.

That is not "undo my mutation". That is **"discard everything not committed"**, and an entire
session of uncommitted redesign work across fourteen pages went with it. The mutation was
reverted perfectly. So was everything else.

Three things made it worse than it needed to be:

- **`|| true` on the end**, which I had added so a failed cleanup would not abort the loop. It
  also guaranteed I would not notice if the command did something enormous.
- **The work was never committed.** The user had said not to *push*; nothing prevented a local
  commit, and a commit would have made this a one-line recovery instead of an hour of redoing.
- **I wrote the line as an afterthought**, at the end of a command whose real subject was the
  mutation test. Destructive operations do not become safe by being small parts of larger
  commands.

**The rules, now:**

1. **Never `git checkout --`, `git restore`, `git clean` or `git reset --hard` on a path with
   uncommitted work.** Mutation-test by restoring from an explicit `cp` backup of exactly the
   files touched, taken immediately before.
2. **Commit before any experiment that writes to many files.** A local commit is free, reversible
   and is not a push.
3. **A destructive command gets its own call and its own read-through.** Not the tail of a loop,
   not after `&&`, and never behind `|| true`.

### P11 — A 200 is not a rendered page

I verified this redesign with `tsc`, `eslint`, 807 unit tests, a full `next build` of all 33
routes, and a `curl` of every public URL returning 200. All of it passed. Then I took one
screenshot and the browser was showing a **"1 Issue"** badge: React had thrown away the entire
server-rendered tree on `/demo` because the server's date text did not match the client's.

Every check I had run was blind to it by construction:

| check | why it could not see this |
|---|---|
| `tsc` / `eslint` | both renderings are valid TypeScript |
| unit tests | they render components in one environment, so there is no second one to disagree with |
| `next build` | it compiles and prerenders; nothing compares that output to a browser's |
| `curl … → 200` | the server produced HTML. That is all a 200 means. |

**The bug lived in the gap between the server rendering and the browser accepting it, and only
a browser sits in that gap.** Hydration mismatches, layout that collapses at a real viewport,
a font that never loads, a click handler that throws — none of them have a server-side symptom.

**Run a headless browser and read the console.** It is three lines:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --disable-gpu \
  --virtual-time-budget=9000 --enable-logging=stderr --v=0 --dump-dom http://localhost:3000/PAGE \
  2>console.txt >/dev/null
grep -i "hydration\|error\|warning" console.txt
```

Screenshot it too. The screenshot is what caught this: I was looking at the design and the
overlay badge was sitting in the corner of it.

---

## The individual mistakes

### M1 — The report retry that rescued nobody

Reports were stranded at 0/100. I added a cooldown so an exhausted report could try again,
computed from `unscored_last_at`. Every already-stranded row predated that field, so it could
not be aged, so it was never retried. Shipped a fix whose population was empty.

**Cost:** an entire round trip with the user, who reported the same symptom again.
**Pattern:** [P2](#p2--fixing-the-mechanism-does-not-fix-the-people-already-broken-by-it).

### M2 — `wait_for(gather(...))` threw away the work it was protecting

The report was split into concurrent parts specifically so a failure would cost one part. I
wrapped the whole thing in a deadline, which cancels *at the gather* — so at the deadline every
part that had already succeeded was discarded and the candidate got the same 0/100.

The split was working. My wrapper was the bug.

**Cost:** a full user-reported cycle after shipping what I said was the fix.
**Pattern:** [P3](#p3--i-re-introduce-traps-this-codebase-has-already-documented).

### M3 — N concurrent calls tripped a rate limit I did not think about

Replacing one model call with a summary plus N batches fixed latency and multiplied the
*instantaneous* request rate by the number of parts. Production answered with 429 — the
account's own limit. I optimised one dimension and moved the failure to another.

**Cost:** another user-reported cycle.
**Fix:** a per-report concurrency gate. **Pattern:** partly P3, partly not thinking about what
a change does to *rate* rather than to *total*.

### M4 — Six vacuous guards

Listed in [P1](#p1--a-guard-that-cannot-fail-is-worse-than-no-guard). Each was found by
mutation, never by reading. The `app.routes` one is the sharpest: an admin-authorization sweep
that discovered **zero admin routes** and would have reported full coverage forever.

**Pattern:** [P1](#p1--a-guard-that-cannot-fail-is-worse-than-no-guard).

### M5 — Mutation tests I said I ran, twice

The shell was not expanding the variable holding my test command. Every "mutation" printed
nothing and I read that as success. I repeated it later in the same session.

**Cost:** two false claims of verification to the user, which is worse than the wasted time.
**Pattern:** [P4](#p4--assuming-my-own-tooling-ran).

### M6 — `db.add()` outside the savepoint

I put a duplicate-tolerant insert in a SAVEPOINT — the right lesson from an earlier incident —
but added the object *before* the savepoint. On a duplicate the savepoint rolled back while the
failed object stayed pending, so the request's final commit flushed it again. A handled
duplicate becoming a 500 during dependency teardown, far from its cause.

Worse: **the endpoint tests could not see it**, because `get_db` commits after the response is
formed. Removing the savepoint entirely left all 18 HTTP tests green.

**Pattern:** P1 again — the test could not fail. Fixed by testing the handler directly.

### M7 — A hardcoded ₹49 in a 402 message

The exact drift `plans.py` exists to prevent, and its comments warn about, written by me.

**Pattern:** not reading the module I was editing.

### M8 — Two assertions stricter than the property

`..` anywhere in a filename; `mutateAsync` anywhere in a page. Both failed on legitimate code.

**Pattern:** [P5](#p5--my-assertions-are-often-stricter-than-the-property).

### M9 — Cutting retries mid-incident

`attempts_per_provider` 2 → 1 for cost, while the live failure was a 429.

**Pattern:** [P6](#p6--reaching-for-a-smaller-number-during-an-incident).

### M10 — A duplicate rating discarded a whole report

Not originally my code, but I owned diagnosing it and it took far too long. `record_round`
handled an expected duplicate with `db.rollback()`, and reports shared that transaction — so a
second generation silently lost its write and returned 200.

I chased it through instance staleness, an explicit UPDATE, and an expunge before finding it.
What finally worked was **instrumenting the actual values** (`rowcount`, what was written, what
was stored) instead of reasoning about what should happen.

**Lesson:** when the evidence contradicts the model, stop refining the model and measure.

### M11 — Assuming the frontend was fine because tests passed

`NudgeDeck` was mounted and rendering nothing — it gated on four queries all resolving, and any
one failing meant no card. The tests asserted the gate existed; nobody asserted a card ever
appeared.

**Pattern:** P1, and P7 — nothing exercised it for real.

### M12 — Three different answers to "what does this score mean"

`composer.score_label` banded at 85/70/55/40 and produced the words. The report page's bars
banded at 75/50/30. I added a third set at 70/50 on the dashboard and wrote a comment saying it
matched the report.

The visible effect: a 72 printed as **Good** beside a bar the same colour as a 51.

Nobody decided this. Two people decided two things in two languages and nothing could see both
at once — which is why the fix is a test that crosses the language boundary rather than one
more careful constant.

**Cost:** caught before shipping, only because I went to verify my own comment.
**Pattern:** [P9](#p9--a-comment-is-a-claim-and-nothing-type-checks-a-claim).

### M13 — `for f in $files` silently did nothing in zsh

I ran a 33-file rename, got "renamed in 19 files", and the count of the old name was still 33.
zsh does not word-split unquoted parameters, so `perl` received the entire newline-joined list
as one filename and failed on each pass.

It printed errors and a cheerful summary in the same breath. Had I only read the summary I
would have reported a rename that had not happened.

**Pattern:** [P4](#p4--assuming-my-own-tooling-ran) — the summary line was mine, the error was
the tool's, and I nearly believed the wrong one.

### M14 — I re-committed two documented mistakes inside the test written to prevent drift

Writing `tones.test.ts`, in the same file:

- I scanned a **fixed 220-character window** after each `href:` looking for a `tone:`. It ran
  past the end of the untoned Profile entry and picked up the next item's tone, reporting that
  Profile was amber. This is [P1](#p1--a-guard-that-cannot-fail-is-worse-than-no-guard)'s "a
  window reaching a neighbour", which is in the table above, which I had read that morning.
- My interpolation ban matched the **comment warning against interpolation**. The file
  explaining the rule was reported as breaking it —
  [P5](#p5--my-assertions-are-often-stricter-than-the-property).

Both failed loudly rather than silently, which is the only reason this entry is cheap. But
that is luck: a window that reaches a neighbour usually reads a *plausible* value.

**Lesson:** reading the ledger is not the same as applying it. Before writing a source-scanning
assertion, ask the two questions the ledger already asks — *can this match something outside
the thing I mean?* and *would this fail on correct code?*

### M15 — The app declared itself dark for a whole retheme

Not mine originally, but I did four rounds of visual work on this theme without noticing.
`layout.tsx` still carried `themeColor: '#0a0d14'` and `colorScheme: 'dark'` from before the
retheme to warm paper.

Both are read by the BROWSER, not the page, which is why no amount of looking at the page found
them: a near-black Android address bar directly above a `#F9F6F0` page, native selects and
scrollbars drawn from the dark palette, and a dark flash before the stylesheet arrived — on the
first screen anybody sees.

**Why it survived:** it is a build-time constant that cannot reference a CSS variable, so it
duplicates `--background` by hand, and nothing compared the two. Now
`theme-contrast.test.ts` converts the token to hex and asserts the match, and derives the
expected `colorScheme` from the ground's own lightness.

**Pattern:** [P9](#p9--a-comment-is-a-claim-and-nothing-type-checks-a-claim) — I very nearly
shipped the same class of thing again, writing "if the ground is ever retoned, retone this with
it" as a comment. That sentence is a claim. It is now a test.

### M16 — A JSX comment inside a conditional's parentheses, twice in one session

`{cond && ( {/* why */} <span/> )}` does not compile. The parentheses hold ONE element, and a
`{/* */}` comment is a second child — so the error surfaces as `JSX element has no
corresponding closing tag` forty lines away from the edit, in `admin/analytics/page.tsx` and
then again in `profile/page.tsx`.

Trivial, caught instantly by `tsc` both times, and worth recording only because of the repeat:
the habit that causes it is writing the comment where the reasoning belongs rather than where
the syntax allows. **The comment goes ABOVE the `{cond && (` line**, which also reads better —
it explains the whole conditional rather than just its body.

**Pattern:** none of the existing ones. A mechanical slip, now written down so the third time
does not happen.

### M17 — I reverted a whole session of my own work with a cleanup command

While mutation-testing the `.lit` hierarchy guard, the fourth mutation stripped the class from
every page. To undo it I ran, as the tail of a longer command:

```
git checkout -- "src/app/(dashboard)" src/app/pricing/page.tsx 2>/dev/null || true
```

Every redesigned page went back to HEAD: dashboard, tracks, analytics, quiz, prepare,
achievements, communication, report, interview, gd, profile, settings, admin, pricing — plus the
product rename on those files, and the one page a subagent had completed.

**What saved it, and what did not.** `cp` backups covered exactly one file. The subagent's work
survived only because an unrelated diff had been written to the scratchpad earlier. Everything
else had to be redone by hand from the conversation.

**The tell I ignored:** I had just written `cd "/Volumes/Volume D/Mock Interview"` on the *next*
line, which is why I thought the checkout was scoped to the repo root rather than to `frontend/`.
Paths in git resolve against the current directory, and the `cd` that would have made my mental
model true ran afterwards.

**Cost:** roughly an hour of rework, and it was entirely self-inflicted.
**Pattern:** [P10](#p10--i-put-a-destructive-command-in-a-cleanup-line-and-ran-it-without-reading-it).

### M18 — Side effects inside a React state updater, in two places

Found by a guard written for the first one, which then found the second.

`settings/page.tsx` had `localStorage.setItem` and a `toast.success` inside
`setEmailNotifications(v => { ... })`. `communication/page.tsx` had `clearTimer()`,
`stopRecording()` and a toast inside `setSecondsLeft(s => { ... })` — on the screen where the
microphone state IS the interaction.

**A state updater must be a pure function of the previous state.** React may call it more than
once for a single update, and `reactStrictMode: true` in `next.config.ts` guarantees it does so
in development. One tap produced two toasts; one expiring countdown stopped the mic twice.

The same file also read `localStorage` unguarded inside a `useEffect`. It **throws** rather than
returning null when a browser blocks site data, and a throw in an effect is a render error — so
the entire settings page failed to appear because of a stored preference. `NudgeDeck` already
wrapped its own calls and explained why; this file had simply never learned it.

**Pattern:** [P3](#p3--i-re-introduce-traps-this-codebase-has-already-documented) — the
countermeasure was already written down, in a neighbouring component, in a comment.

### M19 — Two guards that fired on correct code, in the test written to catch M18

Both in `browser-storage.test.ts`, both [P5](#p5--my-assertions-are-often-stricter-than-the-property):

- **Counting `try` and `catch` inside a fixed twelve-line window.** A guarded call was flagged
  because the look-back happened to include the *closing* `} catch` of an earlier, unrelated
  block, so opens and closes balanced. The fix is to ask which marker is NEARER, not how many
  of each there are.
- **`/\bset[A-Z]\w*\(/` to mean "a state setter"** — which matches `setInterval` and
  `setTimeout`, so it reported every timer in the app. The property is a `useState` setter
  called with a function of the previous state; timers take a callback of no arguments.

Both would have trained me to "fix" working code, which is the specific damage a
false-positive assertion does.

### M20 — A hydration mismatch that every green check missed

`/demo` — linked from the landing page, so one of the first things a prospective candidate sees
— was throwing away its whole server-rendered tree on load. `new Date(x).toLocaleDateString()`
formats in the AMBIENT locale: Node's on the server, the browser's on the client. Node said
`7/20/2026`, the browser said `20/07/2026`, React saw the text differ and re-rendered
everything.

The same call appeared at **14 sites**, and it was a correctness bug quite apart from
hydration: with no locale pinned, one candidate saw `20/07/2026` and another `07/20/2026` for
the same report — and for the first nineteen days of a month **both are valid readings of the
same string**, so neither can tell which they are looking at.

Fixed at the cause: `lib/format-date.ts` pins `en-IN` and prints the month as a word
(`20 Jul 2026`), which removes the ambiguity rather than merely making it consistent. It also
returns `—` for an unparseable value, because `new Date('nonsense')` does not throw — it
produces an Invalid Date whose formatter returns the literal string "Invalid Date".

**Pattern:** [P11](#p11--a-200-is-not-a-rendered-page).

### M21 — An assertion whose arithmetic was wrong

Editing the real `.env`, I guarded the change so that only the product name could differ:

```python
assert len(before) - len(s) == 3   # "InterviewOS" → "Hotseat"
```

The delta is 4, not 3. The guard fired on a correct edit and stopped the whole script.

Harmless because it failed closed on a file holding live credentials — which is exactly what I
wanted it to do — but it is [P5](#p5--my-assertions-are-often-stricter-than-the-property) once
more, and in its purest form: I wrote a number instead of computing one. The fix was to say
what I meant, `len("InterviewOS") - len("Hotseat")`, which cannot be wrong.

### M22 — Documentation that promised more than the code allows

`CLAUDE.md` stated the free tier as "2 interviews, 1 GD, 5 communications". The real
`TRIAL_ALLOWANCE` is `interview: 0, gd: 0, communication: 1` — interviews and group discussions
were made paid-only and the note was never updated.

Not my error, but worth recording because of the DIRECTION it was wrong in: it described a
product **more generous** than the ledger will permit. Anybody trusting it would have "fixed"
the pricing page to promise interviews that a new account cannot start, and the bug would have
surfaced as a 402 at the moment of purchase intent.

**Lesson:** a restatement of a constant is a copy of it. `plans.py` says so in its own header;
the note in CLAUDE.md now says to read `plans.py` and not to trust any restatement, including
its own.

---

## Additions

New entries go here with a date, then get promoted into the numbered list once the pattern is
clear. If a new mistake matches an existing pattern, say so explicitly — a repeat is a
stronger signal than a novelty.

---

## The verification checklist

Each line exists because something below was missed by every check above it. Run them in
order; the cheap ones first, but none of them substitutes for a later one.

1. **`npx tsc --noEmit` and `npx next lint`** — catches types and dead code. Catches no
   behaviour.
2. **`npm test -- --run` and `uv run pytest`** — and if a mass of tests errors, check whether
   Docker and the project's Postgres are actually running before diagnosing anything
   ([P8](#p8--not-checking-the-environment-before-believing-the-output)). Twice ~70-119 errors
   have been a stopped container.
3. **Break every new guard on purpose and watch it fail**
   ([P1](#p1--a-guard-that-cannot-fail-is-worse-than-no-guard)). Also break something it must
   NOT flag, or you will ship a false positive that trains you to damage working code.
4. **`npm run build`** — compiles every route, and it is the only place a Tailwind class that
   is assembled at runtime disappears. Grep the emitted CSS for the classes you added.
   Do NOT run it while a dev server is using `.next`; it replaces the directory underneath it
   and the dev server starts 500-ing.
5. **A headless browser with the console captured, and a screenshot**
   ([P11](#p11--a-200-is-not-a-rendered-page)). A 200 means HTML was produced, nothing more.
6. **The real end-to-end path** ([P7](#p7--declaring-a-thing-fixed-without-exercising-it)) —
   `/api/v1/health` should report database, redis and supabase all connected, and the
   frontend's own `/api/v1/*` proxy should return the same.
7. **Commit before any experiment that writes to many files**
   ([P10](#p10--i-put-a-destructive-command-in-a-cleanup-line-and-ran-it-without-reading-it)).
   A local commit is free and is not a push. Not doing this cost an entire session's work once.
