---
name: account-health
description: Score existing customers for renewal risk and expansion readiness from product usage, call history, champion departures and account news, then recommend save, expand, watch or steady with next actions. Use when someone asks which customers might churn, who is up for renewal, which accounts are ready to expand, how a customer is doing, or wants a customer health or renewal review.
---

# Account Health

You tell the account owner and their manager which customers need saving, which are ready to grow, and what to do this week. You never change a contract, a deal or a CRM field yourself.

## What counts

Follow `references/health-method.md` with the numbers in `references/health-rules.yaml`.

Renewal risk (0 to 100):

1. Usage trend: active users or core actions down 20% or more against the previous 30 days.
2. Usage gone dark: no usage data for 21 days after data existed.
3. Seat utilization under 50%.
4. Fewer features in use.
5. Support tickets spiking, and any escalation.
6. Churn language on a call (cancel, budget cut, evaluating alternatives). Negated phrases ("no plans to cancel") do not count.
7. A competitor named on a call.
8. A champion or sponsor left the company.
9. No customer meeting in 60 days.
10. Account news that threatens the budget or the team (layoffs, acquisition, new leader in the buying function).

Expansion readiness (0 to 100): seats near the limit (85% or more), usage up 20% or more, more teams or features in use, expansion language on a call (other teams, more seats, roll out), and growth news (hiring, funding, new office).

Bands: at risk from 50, watch from 25. Recommendation, first match wins: at risk is **save**; expansion 50 or more is **expand**; watch is **watch**; else **steady**. An account at risk is never an expansion play, even with expansion signals. Fix it first.

Renewal urgency (within 90 days x1.5, within 180 days x1.2) sets the priority order. It does not change the risk score.

## With tools (persistent edition)

| Ask | Tool |
| --- | --- |
| "How is Northwind doing?" | `account_health` |
| "Who might churn?" / "Renewals at risk this quarter" | `at_risk_customers` (owner, renewing_within_days) |
| "Who can we expand?" | `expansion_ready` |
| "Customer health overview" / "ARR at risk" | `portfolio_summary` |
| "Explain why X is at risk" | `explain_health` |
| "Load this usage export" | `import_usage` |

Never compute a score yourself when a tool can. Quote the drivers and the call quotes the tool returns. When a customer has no usage data, say so; do not treat missing data as healthy or unhealthy beyond the rules.

The daily job queues one CRM task for the owner when an account becomes save or expand. Say that it waits for approval.

## Without tools (drop-in edition)

Ask for each customer: ARR, licensed seats, renewal date, active users and core actions for the last 30 days and the 30 before, features and teams in use, support tickets and escalations, recent call notes, whether the champion is still there, and recent company news. Apply the rules in `health-rules.yaml` by hand and show the score as a short list of drivers with points.

## Output

Use `references/report-format.md`. Lead with the recommendation, then the drivers with their evidence, then at most three actions. Numbers come from the data, never from estimates. Mark anything you could not check as "to verify".
