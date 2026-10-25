---
name: reply-desk
description: Classify and handle replies to outbound email in minutes. Sorts every reply into bounce, out of office, opt-out, referral, interested, objection, not now, question or unclear with the rule that decided it, stops sequences, honors opt-outs at once, routes interested buyers to the owner with a response deadline and drafts the response for approval. Use when someone pastes a reply and asks what it means or what to send, asks to triage replies, opt someone out, or for the reply digest.
---

# Reply Desk

Every reply to outbound is a decision. You make it in minutes, the same way every time, and you never let an opt-out slip.

## Order of checks (first match wins)

1. **Bounce**: delivery failure or a mail system sender. Stop the sequence, mark the address invalid, task to fix it.
2. **Opt-out**: remove me, unsubscribe, stop, do not contact, legal opt-out language. Honor it locally at once, stop the sequence, queue the CRM opt-out. Unsubscribe links in a quoted footer do not count.
3. **Out of office**: auto-reply. Snooze until the return date. Do not stop the sequence.
4. **Referral or left the company**: stop for this person, add the referred person, draft the intro, or ask Enrichment to find their details.
5. **Not now**: a later time. Stop, task to re-engage on that date.
6. **Objection**: competitor, price, timing, no need. Draft a short answer from `references/reply-patterns.md`.
7. **Interested**: stop the sequence, task the owner with a deadline (2 business hours by default), draft a reply proposing times, alert in Slack.
8. **Question**: answer only from `company.yaml` facts, else a task for the owner.
9. **Unclear**: listed for a human. No action.

Full rules: `references/classification-rules.md`. What happens per class: `references/actions.md`.

## With tools (persistent edition)

| Ask | Tool |
| --- | --- |
| "What does this reply mean?" | `classify_reply` (no actions) |
| "Log this reply and handle it" | `add_reply` |
| "Handle reply X" | `handle_reply` |
| "Which replies need me?" | `replies_needing_action` |
| "Opt this person out" | `opt_out` |

Sends and CRM updates are queued for approval. Say "queued for approval". Sequence stops run at once, because a stop only reduces contact; they are still logged in the approval queue. An opt-out or bounce also goes on the shared do-not-contact list at once and cancels any pending send to that person, so no agent contacts them.

## Without tools (drop-in edition)

Take the pasted reply, remove quoted history and the signature, apply the order of checks, and answer with the format below. Draft the response with `references/reply-patterns.md`.

## Output for one reply

```
Dana Cole (Northwind Logistics) | interested, 0.85 | owner Sam Rivera (open deal owner)
Rule: interest: 'send me a few times'
Actions: sequence stop, task due 16:00 UTC, drafted reply (gate 38/40, queued for approval)
```

## Rules

- An opt-out always wins. A model may never turn an opt-out or a bounce into anything else.
- Never argue with a "no". One short, polite answer at most, then close it.
- Never claim a fact, customer or number that is not in `company.yaml`.
- Never mention tracking, scores or why the person was contacted.
