> **SUPERSEDED — see [VOICES.md](VOICES.md).**
>
> The product runs on Fish Audio, not ElevenLabs, and the roster is neutral English rather
> than Indian-accented. Both changed after this was written. VOICES.md has the current ids,
> the env vars to set on Render, the tone table, and the one command that checks a voice
> against the catalogue before it ships.
>
> This file is kept only for the cost comparison below, which is what decided the vendor and
> is still the reasoning to revisit if speech ever needs to move again. Everything else in
> it — the setup steps, the voice ids, the env var names — is out of date. Do not follow it.

> Part of the [[index|Hotseat documentation]].

# Neural voices — ElevenLabs setup

The code is written and wired. This is the part only you can do, plus the numbers you should
see before you commit to it.

---

## Read this first: what it costs

Measured against the real constants — 26 panel turns, ~200 characters a contribution, so
about **7,800 characters per GD round**:

| provider | $/GD round | $/interview | vs the round's AI cost |
|---|---:|---:|---:|
| ElevenLabs Creator ($22/100k) | **$1.72** | $0.63 | **12×** |
| ElevenLabs Pro ($99/500k) | $1.54 | $0.57 | 11× |
| ElevenLabs Scale ($330/2M) | $1.29 | $0.48 | 9× |
| ElevenLabs Scale + **Flash v2.5** | **$0.64** | $0.24 | 4.5× |
| Azure Neural TTS (~$15/1M) | **$0.12** | $0.04 | 0.8× |
| Google Cloud Neural2 (~$16/1M) | $0.13 | $0.05 | 0.9× |

For comparison: **every AI call in a GD round now costs $0.142 in total.**

At a thousand users doing one round a day, that is **$1,716/day on ElevenLabs Creator**
against **$117/day on Azure**.

So the honest position: ElevenLabs sounds the best, and for three named characters arguing
with each other that is worth something real. But it would become roughly 92% of your cost,
and Azure has native **en-IN** voices — Neerja and Prabhat, the two this codebase's own voice
ranking already searches for by name. For Indian campus practice, an authentic accent is
probably worth more than emotional range.

**My recommendation: start with ElevenLabs on Flash v2.5 to hear the difference, keep
`TTS_DAILY_BUDGET_USD` low, and look at the real per-round figure in the logs before turning
it on for everyone.** The provider is a config value, so switching to Azure later is one
module and one branch in `factory.py`.

Verify current pricing on their site — mine is from training data and vendor pricing moves.

---

## Step 1 — Create the voices (this is the part you have not done)

You said you have used ElevenLabs but never imported voices into a project. You need **three
panel voices plus one interviewer**, and the genders must match the names or the whole point
is lost.

1. Sign in at [elevenlabs.io](https://elevenlabs.io) → **Voices** → **Voice Library**.
2. Filter by **Language: English**, and if available **Accent: Indian**. Indian-accented
   English matters here — these panelists are meant to be sitting in a room in India.
3. Pick four and click **Add to My Voices**:

   | speaker | gender | what to listen for |
   |---|---|---|
   | **Riya** | female | assertive, quick, confident — she opens strong and quotes numbers |
   | **Arjun** | male | argumentative, a bit clipped — he interrupts to disagree |
   | **Meera** | female | warmer, calmer — she finds middle ground and pulls you in |
   | **interviewer** | either | neutral, measured, professional |

   Riya and Meera **must be clearly different from each other**, not just both female. Two
   similar female voices is the problem you already reported.

4. For each one, open it in **My Voices** and copy the **Voice ID** — a 20-character string
   like `21m00Tcm4TlvDq8ikWAM`. There is a copy button next to the name.

5. **Profile → API Keys → Create API Key.** Copy it once; it is not shown again.

---

## Step 2 — Set five environment variables

On Render: **Dashboard → your service → Environment**.

```bash
TTS_ENABLED=true
ELEVENLABS_API_KEY=sk_your_key_here
ELEVENLABS_MODEL=eleven_flash_v2_5
ELEVENLABS_TIER=creator
TTS_VOICE_IDS=Riya:21m00Tcm4TlvDq8ikWAM,Arjun:VOICEID2,Meera:VOICEID3,interviewer:VOICEID4
```

Notes on each:

- **`TTS_VOICE_IDS`** — names must match `PANELISTS` in `backend/app/api/v1/gd.py` exactly
  (`Riya`, `Arjun`, `Meera`), plus the literal `interviewer`. Comma-separated, no spaces
  needed. A name you leave out falls back to browser speech **for that speaker only**, which
  is better than the whole round dropping.
- **`ELEVENLABS_MODEL`** — keep `eleven_flash_v2_5`. It bills at half the credits per
  character and answers in ~75ms rather than several hundred, and this sits in the middle of
  a live discussion. `eleven_multilingual_v2` is richer and is the right choice only for
  pre-rendered audio.
- **`ELEVENLABS_TIER`** — must match your actual subscription. It affects nothing but the
  cost figures in your logs; setting it wrong makes your spend reporting wrong, not the audio.
- **`TTS_DAILY_BUDGET_USD`** — defaults to **$5**, which is about three GD rounds on Creator.
  Leave it there while you evaluate. Past it, everyone falls back to browser voices and
  nothing breaks.

Optional:

```bash
TTS_CACHE_TTL_SECONDS=1209600   # 14 days, the default
TTS_RATE_LIMIT_PER_HOUR=200     # ~5 GD rounds per user per hour
```

---

## Step 3 — Confirm it works

```bash
# Signed in, so use a real token from the app
curl -s https://<your-api>/api/v1/tts/status -H "Authorization: Bearer <token>" | jq
```

You want:

```json
{
  "enabled": true,
  "provider": "elevenlabs",
  "budget_remaining_usd": 5.0,
  "voices": { "Riya": true, "Arjun": true, "Meera": true, "interviewer": true }
}
```

If `enabled` is `false`, check in this order: `TTS_ENABLED`, then whether
`ELEVENLABS_API_KEY` is actually set, then whether the budget is already spent. If a name
shows `false`, that entry in `TTS_VOICE_IDS` is malformed or misspelt.

Then start a group discussion. The line **"Standby voices — your browser's built-in speech"**
above the panel strip disappears when neural speech is active. That indicator exists because
otherwise you cannot tell whether you are hearing the real thing.

---

## Step 4 — Check what it actually cost you

After one round:

```bash
grep tts_synthesised <your-logs> | tail -40
```

Each line carries `characters` and `cost_usd`. Add them up and compare against $1.72 —
if it is far off, my per-character estimate needs correcting for your tier.

Watch for `X-TTS-Cache: hit` on the response headers. **Interview** questions come from a
fixed bank of ~37, so after the first candidate those are nearly free. **GD** contributions
are unique text and will never hit — that is expected, not a fault.

---

## How it behaves when things go wrong

Every one of these falls back to browser speech, and the round continues:

| situation | what happens |
|---|---|
| `TTS_ENABLED=false` | never attempted; no round trip wasted |
| No API key | `/tts/status` reports `enabled: false`; never attempted |
| Daily budget spent | `402`, everyone moves to browser voices |
| ElevenLabs down or slow | `503` after 12s server-side; that utterance uses the browser |
| One voice id missing | that speaker alone uses the browser |
| Redis unavailable | works, but the audio cache stops helping |

The one thing that would be unacceptable — a TTS problem breaking a discussion — cannot
happen, because the caller treats any non-200 as "use the browser".

---

## If you switch to Azure or Google later

1. Add `backend/app/services/tts/azure.py` implementing the same `synthesize()` as
   `elevenlabs.py` (it is ~80 lines).
2. Add a branch in `services/tts/factory.py`.
3. Set `TTS_PROVIDER=azure` and put Azure voice ids in `TTS_VOICE_IDS` —
   `Riya:en-IN-NeerjaNeural,Arjun:en-IN-PrabhatNeural,…`.

Nothing else changes. The endpoint, the budget, the cache, the frontend and the fallback are
all vendor-agnostic, and the audio cache key includes the provider name so you will not be
served the old vendor's audio after switching.
