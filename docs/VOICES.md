> Part of the [[index|Hotseat documentation]].

# Voices

What the panels sound like, which ids are set, and the one command that stops a voice being
wrong again.

Fish Audio is the provider (`TTS_PROVIDER=fish`, model `s2.1-pro-free`). Everything below is
about `TTS_VOICE_IDS`, which is the only setting that decides who sounds like whom.

---

## The roster

Neutral English throughout — no Indian accent, no British. That is a change from the
original design and it was a deliberate one, twice over:

- **The en-IN voices were the problem, not the accent.** Ranking accent above quality picked
  Apple's Rishi and Veena — decade-old formant synths — over good neural voices. Told to
  choose, the product should sound like a person with a slightly wrong accent rather than a
  machine with the right one.
- **British is last on purpose.** Not a quality judgement: a British interviewer is the wrong
  character for an Indian campus panel, and lands as more incongruous than a neutral
  American one.

| speaker | panel | gender | voice | uses / likes | id |
|---|---|---|---|---:|---|
| **Anil** | interview | male | Ethan — authoritative, calm, clear | 426,490 / 2,539 | `536d3a5e000945adb7038665781a4aca` |
| **Priya** | interview | female | Paula — articulate, confident, professional | 126,893 / 1,606 | `c2623f0c075b4492ac367989aee1576f` |
| **interviewer** | fallback | male | *(same as Anil)* | — | `536d3a5e000945adb7038665781a4aca` |
| **Riya** | GD | female | Hannah — professional, confident, middle-aged | 232,838 / 1,250 | `9a9cf47702da476aa4629e2506d4a857` |
| **Arjun** | GD | male | alex — clear, professional, young | 52,699 / 675 | `1d52151a55eb4878a997bd06e816b5f6` |
| **Meera** | GD | female | Friendly Young Female | 2,727 / 70 | `1b1286fcf2f44d8ba1405e0b71abca22` |

Riya and Meera are both female and share a round, so they are separated by age band rather
than by tone alone — two similar female voices was a real complaint about the old roster.
Hannah is middle-aged and Meera is young, so that separation survives the changes below.

### Anil, Priya and Arjun were replaced, by the argument already written here

Reported as "the voices must not look cheap". Measured, and the report was right — the usage
numbers are not close:

| speaker | old voice | uses | likes |
|---|---|---:|---:|
| Anil | Professional Male Voice | **57** | **0** |
| Priya | Clear & Confident Female | **108** | **3** |
| Arjun | Clear Male Voice | **42** | **1** |

Fifty-seven generations. Zero likes. These were near-empty community uploads whose only
recommendation was a title that reads like a description — and this document had ALREADY
established, in the section below, that usage is the only quality signal available without
listening to every candidate in the catalogue. Riya was replaced by that argument. Anil,
Priya and Arjun were never put through it. So the reasoning existed and half the roster had
never been measured against it, which is the more useful thing to record than the ids.

The replacements are the top of the English catalogue by real usage, filtered to tags that fit
a corporate interview panel and against a reject list — `character-voice`, `entertainment`,
`announcer`, `advertisement`, `breathy`, `old`, and every regional accent.
`scripts/verify_voices.py` passes on the new roster.

**Ethan for Anil**, on 426k generations with the best like-rate of any male candidate
(2,539), is `authoritative`, `calm`, `clear`, `professional`.

Slax (`c5f56a6c…`) was chosen first, on the strength of 1.3 million generations — the
most-used professional male voice in the catalogue — and was rejected after listening:
reported as "horrific" and "very bad". That is worth recording rather than quietly
overwriting, because it is the limit of this document's whole method. Usage separates a
57-generation upload from a real voice, and it cannot separate two real voices: 1.3M
generations told us Slax is not amateur, and nothing about whether it is pleasant to be
interviewed by. **Rank by usage to build the shortlist, then listen before committing.** That
step was skipped here and cost a round trip.

**Paula for Priya**, on 127k generations with the best like-rate of any candidate, is
`articulate`, `confident`, `conversational`, `professional`. She sits beside Slax in the same
round, so the choice was partly about separation: Laura (`e3cd3841…`, 154k / 1,478) scores just
as well but is `deep`, `warm`, `calm` — too close to Slax's measured register, and two voices
that blur is the exact complaint Riya and Meera were separated to avoid.

**alex for Arjun** is the smallest of the three upgrades and the least certain. `Energetic
Male` (`802e3bc2b27e49c2995d23ef70e6ac89`) has far better numbers — 585k / 2,983 — and was
rejected on register: it is tagged `announcer` and `advertisement`, and a voice that sounds
like a commercial is wrong in a discussion however popular it is. Arjun's documented stance is
energetic, so this trades some of that for a professional register. If the GD sounds flat,
`Energetic Male` is the deliberate alternative and this paragraph is the trade.

### Susan FE was rejected, and how it was caught is the point

`56431e329b21489c9f9f7ab9c77312d4` was the strongest candidate on tags alone — the only voice
in the catalogue tagged both `Corporate` and `Business`, which is literally what was asked
for. Its own description reads:

> A professional and confident middle-aged **male** voice.

Tagged female, described male. That is exactly the failure recorded below — Meera was given a
male voice twice — and the only reason it did not happen a third time is that the description
was read rather than the tags trusted. `verify_voices.py` checks the gender TAG, so this would
have passed it. **Read the description, not only the tags**, and treat a disagreement between
them as disqualifying rather than as something to resolve.

### Riya was replaced, and popularity is why

She was `Clear Assertive Female` (`b7e0bd78…`) and was still reported as unpleasant after
the pacing fix below — which was the signal that pacing was not the whole problem. The
catalogue says why: **128 generations and 1 like**, against hundreds of thousands and
four figures for the voices people actually use. Fish's catalogue is largely
community-uploaded and varies enormously in quality, so usage is the only quality signal
available without listening to every candidate.

Ranking English female voices by usage and discarding the unusable ones is quick:
`Jasphina` (960k) is tagged `character-voice, playful, animated, **fast**` — fast being
the original complaint; `Sarah` (1.7M) is `soft, breathy, intimate`, which is the wrong
register for somebody challenging your numbers; most of the rest of the top twenty are
anime characters, celebrity clones and producer watermarks.

That leaves two real candidates, and the choice between them was made by **listening to
both** rather than by reading tags:

| voice | id | tags | usage |
|---|---|---|---:|
| **Hannah** *(chosen)* | `9a9cf477…` | educational, professional, confident, clear | 225k / 1,220 |
| Laura | `e3cd3841…` | deep, warm, calm, professional, clear | 149k / 1,437 |

Laura remains the better fit for **Meera**, whose stance is the synthesiser — calm, warm,
brings quiet people in — if that voice is ever revisited.

`scripts/verify_voices.py` passes on the new roster: female, neutral English, not `old`.

### What the previous roster got wrong

Both faults were audible and both survived a review:

- **Anil was tagged `old`.** "Confident Indian Speaker" is an *old* male voice, and a Senior
  Engineering Manager read as tired rather than senior. That is what "does not sound
  professional" was.
- **Meera had a male voice.** Twice. The id assigned to her carries no single gender tag in
  the catalogue, so nothing about it said "female" and it did not sound female.

---

## Verifying it, which is the actual fix

```bash
cd backend && uv run python scripts/verify_voices.py
```

It reads the expected gender for each name from `PANELISTS` in `api/v1/gd.py` and
`INTERVIEWERS` in `api/v1/panel.py` — the same declarations the prompts and transcripts use,
so there is no second list to drift — then checks each configured id against Fish's
catalogue for:

- the id resolves at all (a typo is a 400 from the vendor, not a graceful fallback)
- the vendor's gender tag matches the gender the panel declares
- the accent is neutral English
- it is not tagged `old`

Exit status is 0 when everything passes, 1 otherwise, so it can gate a deploy script. It
needs a live `FISH_API_KEY`; it is not in CI because CI has no key and no reason to have one.

Run it whenever `TTS_VOICE_IDS` changes. That is the only moment it can catch anything.

Against the old roster it prints:

```
  FAIL Anil         'Confident Indian Speaker'
         - tagged 'old' — reads as tired rather than senior
  FAIL Meera        'Indian Tech Professional'
         - catalogue does not state a single gender
```

---

## Tone

Each panel line carries a `tone`, chosen by the model, because the model is the only thing
that knows which of its own lines is the correction. Delivery is resolved **server-side**
from names — the browser never sends prosody numbers, since speed decides how many seconds
of audio get billed.

| tone | when | speed |
|---|---|---:|
| `asking` | putting a question | 0.95 |
| `correcting` | the answer was wrong — serious, not angry | 0.88 |
| `affirming` | the answer was good | 1.04 |
| `aside` | talking to the other interviewer | 1.08 |
| `neutral` | greetings, the close, answering a question | 1.00 |

Verified against the live API that this is real rather than a field Fish accepts and drops:
identical text at speed 0.80 → 53.9KB, 1.00 → 47.2KB, 1.20 → 35.5KB.

## Pace, which is per SPEAKER rather than per line

Tone says how a *line* is delivered. `SPEAKER_PACE` in `services/tts/base.py` says how a
*person* talks, and multiplies the tone's speed. The two are independent: Riya asking a
question and Riya conceding a point are both still Riya.

| speaker | pace | why |
|---|---:|---|
| **Riya** | 0.92 | reported as "annoying and disturbed" — see below |
| everyone else | 1.00 | no entry needed; unlisted speakers use the tone speed unchanged |

Kept at 0.92 after the voice change. The pace and the voice were two independent causes of
one complaint: the arithmetic below made *any* voice in that slot sound resampled, and the
voice itself was a poor one, so fixing either alone left the other in place. Hannah is not
tagged `fast`, so if she now reads as too slow this is the single number to raise.

Riya is the only entry and the reason the mechanism exists. Her GD stance is the assertive
one, so `personaFor` gave her the largest client-side tempo in the product (1.09), and that
was applied as an `<audio>` **playbackRate on top of** a tone speed already reaching 1.08. An
aside from her therefore played at roughly **1.18**.

The distortion was the bigger half of that, not the speed. A playbackRate *resamples finished
audio*; it does not re-synthesise it. Past about ±12% — a threshold `neural-tts.ts` documents
in its own comment — that stops sounding brisk and starts sounding wrong, which is what
"disturbed" was describing. Three things changed:

- her pace moved into **synthesis**, here, where the vendor actually renders it slower
- the assertive persona tempo dropped `1.09 → 1.02`, with assertiveness now carried by the
  160ms floor-latch instead, which is the channel `persona.ts` already argues is the safest
- the neural playbackRate is damped to 40% of its deviation and clamped to ±5%, so it hints
  at tempo rather than resampling audibly. The **browser fallback keeps the full multiplier**,
  because that path often has to put two panelists on one system voice and there tempo is
  doing the real work of telling them apart

Net: Riya went from ~1.04× to ~0.88× perceived, with the resampling component effectively
gone. Measured on the live API at the same text — `asking` 93,621 → 104,070 bytes,
`neutral` 96,129 → 99,055, `aside` 82,337 → 84,844. Longer audio is slower audio.

Combined tone × pace is clamped to 0.80–1.15. Both multipliers are ours rather than a
caller's, so that is not input validation — it is a guard against two individually reasonable
edits multiplying into something unlistenable, and it bounds the bill, since duration is what
these vendors charge for.

The **resolved speed is part of the audio cache key**, as a number rather than as the
speaker's name. Speed is what differs in the bytes; the name is only how it was chosen.
Keying on the number lets Anil and the `interviewer` fallback — same voice id, same pace —
correctly share one cache entry, while any future per-speaker pace splits them automatically.

Tone is part of the audio cache key. Without that, the first delivery of a line would win
for a fortnight, and a sentence spoken once in passing would be served back — flat — to
every candidate who later got that question wrong.

An unrecognised tone resolves to neutral rather than erroring, at every layer. A client on
last week's bundle must still get audio; silence is a far worse failure than flat delivery.

`speechSynthesis` has no equivalent of prosody, so the browser fallback applies its own
smaller rate and pitch offsets (`BROWSER_TONE` in `lib/speech/neural-tts.ts`). That path is
not rare — it is what every candidate hears once the daily TTS budget is spent — and a
correction that only sounds like one while the vendor is up is a feature that works in the
demo and not in the product.

---

## Setting it on Render

Dashboard → your service → Environment:

```bash
TTS_ENABLED=true
TTS_PROVIDER=fish
FISH_API_KEY=<your key>
FISH_MODEL=s2.1-pro-free
TTS_VOICE_IDS=Anil:595c8bbb74eb471fbb599d81dac5672a,Priya:cb131d96670e4d92951e5ea56697c5ab,interviewer:595c8bbb74eb471fbb599d81dac5672a,Riya:9a9cf47702da476aa4629e2506d4a857,Arjun:01f34c9748f74dcda57448f033ea2935,Meera:1b1286fcf2f44d8ba1405e0b71abca22
```

`FISH_MODEL` is not optional and not a placeholder. Fish bills API credit separately from
platform credit, so an account can look funded and still return 402 on the paid backends;
`s2.1-pro-free` is verified to return real audio in about 3.5 seconds on a zero-credit key.

Note that the model name goes in a **header**, not the request body — which is why getting
it wrong fails as a 402 rather than a 400. That is handled in `services/tts/fish.py`; it is
mentioned here only because the failure is so misleading.

A name missing from `TTS_VOICE_IDS` falls back to browser speech **for that speaker alone**,
not for the whole round.

### Check it took

```bash
curl -s https://<your-api>/api/v1/tts/status -H "Authorization: Bearer <token>" | jq
```

Every name should read `true`. A `false` means that entry is malformed or misspelt.

---

## When it goes wrong

Every one of these degrades to browser speech and the session continues:

| situation | what happens |
|---|---|
| `TTS_ENABLED=false` | never attempted |
| no API key | `/tts/status` reports `enabled: false` |
| daily budget spent | `402`, everyone moves to browser voices |
| Fish API credit exhausted | `402` — separate from platform credit, top up at fish.audio/app/developers |
| Fish down or slow | `503` after 12s server-side |
| one voice id missing | that speaker alone uses the browser |
| Redis unavailable | works, but the audio cache stops helping |

The one thing that would be unacceptable — a TTS problem breaking an interview — cannot
happen, because every caller treats any non-200 as "use the browser".
