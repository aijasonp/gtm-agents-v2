---
name: stack-audit
description: Audit and rationalize the GTM tool stack. Computes utilization, cost per active seat and overlap from the tool inventory, maps which capabilities the agent pack covers, watches notice deadlines before auto-renewal, recommends cut, downsize, consolidate or keep with evidence and the condition to meet first, runs a side-by-side of a tool's top accounts against agent signals, and drafts the tool-cut memo. Use when someone asks what tools to cut, what renews soon, where the stack overlaps, how much could be saved, or for a tool-cut memo.
---

# Stack Audit

You turn tool spend into decisions that hold up in a budget review. Every recommendation has numbers, a condition and a deadline.

## Method

Follow `references/audit-method.md`. Capability coverage by the agents is in `references/capability-map.yaml`. Memos follow `references/memo-format.md`.

## With tools (persistent edition)

| Ask | Tool |
| --- | --- |
| "What does our stack cost and who uses it?" | `stack_summary` |
| "Where do tools overlap?" | `overlap_matrix` |
| "What renews soon?" | `renewal_calendar` (days ahead) |
| "How much could we save?" | `savings_scenarios` |
| "Do the agents find the same accounts as tool X?" | `compare_lists` (tool, file of its top accounts) |
| "Write the memo for tool X" | `cut_memo` |

## Without tools (drop-in edition)

Ask for the inventory: tool, capabilities, seats purchased, seats active in 30 days, logins in 30 and 90 days, annual cost, renewal date, notice days. Apply the method by hand and show the formula behind each number.

## Rules

- Never invent a cost, seat count or renewal date. Unknown stays unknown and out of totals.
- Never recommend cutting on low usage alone. State the capability coverage and the condition first.
- A tool the agents depend on (sequencer, dialer, call recorder, one contact data source, marketing automation) stays.
- Lead with the notice deadline when it is inside 60 days. A missed deadline costs a full year.
