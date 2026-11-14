# Health method

## Customers
An account is a customer when its CRM record has `customer: true` or it has a won deal. `customer: false` overrides a won deal (churned or a one-time purchase).

Contract fields come from the account: `arr`, `seats`, `renewal_date`, `owner` (or `csm`). Missing pieces fall back to the latest won deal: its amount for ARR, its owner, and its close date plus `contract_months` for the renewal. The result says which source the renewal date came from.

## Usage
Usage rows are `account, metric, value, observed_at`, loaded from a CSV or JSON export (Snowflake, PostHog, product database) or added one at a time. Metric names are mapped through `metric_aliases`; unknown names are refused.

| Metric | Window math |
| --- | --- |
| active_users, core_actions, features_used, teams | average of observations in the last 30 days vs the 30 before |
| support_tickets, escalations | sum in each window |
| utilization | latest active_users / licensed seats |

A change needs data in both windows. One window alone gives no trend.

## Conversations
Meetings on the account in the last 90 days (summary and transcript) and the call insights Meeting Intelligence wrote (objections, competitor and pricing mentions, next steps, flags). Phrases match whole words. A phrase with a negation in the 20 characters before it is skipped. The sentence that matched is kept as the quote.

## People and news
Contacts with a champion or sponsor role (`role` field) marked `left_company: true` or `status: left` count as departed. Account signals from the last 60 days are split into risk and expansion types by `signals` in the rules file.

## Scores
Each driver adds its points once. Scores cap at 100. Drivers are listed highest points first, and the actions follow the same order, three at most.

## Write-back
Nothing is written to the CRM without approval. When an account's recommendation changes to save or expand, one `crm_task` for the owner is queued (due in 2 days for save, 5 for expand). The same recommendation the next day queues nothing.
