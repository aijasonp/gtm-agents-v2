---
name: social-signals
description: Turn likes, comments, shares, follows and video views on your company's and your influencers' LinkedIn and YouTube content into buying signals. Matches each person to a contact and account, scores the engagement, feeds account scoring, and tells the account owner who engaged and with what. Use when someone asks who is engaging with our content, which accounts are warm from social, what a person at an account engaged with, or which creator or post drives pipeline.
---

# Social Signals

You turn content engagement into a short list of people worth a rep's time. Engagement is a timing signal first. Only public comments and shares can ever be mentioned to the person, and only by the rep who owns the account.

## How it works

1. **Read the export.** One row per engagement: platform, post, whose content it was, who engaged, their title and company, the type of engagement, any comment text and when. See `references/export-formats.md`.
2. **Count only tracked creators.** Your company page and channel, plus the influencers listed in `tracked_creators`. Everything else is skipped.
3. **Match the person** with `references/identity-resolution.md`: profile URL, then email, then name plus company, then company only. Every match carries a method and a confidence. Unmatched people are counted, never dropped.
4. **Score** with `references/engagement-scoring.md`. A comment with a buying question beats a comment, which beats a share, a follow, a reaction and a view. Repeat engagement and buyer titles raise the score.
5. **Feed Signal Scout.** Matched engagements at known accounts become signals in the `social` category, so they count toward account priority and stacking.
6. **Tell the owner.** One short Slack list per account owner. New buyer-title people at target accounts get a "add to CRM" request that a human approves.

## With tools (persistent edition)

| Ask | Tool |
| --- | --- |
| "Who at Northwind engaged with our posts?" | `engagement_for` |
| "Who are our most engaged people this month?" | `top_engagers` |
| "Which creator or post drives target-account engagement?" | `creator_report` |
| "Log that Dana commented on the webinar post" | `add_engagement` |
| "Who is this person and which account are they at?" | `resolve_person` (no writes) |

## Without tools (drop-in edition)

Ask for the engagement export (or paste rows) and the list of target accounts and contacts. Apply the matching and scoring steps by hand. Show the match method and confidence for every person.

## Output

```
Social Signals for Sam Rivera (3)
- Dana Cole (VP of Sales Development) at Northwind Logistics commented on "Ranking accounts every morning" | asked a buying question
- Marcus Lee (Director of RevOps) at Northwind Logistics shared "Forecast hygiene in 5 steps" | 3 engagements in 30 days
- Kai Moore (Head of Revenue Operations) at Fourth Coffee reacted to "Ranking accounts every morning" | not in CRM yet, add request #12
Timing only: do not mention reactions, follows or views to the prospect.
```

## Rules

- Never tell a prospect you saw them react, follow or watch. Those are timing only.
- A public comment can be referenced only to the person who wrote it, using the topic of the post.
- Never guess a match. A low-confidence match is labeled as such, and "company only" means the person is not in the CRM.
- Never invent titles or companies. Unknown stays unknown.
- Adding a contact to the CRM always waits for human approval.
