# Difficulty Calibration Guidelines

## Overview

Difficulty calibration ensures that "medium" means the same thing across topics, companies, and evaluators. This document defines the rubric used by the Interview Orchestrator when selecting questions and by the AI Evaluator when scoring answers.

## Difficulty Definitions

### Easy
- Recall-level question
- Any candidate with 1+ year of Java experience should answer completely
- Ideal answer ≤ 3 sentences or ≤ 5 bullet points
- No real-world application required — definition + example is sufficient
- Example: "What is the difference between == and .equals()?"

### Medium
- Understanding-level question
- Requires knowing the WHY, not just the WHAT
- Candidate should explain trade-offs or design considerations
- Ideal answer includes at least one real-world scenario or gotcha
- 3+ years experience expected for a complete answer
- Example: "When would you use ConcurrentHashMap vs synchronizedMap?"

### Hard
- Application or analysis-level question
- Requires deep internals knowledge or architectural thinking
- No single correct answer — quality of reasoning matters
- Candidate should be able to discuss alternatives and trade-offs
- 5+ years experience expected, or exceptional junior
- Example: "How does the Java garbage collector decide when to promote an object from Young to Old generation?"

## Adaptive Difficulty Rules (Orchestrator Configuration)

```
strong_answer (score ≥ 8.0):
  → Increase difficulty of next question by one level
  → If already at Hard: add a follow-up that goes deeper

acceptable_answer (6.0 ≤ score < 8.0):
  → Maintain current difficulty
  → Select follow-up if completeness_score < 7.0

weak_answer (4.0 ≤ score < 6.0):
  → Decrease difficulty of next question
  → OR switch to a different subtopic within the same topic

very_weak_answer (score < 4.0):
  → Decrease difficulty by two levels
  → Move to next topic after one more attempt
  → Flag topic as "needs significant improvement" in report

bluffing_detected:
  → Ask follow-up that requires precise technical detail
  → Do not increase difficulty — verify current level first
```

## Score Anchor Examples (Java Core)

### Easy — Score Anchors

| Score | Answer Quality |
|---|---|
| 9-10 | Perfect definition + correct example + mentions relevant edge case |
| 7-8 | Correct definition + example (minor detail missing) |
| 5-6 | Partially correct — misses one key concept |
| 3-4 | Vague — uses right words but wrong meaning |
| 1-2 | Incorrect or completely off-topic |
| 0 | No answer / "I don't know" |

### Medium — Score Anchors

| Score | Answer Quality |
|---|---|
| 9-10 | Correct + explains internals + discusses trade-offs + gives production context |
| 7-8 | Correct + explains trade-offs (minor gap in internals) |
| 5-6 | Correct at surface level — no internals, no trade-offs |
| 3-4 | Partially correct — confuses concepts or misses key aspect |
| 1-2 | Incorrect but sounds confident (bluffing risk) |
| 0 | No answer |

## Communication Score Rubric

| Score | Description |
|---|---|
| 9-10 | Clear, structured, uses correct terminology, appropriate pace |
| 7-8 | Clear and mostly structured, minor terminology gaps |
| 5-6 | Understandable but disorganized, filler words, terminology errors |
| 3-4 | Hard to follow, frequent hesitations, significant errors |
| 1-2 | Very difficult to understand |
