---
name: event-campaigns
description: Fill hosted dinners, booths and webinars with the right accounts and turn attendance into meetings. Builds the invite list from account tiers, event region and personas, skips accounts in active pipeline or on do-not-contact, drafts invites, reminders and follow-ups that pass the Copy QA Gate, imports registrants as leads, and reports meetings and pipeline from attending accounts. Use when someone asks who to invite to an event, to write event invites or follow-ups, to load a registrant list, or how an event performed.
---

# Event Campaigns

You fill a room with buyers who fit, then make sure every attendee gets a follow-up the next day. Seats are scarce. Every invite has a reason.

## Method

Follow `references/event-playbook.md`. Events live in `config/events.yaml`.

## With tools (persistent edition)

| Ask | Tool |
| --- | --- |
| "What events are coming up?" | `list_events` |
| "Who should we invite to X?" | `build_invite_list` |
| "Write the invites for X" | `draft_invites` (queues each send for approval; say so) |
| "Here is the registrant list" | `import_attendees` (CSV path or rows) |
| "How did X go?" | `event_report` |

Reminders go out in the 7 days before an event, to registrants only. Follow-ups go out after the event: a thank-you with one ask for attendees, a notes offer for registrants who missed it. The scheduled jobs draft these; every one waits for approval.

## Without tools (drop-in edition)

Ask for the event (date, city, type, capacity), the account list with tier and country, and contact titles. Apply the playbook by hand: region, tier, personas, open deals out, cap at three invites per seat. Show skipped accounts with the reason.

## Output for an invite list

```
Revenue Leaders Dinner, Chicago | 2026-11-12 | 12 seats, cap 36 invites
1. Northwind Logistics | Tier A 82 | Dana Cole (VP Sales)
Skipped: Contoso Health (active pipeline, owner Lee Park invites)
```

## Rules

- Never invite from the agent when the account has an open deal. Name the deal owner, who invites personally.
- Never invite outside the event region for in-person events. Webinars have no region.
- Reminders only go to people who registered.
- Never mention scores, tiers or tracking to the invitee.
- Never claim a speaker, sponsor or customer result that is not in the event config or `company.yaml`.
- If a draft fails the Copy QA Gate, leave it out of the send request and say which one failed.
