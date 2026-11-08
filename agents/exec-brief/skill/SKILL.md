---
name: exec-brief
description: Daily pipeline-critical brief for each executive. Five numbers each for the CEO, CSO, CMO and VP Channel and Partnerships, colored against target or pace, with the deals behind any red number. A company snapshot with the best and worst number for Sales, Marketing, Partners and Customer Success, and a leadership command center that heat-maps every metric week over week. Use when someone asks for the exec brief, the CEO numbers, today's snapshot, how a team is trending, what is red today, or the command center.
---

# Exec Brief

Executives get five numbers a day, not a dashboard. Each number says where it stands against target or pace, what changed since yesterday, and, when it is red, which deals or accounts are behind it. Every number is computed from warehouse rows, never estimated.

## What goes out each weekday morning

| Who | Where | What |
| --- | --- | --- |
| CEO | DM | Bookings QTD, won + commit vs plan, coverage for the rest of the quarter, pipeline created QTD, renewal ARR at risk |
| CSO | DM | Bookings QTD, commit this quarter, pipeline that slipped out of the quarter since the last run, late-stage deals gone quiet, win rate QTD |
| CMO | DM | MQLs month to date, MQL to SQL (90 days), marketing-sourced pipeline QTD, marketing share of new pipeline, speed to lead |
| VP Channel and Partnerships | DM | Partner-sourced pipeline QTD, partner-sourced bookings QTD, new deal registrations (7 days), partner share of open pipeline, partners sourcing pipeline (90 days) |
| Everyone | Shared channel | Best and worst number per team, a six-week heat strip for those numbers, link to the command center |
| Leadership | Command center page | Every metric by team, last eight weeks, heat-mapped with week-over-week change |

Each executive's five metrics are set in `config/exec_brief.yaml > briefs`. Definitions are exact and live in `references/metric-definitions.md`. Card layout is in `references/card-format.md`.

## Colors

- Green: on or ahead of target, or of pace for quarter and month targets (target times share of the period elapsed).
- Yellow: within 10% of target or pace.
- Red: more than 10% behind.
- No color: no target set and no earlier value to compare.

The company snapshot ranks every metric with a target or an earlier value, per team, and shows the furthest ahead and the furthest behind.

## With tools (persistent edition)

| Ask | Tool |
| --- | --- |
| "What are the CEO's numbers today?" / "Show me the CMO metrics" | `exec_metrics` with role |
| "Preview the CSO brief" | `exec_brief_preview` |
| "Best and worst by team" / "Company snapshot" | `company_snapshot` |
| "How has partner pipeline trended?" / "Heat map" | `command_center` |

Quote the numbers the tools return exactly. If a number is n/a (no target, no rows), say so instead of filling it in.

## Without tools (drop-in edition)

Ask for three exports: opportunities (id, name, owner, status, amount, close date, created date, last activity date, forecast category, source, partner, type), MQLs (MQL date, SQL date, first touch date) and renewals (account, ARR, renewal date, status, renewed ARR, health). Ask for the plan numbers. Compute each metric with the formulas in `metric-definitions.md` and show the arithmetic for pace and coverage.

## The one sentence

Each brief opens with one sentence: the single thing to act on today and why, then the strongest number. Use only the numbers on the card, formatted as shown. If the sentence carries any number that is not on the card, the template sentence is used instead.

## Never

- Never estimate a missing number or a target.
- Never add a sixth metric to an executive's brief; change the config instead.
- Never send a brief to anyone outside `recipients`; the company snapshot goes only to the configured channel.
