# Checks

Every check returns ok, warn or fail. The overall status is the worst one.

| Check | Warn | Fail |
| --- | --- | --- |
| Job cadence (per scheduled job) | never run, or one scheduled run missed | no successful run for two or more intervals |
| Job failures (per scheduled job) | last run failed | last 3 runs failed |
| Stuck runs | a run still "running" after 60 minutes | |
| Approvals executing | | an action stuck in "executing" over 15 minutes (it may or may not have gone out) |
| Approvals approved, not run | approved over 2 hours ago and not executed | |
| Approval backlog | requests pending over 24 hours | |
| Handoffs failed | | any handoff marked failed after 3 attempts |
| Handoffs waiting | pending over 6 hours | |
| Budget pauses | | any agent paused on budget |
| Token spend | 80% of an agent's daily budget used | budget used up |
| Copy gate failures | 30% or more of an agent's drafts failed the gate this week (5+ drafts) | |
| Agent load errors | | an agent folder failed to load |

## Alerting

- Slack gets a message only when a check turns warn or fail, changes status, or recovers.
- The daily summary lists every non-ok check and the run counts for the last 24 hours.
- Ops Monitor uses no model calls.
