# Cognizant Digital Nurture — Java Full Stack Engineer (FSE)
# Interview Pattern Reference

## Overview

The Cognizant Digital Nurture Java FSE program typically conducts a structured assessment process consisting of multiple rounds. This document captures the commonly reported interview format based on public interview experiences.

## Round Structure

### Round 1 — Online Assessment (Aptitude + Coding)
- Duration: 90 minutes
- Platform: AMCAT or HackerEarth
- Components:
  - Quantitative Aptitude (20 questions, 20 min)
  - Logical Reasoning (20 questions, 20 min)
  - Verbal Ability (20 questions, 20 min)
  - Coding (2 problems, 30 min — Easy/Medium difficulty)
- Coding language: Java (preferred), Python allowed

### Round 2 — Technical Interview 1 (Core Java + DSA)
- Duration: 45–60 minutes
- Format: 1:1 with senior developer
- Focus areas (by frequency):
  1. Java OOP principles (always asked)
  2. Collections Framework — HashMap, ArrayList, LinkedList internals
  3. Exception handling patterns
  4. String handling and immutability
  5. Basic DSA — arrays, linked lists, sorting
  6. Basic SQL queries — joins, aggregations

### Round 3 — Technical Interview 2 (Spring Boot + Databases)
- Duration: 45–60 minutes  
- Focus areas (by frequency):
  1. Spring Boot auto-configuration and starter dependencies
  2. REST API design — status codes, request/response structure
  3. Spring Data JPA and Hibernate — entity mapping, relationships
  4. SQL — complex queries, indexing, normalization
  5. Microservices basics (awareness level, not deep implementation)
  6. Git basics

### Round 4 — HR Interview
- Duration: 20–30 minutes
- Topics: Tell me about yourself, strengths/weaknesses, location preference, bond agreement, salary expectations

## Topic Weight Distribution (Mock Interview Configuration)

| Category | Weight | Topics |
|---|---|---|
| Java Core | 35% | OOP, Collections, Exception Handling, Generics, Streams, Memory Model |
| Spring Boot | 30% | Auto-configuration, REST, Security, Data JPA, Testing |
| Databases | 20% | SQL joins, indexing, JPA/Hibernate, transactions |
| Data Structures | 10% | Arrays, LinkedList, HashMap, basic sorting/searching |
| System Awareness | 5% | Microservices basics, Git, REST principles |

## Commonly Asked Questions (High Frequency)

### Java Core (must ask every session)
- Difference between == and .equals()
- HashMap vs ConcurrentHashMap
- What is the Collections hierarchy?
- Explain SOLID principles with examples
- What is the difference between abstract class and interface?

### Spring Boot (must ask every session)
- How does Spring Boot auto-configuration work?
- Explain the difference between @Component, @Service, @Repository, @Controller
- What is Spring Data JPA? How does it simplify database access?
- What is the difference between @RestController and @Controller?

### Databases (must ask every session)
- Write a SQL query to find the second highest salary
- Explain the difference between INNER JOIN and LEFT JOIN
- What is database normalization? What is 3NF?
- What is an index and when should you use one?

## Evaluation Criteria

Based on interview reports, Cognizant evaluators prioritize:
1. **Correctness over speed** — getting the answer right matters more than responding fast
2. **Explanation clarity** — can you explain WHY, not just WHAT
3. **Real-world awareness** — have you used these in actual projects?
4. **Communication** — structured, confident, professional

## Common Disqualifiers

- Unable to explain HashMap internals at all
- Cannot write basic SQL joins
- Unable to explain the difference between @Component variants
- No projects to demonstrate applied knowledge
- Very poor communication (cannot explain even simple concepts)

## Recommended Difficulty Curve

```
Question 1-3: Easy     (build confidence, assess baseline)
Question 4-7: Medium   (core evaluation zone)
Question 8-10: Hard    (differentiate candidates)
Follow-ups:   Adaptive (based on answer quality)
```
