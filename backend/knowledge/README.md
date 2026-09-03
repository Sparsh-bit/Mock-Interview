# InterviewOS Knowledge Base

This directory contains curated interview knowledge organized by topic, company, and pattern. It serves as the foundational data source for the Interview Orchestrator.

## Purpose

The knowledge base combines two things:
1. **Curated questions** — Real interview questions gathered from public interview experiences (Glassdoor, LinkedIn, Blind, GeeksForGeeks)
2. **Topic reference material** — Technical summaries used to verify answer quality and generate follow-ups

The Interview Orchestrator uses this knowledge base alongside GLM's reasoning to produce realistic, adaptive interview sessions.

## Directory Structure

```
knowledge/
├── topics/              # Technical concept references by domain
│   ├── java/            # Core Java, Collections, Streams, Concurrency, JVM
│   ├── spring/          # Spring Boot, Security, Data JPA, Cloud
│   └── databases/       # SQL, NoSQL, JPA, Query Optimization
├── questions/           # Curated question sets in YAML format
│   ├── java_core.yaml
│   ├── spring_boot.yaml
│   └── databases.yaml
└── difficulty/          # Difficulty calibration guidelines
    └── calibration.md
```

Company interview FORMATS are deliberately not here. What a given company asks in
a given program — areas, weights, sub-topic descriptors, cross-question themes,
which forms each area can be asked in — lives in `app/data/syllabus.py`, as typed
Python that mypy checks and that raises at import if anybody puts a question in
it. See that file's header for the argument; the short version is that this
directory once held `interview_patterns/cognizant_java_fse.md`, a round-by-round
reference with a "Commonly Asked Questions (must ask every session)" list, read by
nothing in `app/`, `scripts/`, `tests/` or `docs/`. A candidate then reported a
mock that asked the same recycled questions, and a Markdown file with no reader is
a copy-paste source with nothing to keep it honest.

## Adding Content

### Adding a new question
Edit the appropriate YAML file in `questions/`. Each question requires:
- `id`: Unique string identifier
- `content`: The question text
- `topic`: Must match a topic slug in the database
- `difficulty`: easy | medium | hard
- `type`: conceptual | practical | scenario | coding
- `expected_keywords`: List of concepts the ideal answer covers
- `ideal_answer`: (Optional) Reference answer for evaluation calibration

### Adding a new topic reference
Create a `.md` file in the appropriate `topics/` subdirectory. The filename becomes the topic slug.

### Adding a company interview format
Not here. Append a `Syllabus` to `SYLLABI` in `app/data/syllabus.py` — rounds,
topic weightings and question FORMS, as data the planner reads. Descriptors of
what is covered, never a question a candidate could be asked: the import-time
validator in that module rejects any authored string carrying a question mark, an
interrogative opener, a second-person pronoun or more than nine words, and
`tests/test_syllabus.py` rejects one that shares a five-word phrase with any
question bank in the repo.

## Seed Script

To populate the database from this knowledge base:
```bash
cd backend
uv run python scripts/seed_knowledge_base.py
```
