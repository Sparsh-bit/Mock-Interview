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
├── difficulty/          # Difficulty calibration guidelines
│   └── calibration.md
└── interview_patterns/  # Company-specific interview formats
    └── cognizant_java_fse.md
```

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

### Adding a company interview pattern
Create a `.md` file in `interview_patterns/`. Include: round structure, topic weightings, common question types, and known evaluation criteria.

## Seed Script

To populate the database from this knowledge base:
```bash
cd backend
uv run python scripts/seed_knowledge_base.py
```
