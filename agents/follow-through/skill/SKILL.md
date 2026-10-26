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

## How the cadence works

Every contact in an active motion (after a meeting, an event, a tee-up or a proposal) holds one next touch with a due time, from `config/cadences.yaml`.

1. A step is done when the evidence shows the touch happened: an email sent, a draft marked sent, a task closed, the AE confirming a peer agent's draft, new deal activity, or a logged touch.
2. Steps this agent owns are drafted ahead of time from facts only, gated, and queued as one email for the AE to confirm.
3. Steps other agents draft (the recap, the event thank-you) are only checked.
4. A missed step, or a draft the AE has not confirmed, escalates to the owner, then the manager. Once per step.

Details: `references/cadence-rules.md`.

## With tools (persistent edition)

| Ask | Tool |
| --- | --- |
| "Is this person engaged?" / "Why was she teed up?" | `check_engagement` |
| "Run the triggers now" | `run_triggers` |
| "What do I need to act on?" / "What is overdue?" | `tee_ups`, `next_touches` |
| "I called him" / "She booked" | `resolve_tee_up`, `log_touch` |
| "Where does she stand?" | `cadence_status` |
| "Are there any follow-up gaps?" | `follow_up_coverage` |
| "Put him in the post-event cadence" | `start_motion` |
| "What are the rules?" | `explain_rules` |

## Without tools (drop-in edition)

Ask for the engagement export from the sequencer (email, event, time). Count human opens only: drop any open within a few seconds of the send. Apply the rules in `config/triggers.yaml` in order and list each person with the rule that matched and the action.

For follow-up, ask for open deals with their last touch and next step date, plus recent meetings and events. Apply `config/cadences.yaml` and list each person with the next touch, its due date, and anything already past due.

## Rules

- Opens and clicks are timing only. Never write "I saw you opened my email" or anything like it. The brief gives a sayable reason instead.
- A reply always goes to Reply Desk, never to a trigger.
- Opted out, bounced or do-not-contact: no action, ever.
- One tee-up per person inside the cooldown. Already teed up means no second task.
- Pausing automation runs at once because it only reduces contact. Every CRM write waits for approval.
- Change a threshold in `config/triggers.yaml` or a cadence in `config/cadences.yaml`, never in code or in a prompt.
- A follow-up draft uses only the facts given: the last call, the deal's next step, a sayable why-now line. Nothing invented.
- One pipeline email, one approval, confirmed by the owner. A rejected draft means the AE writes that touch.
