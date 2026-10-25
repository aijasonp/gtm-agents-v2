# Lead scoring method

A lead score is 0 to 100. Four parts, weighted per `routing.yaml`:

| Part | What it measures | How |
| --- | --- | --- |
| ICP fit | Is the company one we sell to? | Same ICP math as Signal Scout, from `icp.yaml`: industry, headcount, country, revenue, stack. Unknown company = 50 (neutral). Excluded industry = 0. |
| Persona | Is this person a buyer? | Title to seniority and function. 60 points if the function is a buyer function in `company.yaml`, plus 8 per seniority level (IC 8, manager 16, director 24, VP 32, C-level 40). |
| Intent | How strong was the action? | `source_intent` in `routing.yaml`. A written message on the form adds 10, capped at 100. |
| Heat | Is the account showing buying signals? | Latest Signal Scout heat for the account, 0 if none. |

## Hard rules (checked first)

1. **Active pipeline.** If the account has an open deal, the lead goes to the deal owner as a task. No new-logo outreach is drafted. The digest flags it at the top.
2. **Disqualify.** Excluded industry, a disqualified title (student, teacher, intern and similar) or a free email domain with no matching account and no company name.
3. **Free email with a company name** stays in play but loses the ICP part (scored neutral) and is flagged "verify company".

## Tiers and SLA

| Tier | Score | First response within |
| --- | --- | --- |
| Hot | 70+ | 15 minutes |
| Warm | 50 to 69 | 4 hours |
| Nurture | 30 to 49 | 2 days (marketing nurture, no rep task) |
| Disqualify | under 30 or hard rule | none |

## Routing

1. Open deal on the account: the deal owner.
2. Account already has an owner in the CRM: that owner.
3. Otherwise match `company.yaml` team owners by region (lead or account country) and segment (enterprise at or above `enterprise_employees`), then round-robin among the matches.
4. No match: round-robin across all owners.
