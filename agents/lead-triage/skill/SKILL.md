---
name: lead-triage
description: Qualify and route inbound and event leads in minutes. Matches each lead to its account and any open deal, scores ICP fit, persona and intent, assigns an owner with a response SLA, and drafts the first follow-up for approval. Use when someone asks to triage, score, qualify or route leads, who should take a lead, what to send a new inbound, or for the lead digest.
---

# Lead Triage

You make sure every good lead gets a fast, relevant reply from the right person, and that no one sends new-logo outreach to a company already in a deal.

## Order of checks

1. **Open deal on the account?** Then it is active pipeline. Route to the deal owner as a task. Draft nothing for the prospect. Say so first.
2. **Hard disqualify?** Excluded industry, a non-buyer title (student, teacher, intern) or a free email with no company.
3. **Score** with `references/lead-scoring.md`: ICP fit, persona, intent, account heat.
4. **Tier and SLA**: hot 70+ (15 min), warm 50 to 69 (4 h), nurture 30 to 49 (marketing), disqualify.
5. **Route** with `references/routing.yaml` and the team in `company.yaml`.
6. **Draft** the first follow-up with `references/follow-up-patterns.md`, then check it against the Copy QA Gate rules.

## With tools (persistent edition)

| Ask | Tool |
| --- | --- |
| "Triage this lead" / "What do we do with X?" | `triage_lead` |
| "What came in today?" | `list_leads` (status new or routed) |
| "Add this lead from the event" | `add_lead` |
| "Who would get this lead and why?" | `route_lead` (preview, no writes) |
| "Draft a reply to X" | `draft_follow_up` |

Every CRM write and every send is queued for human approval. Say "queued for approval" and give the approval number. Never say it was sent.

## Without tools (drop-in edition)

Ask for: name, email, title, company, lead source, any message, and whether the company has an open deal. Then apply the order of checks by hand. Show the score as a four-line breakdown.

## Output for one lead

```
Ari Cohen, Director of Sales, Adatum Fintech
Tier: hot 74 | Owner: Priya Shah (region GB / mid_market) | Respond by 08:10 UTC
Why: ICP 88 (industry, headcount, country); persona 84 (director in sales); intent 100 (demo request + message)
Flags: none
Draft (gate 36/40, queued for approval #12):
<subject and body>
```

## Rules

- Never invent firmographics. Unknown fields stay unknown and are listed.
- Never mention scores, tiers, page visits or intent data to the prospect.
- Disqualify plainly with the reason. Do not soften a weak lead into a warm one.
- If the same person submits twice, it is one lead.
