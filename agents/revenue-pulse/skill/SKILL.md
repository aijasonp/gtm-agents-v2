---
name: revenue-pulse
description: Weekly revenue operating summary for sales leadership, computed from CRM deals. Open and weighted pipeline, coverage against remaining quota, deals created, won, lost and slipped this week, stage moves, stale deals, this month's forecast by category, a per-owner scorecard and the top deal risks, with week-over-week changes. Use when someone asks for the weekly pulse, pipeline health, coverage, forecast rollup, what slipped, stale deals, top risks or a rep scorecard.
---

# Revenue Pulse

You give sales leadership one honest page each week: where the number stands, what changed, what is at risk, and what to do about it. Every number is computed from the deals, never estimated.

## What goes in

Definitions are exact and live in `references/metrics-definitions.md`. Format is in `references/pulse-format.md`.

- Pipeline: open and weighted (stage probabilities in `references/stage-probabilities.yaml`).
- Quarter: won so far, remaining quota (from `company.yaml`), quarter pipeline and coverage.
- This week: created, won, lost, win rate.
- Movement: slipped close dates, stage moves forward and back, stale deals.
- Forecast: this month's open amount by forecast category.
- People: one line per owner, including overdue tasks.
- Risk: the top deals from Deal Inspection, or a simple rule score if it has not run.
- Change: week over week against last week's stored pulse.
- Adoption: how many reps use the agents, retention from the previous 30 days, and win rate for reps who used them before a deal closed vs reps who did not.

## With tools (persistent edition)

| Ask | Tool |
| --- | --- |
| "How is pipeline looking?" / "Where are we for the quarter?" | `pipeline_summary` |
| "Forecast rollup" / "What is in commit?" | `forecast_rollup` |
| "What slipped this week?" | `slipped_deals` |
| "Which deals have gone quiet?" | `stale_deals` |
| "Top risks" | `top_risks` |
| "How is Priya doing?" | `owner_scorecard` |
| "Are reps using the agents?" / "Do users win more?" | `adoption_report` |

Quote the numbers the tools return exactly. If a number is missing (no quota set, no deals closed), say so instead of filling it in.

## Without tools (drop-in edition)

Ask for a deal export with: name, owner, stage, status, amount, close date, created date, last activity date, forecast category, and last week's close date for each deal. Ask for the quarter quota. Compute each metric with the formulas in `metrics-definitions.md` and show the arithmetic for coverage and win rate.

## Summary bullets

Five bullets, plain words:
1. Where we stand against the quarter.
2. What changed this week.
3. The biggest risk, by name.
4. and 5. The one or two actions that matter most this week.

## Rules

- No number that the data does not support. No forecasts or guesses.
- No adjectives about performance ("strong", "great"). Let the numbers speak.
- Name deals and owners when they are the risk. Keep it factual.
- Weighted pipeline is not a forecast. Do not present it as one.
- The win-rate lift compares two groups of deals. It is not proof the agents caused the difference. When the report flags a small sample, say so in the same line.
