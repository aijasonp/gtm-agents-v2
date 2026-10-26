# Cadence rules

## The promise

Every contact in an active motion holds one next touch with a due time. A touch nobody made is never silent: it escalates.

## Motions and how they start

| Motion | Starts when | First step drafted by |
| --- | --- | --- |
| `post_meeting` | An external meeting with buyer attendees, on an open deal or a known account | Seller Follow-Up (the recap) |
| `event_attended` | Event Campaigns imports an attendee | Event Campaigns |
| `event_missed` | A registrant did not attend | Event Campaigns |
| `teed_up` | An engagement trigger hands someone to the AE | The AE, by hand |
| `proposal_out` | A proposal is marked sent | Follow-Through |

A newer motion replaces an older one for the same person, so nobody is in two cadences at once.

## When a step counts as done

The first of these after the step opened:

- An email to the person was sent (sequencer event).
- A draft for the contact was marked sent.
- A task for the contact was closed.
- For a step a peer agent drafts (recap, event follow-up): the AE confirmed that draft.
- For deal motions: new deal activity in the CRM.
- The AE logged a touch (`log_touch`): a call, a LinkedIn message, a hallway chat.

## Who drafts

- `follow-through`: drafted from facts only (the last call, the deal's next step, a sayable why-now line), through the Copy QA Gate, `draft_ahead_hours` before it is due, and queued as one `pipeline_email` approval for the owner. A draft that fails the gate is not queued: the AE writes that touch and the clock still runs.
- A peer agent id: that agent drafts it. This agent only checks it happened.
- `ae`: a manual touch. This agent only checks it happened.

If the AE rejects a draft, the AE owns that step. No second draft is queued.

## What stops a motion

`stop_on` in each motion: a reply (Reply Desk owns it), a new meeting (a new `post_meeting` starts), a closed deal, or an opt-out.

## Escalation

A step past due by `grace_hours` business hours, or a draft the AE has not confirmed within `approval_sla_hours`, runs the `escalation` ladder: the owner first, then the manager (`team.manager` in company.yaml). Each level fires once per step.

## The daily check

`follow_up_coverage` lists every open deal with nobody in a cadence and no dated next step, and every touch past due with no draft waiting. Weekdays at 8:00 it posts to Slack when there is anything to fix.
