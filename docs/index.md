# InterviewOS — documentation

The hub note. Open the vault at the repo root and this is the page the graph hangs off.

**Why this file exists.** Obsidian's graph is built from `[[wikilinks]]`, not from folders — a
tidy directory of notes that never reference each other renders as a field of unconnected
dots, which is exactly what this vault was. Every link below is a real edge in that graph, so
the graph becomes a map of how the product actually fits together rather than a list of
filenames.

Wikilinks resolve by **filename**, not path, so `[[VOICES]]` keeps working wherever a note is
moved to. Prefer them over relative Markdown links for anything inside this vault.

---

## Start here

- [[prompt]] — the product brief and phase-by-phase status. **Read this before making
  architectural decisions**: it records what is genuinely wired versus what is still a
  placeholder. Living context, not a README.
- `CLAUDE.md` at the repo root — build commands, architecture, and the conventions an agent
  needs. Deliberately left at the root rather than moved here, because tooling looks for it
  there.

## Running it

- [[DEPLOY]] — the current deployment runbook: environment variables, the settings that
- [[KNOWN-GOOD]] — the state everything was in before the security pass, and why each thing is that way
- [[COMPLIANCE]] — DPDP Act and adjacent regimes: what the code does, and the gaps
  actually matter, and what breaks when each one is wrong.
- [[DEPLOYMENT]] — the older, longer infrastructure write-up. Overlaps [[DEPLOY]]; where they
  disagree, [[DEPLOY]] is newer.

## Money

- [[AI-COST-MODEL]] — what each feature costs per call, measured from the real usage ledger
  rather than from vendor rate cards. Every number in the plan catalogue is priced against
  this, so it is the note to re-read before changing an allowance.
- [[TEMPORARY-token-counter]] — the interim `ai_usage` ledger and the admin screen over it.
  Explicitly temporary: it was the stand-in for a credit system, which now exists in
  `backend/app/services/billing/`. This note describes what can be removed.

## Voice

- [[VOICES]] — the panel roster, which voice id belongs to whom, the tone table, per-speaker
  pace, and the one command that stops a voice being wrong again. Start here for anything
  audio.
- [[ELEVENLABS-SETUP]] — **superseded**, kept only for the vendor cost comparison that
  decided the current provider. Do not follow its setup steps. See [[VOICES]].

## The interview itself

- [[INTERVIEW-REDESIGN]] — why the interview is a room with a two-person panel rather than a
  form with questions on it, and the reasoning behind the surfaces that came out of it.

---

## Where the rest of the documentation lives

Most of this codebase explains itself in place, and that is deliberate — a note describing a
function drifts from it, whereas a comment above the function does not. The two places worth
knowing about:

- `backend/app/prompts/*.md` — the AI prompts, as Markdown. These are **product behaviour, not
  documentation**: editing `interview_panel.md` changes what the panel says. They are part of
  the vault and will show in the graph, which is useful, but treat them as source.
- `backend/knowledge/` — hand-maintained YAML reference data (the recruiter catalogue, study
  subtopics, per-company research) read at runtime.

- [[DESIGN-LANGUAGE]] — what Hotseat looks like, and why
- [[REDESIGN]] — page-by-page progress
