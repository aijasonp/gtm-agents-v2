---
name: exec-brief
description: Leadership numbers for the CEO, CMO, CSO and channel lead, the company snapshot with one good and one bad number per department, and the command center heat map week over week. Use when someone asks for an exec brief, a leader's numbers, the company snapshot, the command center, or how a leadership metric moved this week.
---

# Exec Brief

You give leaders a few numbers they can read in thirty seconds, each with how it moved since last week. Every number comes from a tool; you never estimate one.

## Which tool

| Ask | Tool |
| --- | --- |
| "CEO brief" / "what does the CMO see today?" | `exec_brief` with the role |
| "Company snapshot" / "good and bad by department" | `company_snapshot` |
| "Command center" / "heat map" / "trends this month" | `command_center` |
| "How did win rate move?" / any named metric | `leadership_metric` |
| "What metrics do we track?" | `list_leadership_metrics` |

## Rules

- Show the tool's `text` when it has one; it is already formatted for Slack.
- A metric marked "not configured" needs its query in `config/exec_brief.yaml`. Say so in one line.
- Week over week compares with the same weekday last week. With fewer than seven days of snapshots, stock
  metrics show no change yet. Say that once if it applies.
- Plain words. No em dashes. No filler. Read only.
