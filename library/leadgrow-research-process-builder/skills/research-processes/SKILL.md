---
name: research-processes
description: Step-by-step web research recipes for one company at a time (profile, news, funding, hiring, competitors, reviews, complaints, leadership by level, portfolio size). Use when researching a prospect, account or competitor before outreach, a meeting or a deal review.
---

# Research processes

Each file in this folder is one research recipe from the upstream research-process-builder project. A recipe lists its inputs, the searches to run in order, when to stop, and the exact output format.

## How to run one
1. Pick the recipe that answers the question (table below).
2. Fill its inputs (company name, domain, and anything else it asks for).
3. Run each step in order with your web search tool. Stop when the recipe's stop condition is met.
4. Return the output exactly in the recipe's format. If a fact cannot be found, say so; never guess a date, number or name.

The same files work as a Clay enrichment prompt: paste the recipe as the system prompt and map its inputs to table columns.

## Recipes
| Question | File |
| --- | --- |
| What is this company (size, HQ, funding)? | `find-profiles.md` |
| What happened there recently? | `find-news.md`, `find-pr-releases.md` |
| Did they raise money? | `find-funding.md` |
| Are they hiring, and for what? | `find-hiring.md`, `find-job-role-insights.md` |
| Are they investing in growth? | `find-growth-signals.md` |
| Who do they compete with? | `find-competitors.md` |
| What do customers and employees say? | `find-reviews.md`, `find-negativity.md` |
| Who leads the company? | `find-founders.md`, `find-c-suite.md` |
| Who are the VPs, directors and department heads? | `find-vp-leadership.md`, `find-directors.md`, `find-department-heads.md` |
| Who owns HR, finance, legal or technical areas? | `find-specialist-roles.md` |
| Where do their people show up publicly? | `find-people-creative.md` |
| How many portfolio companies does this firm hold? | `find-portfolio-companies.md` |
