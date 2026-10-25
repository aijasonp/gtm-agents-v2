---
name: rep-brief
description: Bring the work to each sales rep. A daily brief per rep with the three things to do next, replies and hot leads to handle, top accounts with the reason to write now and who to contact, new signals, and pipeline gaps against quota. Plus a push-button workflow that researches an account, drafts the first touch and queues the email, CRM task and dialer call for the rep to approve. Use when a rep asks what to work on, who to call, for their brief, about their pipeline gap, or says "push-button" or "start outreach" on an account.
---

# Rep Brief

Reps should not hunt for work. You hand each rep a short list every morning and do the prep for the first touch, so an account executive can prospect without a BDR in between.

## The daily brief

Built per rep from data, in this order (see `references/brief-format.md`):

1. **Do next:** three actions, ranked with `references/prioritization.md`.
2. **Replies** classified as positive, referral, objection or question.
3. **Hot and warm leads** routed to the rep and not yet answered.
4. **Top accounts:** the rep's accounts ranked by Signal Scout, each with a why-now line and up to two contacts. Accounts with an open deal show the deal, not contacts.
5. **New signals** since the last brief. Timing-only signals are counted, never quoted.
6. **Pipeline:** open pipeline against what is left of quota, the gap to the coverage target, deals with no or late next step, quiet deals and deals Deal Inspection flagged.

A rep with nothing new since the last brief gets no message.

## The push-button workflow

One request ("push-button Fourth Coffee", optionally with a contact) does all of this (see `references/push-button-workflow.md`):

1. **Check conflicts.** Refuse and say why if another rep owns an open deal, an inbound lead is in progress, the account or contact was contacted recently, or anyone is on the do-not-contact list.
2. **Research brief:** firmographics, ICP fit, Signal Scout tier, signals, open deals, contacts, recent calls, competitor and objection notes, and what this contact engaged with.
3. **Draft the first touch** from those facts. It must pass the Copy QA Gate.
4. **Queue together for approval:** the email (sequence enrollment), a CRM follow-up task with a three-line call script, and a dialer call when the contact has a phone number. If the draft fails the gate, nothing is queued.

## With tools (persistent edition)

| Ask | Tool |
| --- | --- |
| "What should I work on today?" | `my_brief` |
| "Push-button Fourth Coffee" / "Start outreach to Rosa" | `push_button` |
| "My top accounts" | `top_accounts` |
| "Where is my pipeline short?" | `pipeline_gaps` |
| "Anything new since this morning?" | `whats_new` |

Say "queued for approval" with the approval numbers. Never say anything was sent.

## Without tools (drop-in edition)

Ask the rep for their account list with recent events, open deals with stage, amount and next step, and their quota. Build the brief in the format in `references/brief-format.md`. For push-button, ask for the account and contact, run the conflict checks by hand, write the research brief and draft the email.

## Rules

- Never quote a timing-only signal (page visits, intent data, reactions, follows, views) to a prospect.
- A line about a person (new role, a comment they wrote) is only said to that person.
- Never invent a fact, number or customer. Missing data is shown as missing.
- Never draft outreach into an account another rep is working or where an inbound lead is in progress.
- Every send, task and dialer call waits for the rep's approval.
