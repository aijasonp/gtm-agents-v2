# Monitoring method

## What is checked

Prospect-facing drafts only: drafts that were scored by the Copy QA Gate when created. Internal documents (battlecards, proposals, tool-cut memos) are excluded in config.

## Sample

Per agent, drafts from the last 7 days sorted by id. Take every k-th draft, where k = drafts / sample size (default 5), so the sample is spread across the week and is the same on every run over the same data.

## Score

Each sampled draft is re-scored with the current Copy QA Gate (banned phrases, em dashes, sentence length, readability, length, exclamations, unverified claims, single ask; 32 of 40 passes).

A draft passes only when the gate passes and it has no unsourced claim. A claim is a money amount, a percentage, a multiplier (3x) or an hours amount (6 hours; meeting lengths like 15 minutes are asks, not claims), or a named customer after "customers like" or "teams such as". It is sourced when the same words appear in `company.yaml` proof points.

## Regression

For each agent, every gated draft in the last 7 days against every gated draft in the 28 days before:

- alert when the mean gate score drops more than 3 points
- alert when the pass rate drops more than 10 percentage points
- no comparison with fewer than 5 baseline drafts or 3 recent drafts

## Storage

One `quality` insight per agent per run with the sample stats, the change against baseline and any alerts.
