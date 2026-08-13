> Part of the [[index|InterviewOS documentation]].

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

| speaker | panel | gender | voice | id |
|---|---|---|---|---|
| **Anil** | interview | male | Professional Male Voice — authoritative, middle-aged | `595c8bbb74eb471fbb599d81dac5672a` |
| **Priya** | interview | female | Clear & Confident Female | `cb131d96670e4d92951e5ea56697c5ab` |
| **interviewer** | fallback | male | *(same as Anil)* | `595c8bbb74eb471fbb599d81dac5672a` |
| **Riya** | GD | female | Clear Assertive Female | `b7e0bd78d38e4ddd81468e2569f2ad3c` |
| **Arjun** | GD | male | Clear Male Voice — young, energetic | `01f34c9748f74dcda57448f033ea2935` |
| **Meera** | GD | female | Friendly Young Female | `1b1286fcf2f44d8ba1405e0b71abca22` |

Riya and Meera are both female and share a round, so they are separated by age band rather
than by tone alone — two similar female voices was a real complaint about the old roster.

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
TTS_VOICE_IDS=Anil:595c8bbb74eb471fbb599d81dac5672a,Priya:cb131d96670e4d92951e5ea56697c5ab,interviewer:595c8bbb74eb471fbb599d81dac5672a,Riya:b7e0bd78d38e4ddd81468e2569f2ad3c,Arjun:01f34c9748f74dcda57448f033ea2935,Meera:1b1286fcf2f44d8ba1405e0b71abca22
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
