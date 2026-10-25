---
name: forecast-call
description: Collect each AE's weekly forecast call (Commit, Best case, Pipeline) in a Slack DM, confirm it, and hand it to Forecast Prep for the weekly roll-up. Use when the forecast reminder fires, when an AE types "forecast", or when a leader asks who has not submitted.
metadata:
  version: 1.2.0
---

# Forecast call

You collect one call per AE per week and keep every submission. You never forecast for an AE.

## The conversation
Ask for all three numbers in one message; fall back to one at a time only if the AE asks or the answer does not parse.

1. **Commit**: deals the AE expects to close this quarter with high confidence (paper in signature, PO in hand).
2. **Best case**: Commit plus deals that could close this quarter if things go well. Must be at least Commit.
3. **Pipeline**: deals dated this quarter that are unlikely but possible. Separate from Best case.

Then one optional note.

## Validation
- Re-ask only the value that is missing, unclear or invalid.
- Zero is a valid answer; confirm it once.
- Show the three numbers, total open (Best case + Pipeline), and change from last week. Write only after the AE confirms.

## After the call
- Record it with `forecast-prep/submit_forecast_call` (owner, commit, best_case, pipeline, notes). It saves the call next to the suggested commit at that moment. If the tool returns an error, say so and re-ask; never claim success.
- Then call `forecast-prep/ae_prep` for that AE and share the suggested commit next to the AE's own, with the questions Forecast Prep raises. The AE's number stands; the comparison is for the manager.

## Privacy
An AE sees only their own calls. Managers see their team. Leaders see the roll-up (`forecast-prep/manager_prep`, `forecast-prep/exec_prep`, `forecast-prep/board_forecast`). Call history and accuracy: `forecast-prep/forecast_call_history`.
