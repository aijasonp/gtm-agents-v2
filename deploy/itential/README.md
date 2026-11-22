# Itential deployment notes

The runtime runs as is. These files layer Itential's choices on top without changing the shipped defaults.

| File | Set | Does |
| --- | --- | --- |
| `autonomy.overlay.yaml` | `GTM_AUTONOMY_OVERLAY=deploy/itential/autonomy.overlay.yaml` | Salesforce notes, tasks, deal notes, field and contact updates write with no approval. Emails to prospects and customers stay with the rep. |

## Settings to fill in

- Salesforce: `SALESFORCE_INSTANCE_URL`, `SALESFORCE_ACCESS_TOKEN`. First run `gtm sync opportunity-analyst --full`
  to pull every opportunity and its stage history; after that the 30-minute job pulls only changes. If the loss
  reason field is not auto-detected, set `SALESFORCE_LOSS_REASON_FIELD` (and `SALESFORCE_COMPETITOR_FIELD`).
- Models: `GTM_FRONTIER_PROVIDER=bedrock`, `GTM_BEDROCK_REGION` (see docs/DEPLOY-AWS.md).
- Snowflake: `SNOWFLAKE_*` with a SELECT-only role, then write the SQL for `mqls_7d`, `net_revenue_retention` and
  `logo_churn_qtd` in `config/exec_brief.yaml`.
- Exec briefs: name, email or Slack id for each leader under `roles` in `config/exec_brief.yaml`; adjust the
  `lead_source` values that count as marketing- and partner-sourced.
- Slack: `SLACK_APP_TOKEN`, `SLACK_BOT_TOKEN`, `GTM_SLACK_ALLOWED_USERS`, `GTM_SLACK_APPROVERS`.

## Note on cold outbound

Sends to a buyer can never be set to auto in this runtime (config/approvals.yaml `send_actions`). Cold outbound
copy is approved per send today. Running approved sequences unattended after one pre-launch review needs a
separate "approved template" mode; it is not built.
