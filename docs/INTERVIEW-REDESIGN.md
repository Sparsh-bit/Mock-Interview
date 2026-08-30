> Part of the [[index|Hotseat documentation]].

# The interview section

What it looks like now, what the panel does, and the two places where a feature that sounds
generous had to be built so it cannot be gamed.

---

## The layout

Three panes, which is the shape of a real technical screen — the person you are talking to is
*beside* your editor rather than replaced by it.

| | |
|---|---|
| **left** | the conversation — everything Anil and Priya have said, attributed, the speaker ringed |
| **middle** | the compiler, **permanently**, for every question |
| **right** | you — camera, eye contact, live person count |

**On a phone they become tabs, not a stack.** Stacked, the compiler sits two screens below
the question it belongs to and the video below that, so a candidate would be scrolling during
an interview. Tabs keep each pane full height and one thumb away. Above `lg` all three are
simply on screen.

The proctoring alert is duplicated outside the video pane on mobile, because a warning that
only renders inside a hidden tab is not invigilation.

### The compiler is permanent, so it has to say what it is

It is on screen for every question, which means on a theory question it is *not* the answer.
That ambiguity is a real cost, so it is resolved in one line at the top of the editor:

- coding question → *"Write your solution here and submit it. Anil and Priya will read it and
  tell you what they find."*
- anything else → *"Not the answer to this one — answer out loud. This is here to sketch on,
  the way you would use a whiteboard."* Submit is hidden; Run and Review still work.

### The left pane is a thread, not a question box

The old page showed "the question" — one string, replaced each time. That is fine while an
interview is a questionnaire and wrong the moment it is a conversation: a DSA question
arrives, you write code, the panel reads it back and says what is wrong, and you answer
*that*. None of those are "the question".

---

## The phases

```
skill_check → asking ⇄ pivot ⇄ reviewing → closing → done
```

- **skill_check** — "out of ten, how would you rate yourself in Java?"
- **asking** — question, answer, correction on the spot
- **pivot** — they said they did not know; the panel offers another topic
- **reviewing** — they submitted code; the panel reads it
- **closing** — wrap-up, "any questions for us?", and a real answer to it
- **done** — the report

**Every phase falls through on failure, and End Interview is live in all of them.** The close
adds three panel turns between the last answer and the report; a candidate must never be
unable to reach their own result because a piece of dialogue would not generate.

The microphone only arms during `asking` and `skill_check`. Without that gate it opens during
a code review and transcribes Anil reading the candidate's own code back to them, straight
into the next answer. `pivot` and `closing` have on-screen controls instead, because a spoken
"yes" is indistinguishable from the start of an answer to a recogniser.

---

## The panel reviews your code

The candidate writes in the editor and submits; the panel reads it and names what is wrong,
the way two engineers reading your screen would.

**The code is never sent from the browser.** It is the answer that was just submitted, and
the server reads it back out of the database — the same rule that keeps the answer key
server-side, and it means a review cannot be produced against code the candidate did not
actually submit.

Verified against the live model on a deliberately broken `findMax`:

> **Priya:** your loop condition is `i <= a.length` — that'll throw an
> ArrayIndexOutOfBoundsException on the last iteration.
> **Priya:** Also, initializing max to 0 breaks if all elements are negative — you'd never
> update it.

Two real bugs, both actually in the code. The prompt is explicit that inventing a bug is
worse than finding none — *a review that is itself wrong is worse than no review in a product
that teaches* — and that a stub is a different conversation from a wrong attempt:

> **Priya:** this is just a stub — the TODO's still there and it always returns zero. I need
> to see an actual attempt.

---

## "I don't know" → a pivot

> **Priya:** Okay, that's fine, Sparsh.
> **Priya:** Let's switch tracks — do you know about OOP and class design?

### Detecting it is the hard part

`backend/app/services/interview/dont_know.py`, decided **server-side**, with 40 tests. The
naive version — `"i don't know" in answer.lower()` — is wrong in both directions:

```
"I don't know the exact syntax, but you'd use a ConcurrentHashMap
 and compute() is atomic, so..."
```

is a *good answer* that opens with the phrase. Interrupting it to offer an easier topic would
land on exactly the careful students who hedge before explaining.

So the rule is not phrase presence. It is: **short, and nothing substantive left once the
phrase is removed.** Two false positives that survived the first draft and are now tests:
`"You pass the object by reference value"` (correct answer, contains "pass") and `"Not sure,
it might be the heap where objects live"` (a hedged attempt).

**Failing safe means failing to `false`.** A missed give-up costs nothing — the interview
carries on. A false positive interrupts a real answer.

### Which topic it offers

Server-side, and never a topic already covered in this session — offering somebody the
subject they just failed, as a lifeline, is worse than offering nothing. Only topics the bank
can actually source questions for, walked easiest-first, because the point is to find ground
the candidate can stand on.

### Why it cannot be farmed

Every pivot is recorded on the session and **the report counts them**. Without that, "I don't
know" is a free instruction to serve easier questions, and the optimal strategy for anyone
chasing a rating is to decline every hard question until the interview is all foundations.

It is deliberately **not** an extra score penalty. The declined question is already scored as
unanswered; docking again punishes the same event twice, and punishing somebody for admitting
a gap rather than bluffing is exactly backwards in a product built to detect bluffing.

---

## Rate yourself in Java

> **Anil:** Sparsh, before we dive in — out of ten, how would you rate yourself in Java?
> **Anil:** And tell us which areas you're strongest in — we'll pitch our questions around that.

Asked out loud, and read out of the transcript (`lib/interview/self-rating.ts`) — a slider
appearing mid-conversation to catch an answer somebody just said is exactly the seam this
redesign removes. The number buttons are the fallback for when no number can be found, and
the parser **returns null rather than guessing**: a wrong rating silently changes which
questions you get and what your report judges you against, with nothing on screen to say so.

Handles what people actually say: `"seven"`, `"7 out of 10"`, `"maybe 6 or 7"`, `"six, no,
seven"`, `"7.5"`. `"seven out of ten"` parsed as **10** until the denominator was stripped
before the number was read — the word pass takes the last number word, which is the ten.

### The part that keeps it honest

A self-rating is a dial the candidate controls, and this product's credential value rests on
the score being hard to game. If a low rating bought easy questions and the score were
computed identically, claiming 2/10 every time would be optimal.

So it moves two things **in opposite directions**:

- **the questions** — claim 8 and you start at the hard end; claim 3 and you start on
  foundations. Your named strengths become the opening focus concepts, so "collections and
  multithreading" actually steers what you are asked.
- **the expectation** — the claim is recorded and the report judges you against it. Clearing
  a foundation set after saying 3 is not the same achievement as clearing it after saying 9.

It sets the **starting point only**. From the first scored answer the existing adaptive signal
takes over completely, so an overclaim buys two hard questions and is then corrected by
evidence. That is what makes the dial safe to hand over: honesty is dominant in both
directions.

---

## The close

The stages existed server-side since the panel was built and **nothing ever called them**, so
the interview simply stopped when the questions ran out.

Wrap-up → "do you have any questions for us?" → an actual answer. Asked as a text box rather
than by voice: this is the moment the microphone is least reliable, because the candidate has
stopped performing and is thinking, and a mistranscribed question gets a confident answer to
something they did not ask.

Asked for honest feedback, the panel gives it:

> **Priya:** A couple of your fundamentals need tightening — you were a bit shaky on the
> conceptual stuff, so I'd go back and revise those basics properly.

---

## Cost

One extra AI call per pivot and per code review, plus two for the close, on top of one per
question. All are `interview_panel_turn` — `CostTier.CHEAP`, `max_tokens=500`, and the ~2,750
token system prompt is **cached**, so a turn bills ~240 fresh input tokens rather than 3,000.
Measured on a live call: 3,305 cached, 242 fresh, 180 out — about **$0.0044 a turn**.

A 12-question interview with two pivots, one code review and a close is roughly 17 turns,
about **$0.075** of dialogue.

---

## Files

| | |
|---|---|
| `frontend/src/app/(interview)/session/[id]/page.tsx` | the three panes and the phase machine |
| `frontend/src/components/interview/PanelThread.tsx` | the conversation, presentational only |
| `frontend/src/lib/interview/self-rating.ts` | reading a rating out of speech |
| `backend/app/services/interview/dont_know.py` | did they decline, or answer badly |
| `backend/app/api/v1/panel.py` | the stages, and the pivot topic choice |
| `backend/app/prompts/interview_panel.md` | how the panel behaves at each stage |
| `backend/app/api/v1/interview.py` | `/self-rating`, `/pivot` |
