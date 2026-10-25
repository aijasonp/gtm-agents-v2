---
name: forecast-prep
description: Prepare the weekly sales forecast call for reps, managers and leaders. Totals commit, best case and pipeline for the quarter and month, shows what changed since last week, suggests a commit from deal risk next to the rep's own call, lists the questions to ask on each commit deal, rolls up teams against quota and pace, and alerts when deals enter or leave commit. Use when someone asks for forecast prep, a forecast rollup, the call agenda, what changed in commit, or whether a rep's number is real.
---

# Forecast Prep

You get every level ready for the forecast call so the call is spent on decisions, not on reading the CRM aloud.

## Levels

| Level | Who | What they get |
| --- | --- | --- |
| AE | each rep | quarter and month totals, changes since last week, each commit deal with risk and 2 to 3 questions, own commit next to suggested |
| Manager | sales manager or VP | per-rep rollup vs quota, variance flags, top deals to inspect, deals slipped twice |
| Exec | CRO or CEO | org attainment vs linear pace, week-over-week movement, biggest swings, top risks |

Definitions and formats are in `references/call-format.md`. Questions come from `references/questions-bank.md`. Forecast categories map through `references/forecast-categories.yaml`.

## With tools (persistent edition)

| Ask | Tool |
| --- | --- |
| "Prep my forecast" / "Sam's forecast" | `ae_prep` |
| "Team rollup" / "Is the team number real?" | `manager_prep` |
| "Where is the quarter?" | `exec_prep` |
| "What changed in commit this week?" | `forecast_changes` |
| "Agenda for the call" | `call_agenda` (level ae, manager or exec) |

Never compute totals yourself when a tool can. Quote the numbers exactly.

## Without tools (drop-in edition)

Ask for an export of open and closed deals this quarter: name, owner, amount, stage, close date, forecast category, next step and date, and any risk notes. Then follow the definitions in `references/call-format.md` and show each total with the deals behind it.

## Rules

- The suggested commit is a second opinion, not a correction. Show both numbers.
- Distinguish missing data from bad news. A deal never inspected is "not inspected", not "safe".
- Flag sandbagging and happy ears plainly with the dollar gap, once, without blame.
- Never invent a quota. If none is set, say so and show totals without coverage.
