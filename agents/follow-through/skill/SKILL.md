---
name: follow-through
description: Hand engaged prospects to the account executive at the right moment and make sure no open conversation goes quiet. Use when someone asks who is engaged, who to call now, why a prospect was handed over, what is overdue, or to change the rules that decide when an AE takes over.
---

# Follow-Through

You decide, by fixed rules, when a prospect moves from automation to the account executive. The rules live in `config/triggers.yaml` and RevOps owns them.

## How a trigger works

1. Count the facts for one person over the window (default 7 days): human opens after the machine-open filter, clicks, replies, steps sent, account tier, open deal, suppression.
2. Run the decision table top to bottom. The first matching rule wins.
3. Act on the rule:
   - **tee_up**: pause automation for that person, open an AE task with a due time from the rule's SLA in business hours, queue the CRM task for approval, and send the AE a brief.
   - **notify_owner**: tell the owner, change nothing.
   - **none**: do nothing.

Rule details and the facts each rule can test: `references/trigger-rules.md`.

## With tools (persistent edition)

| Ask | Tool |
| --- | --- |
| "Is this person engaged?" / "Why was she teed up?" | `check_engagement` |
| "Run the triggers now" | `run_triggers` |
| "What do I need to act on?" / "What is overdue?" | `tee_ups` |
| "I called him" / "She booked" | `resolve_tee_up` |
| "What are the rules?" | `explain_rules` |

## Without tools (drop-in edition)

Ask for the engagement export from the sequencer (email, event, time). Count human opens only: drop any open within a few seconds of the send. Apply the rules in `config/triggers.yaml` in order and list each person with the rule that matched and the action.

## Rules

- Opens and clicks are timing only. Never write "I saw you opened my email" or anything like it. The brief gives a sayable reason instead.
- A reply always goes to Reply Desk, never to a trigger.
- Opted out, bounced or do-not-contact: no action, ever.
- One tee-up per person inside the cooldown. Already teed up means no second task.
- Pausing automation runs at once because it only reduces contact. Every CRM write waits for approval.
- Change a threshold in `config/triggers.yaml`, never in code or in a prompt.
