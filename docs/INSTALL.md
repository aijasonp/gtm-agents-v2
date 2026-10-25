# Install guide (customer ops, about 15 minutes)

## Drop-in edition (Claude, ChatGPT, Gemini, Copilot)

| Platform | Steps |
| --- | --- |
| Claude | Settings > Capabilities > Skills > upload `claude/<agent>-skill.zip`. Team and Enterprise admins can deploy it org-wide. |
| Claude Code / Cowork | Install `claude/<agent>-plugin/` (skill plus MCP server config). |
| ChatGPT | New Custom GPT or Project: paste `chatgpt/instructions.md`, upload `chatgpt/knowledge/`. Persistent edition: add the MCP server in `chatgpt/mcp.json`. |
| Gemini | New Gem: paste `gemini/instructions.md`, upload `gemini/knowledge/`. |
| Copilot | Copilot Studio agent: paste `copilot/instructions.md`, add `copilot/knowledge/` as knowledge. |

## Persistent edition (Docker)

Requirements: a Linux VM with Docker (2 vCPU, 4 GB RAM), outbound HTTPS to the model provider, CRM and Slack.

1. Unpack the release and `cd` into it.
2. `cp .env.example .env` and fill in: `POSTGRES_PASSWORD`, one model key, `HUBSPOT_TOKEN` (or Salesforce), `SLACK_WEBHOOK_URL`, `GTM_API_TOKEN` (intake only, long random string), optionally `GTM_API_APPROVER_TOKEN` (a different string, for approving over HTTP), and the sequencer (`GTM_SEQUENCER=webhook` plus `GTM_SEQUENCER_WEBHOOK`, or `smartlead` plus `SMARTLEAD_API_KEY` and `SMARTLEAD_CAMPAIGN_ID`). Keys stay in this file or the customer's secrets manager; they are never logged.
3. Put `license.json` next to `docker-compose.yml`.
4. Edit `config/icp.yaml` (who you sell to) and `config/company.yaml` (what you sell) once; every agent reads them.
5. `docker compose up -d`
6. `docker compose exec agents gtm selftest` and confirm every check is ok.
7. First run: `docker compose exec agents gtm sync deal-inspection` (accounts, contacts, deals), then `gtm run signal-scout daily_sweep` and `gtm run deal-inspection weekly_inspection`.
8. Review the approval queue: `gtm approvals lead-triage list --all-agents`, then `gtm approvals <agent> approve <ids>` and `gtm approvals <agent> execute`. Or over HTTP with the approver token: `GET /v1/approvals`, `POST /v1/approvals/<id>/approve` (recorded under `GTM_API_APPROVER_NAME`), and `POST /v1/approvals/execute` if `GTM_API_ALLOW_EXECUTE=1`. The intake token can never see or approve anything.
9. From then on the scheduler runs every agent on its cron (see `docs/AGENTS.md`).

### HubSpot private app scopes
Read and write on companies, contacts and deals (`crm.objects.companies.*`, `crm.objects.contacts.*`, `crm.objects.deals.*`); notes and tasks are created through those objects.

Custom properties (or map other names in each agent's config):
- Company: `gtm_signal_score` (number), `gtm_signal_tier` (single-line text), `gtm_signal_reasons` (multi-line text). Map in `agents/signal-scout/agent.yaml > config.crm_fields`.
- Deal: `meddpicc_metrics`, `meddpicc_economic_buyer`, `meddpicc_decision_criteria`, `meddpicc_decision_process`, `meddpicc_paper_process`, `meddpicc_identify_pain`, `meddpicc_champion`, `meddpicc_competition` (multi-line text). Map in `agents/deal-inspection/skill/references/stage-rules.yaml > crm_fields`.
- Deal next step uses HubSpot's `hs_next_step`; map in `agents/seller-follow-up/agent.yaml > config.crm_fields`.

### Salesforce
Connected app with `api` scope. MEDDPICC fields are custom Opportunity fields; set their API names (for example `MEDDPICC_Champion__c`) in the same `crm_fields` maps.

### Deal stages
Map your CRM stage names to the six stage keys (discovery, qualification, evaluation, proposal, negotiation, commit) in `agents/deal-inspection/skill/references/stage-rules.yaml > stage_aliases`, and set stage probabilities in `agents/revenue-pulse/skill/references/stage-probabilities.yaml`.

### Feeding leads
Point web forms, event apps, Clay or Zapier at `POST /v1/leads` (JSON: `email, name, title, company, source, event, message`, optional `industry, employees, country`). Leads are triaged on arrival. Or drop CSV/JSON files into `data/leads/inbox/`. Lead sources and score weights are in `agents/lead-triage/skill/references/routing.yaml`; owners, regions and segments in `config/company.yaml > team`.

### Feeding call transcripts
Export transcripts from Zoom, Teams, Meet, Gong, Fathom or any notetaker as VTT, SRT, plain `Speaker: text` or JSON. Send them to `POST /v1/meetings` (`id, transcript, account_id, deal_id, title, started_at, owner`), or drop files in `data/meetings/inbox/` with an optional `<name>.meta.json` beside each. Put your reps' names in `config/company.yaml > team.rep_names` so talk ratio and coaching flags know which side is yours.

### Feeding signals
Send JSON to `POST /v1/signals`, or drop CSV or JSON files into `data/signals/inbox/` (columns: `account_id, signal_type, observed_at, url, title, source, strength`). The daily sweep ingests and archives them. Valid `signal_type` values are in `skill/references/signal-taxonomy.yaml`. Enrichment-provider connectors write to the same inbox.

### Feeding replies and social engagement
Point your sequencer's reply webhook (or an inbox rule) at `POST /v1/replies` (`from_email, subject, body, received_at, campaign`), or drop files in `data/replies/inbox/`. Export LinkedIn and YouTube engagement (page analytics, YouTube Studio or a scraper tool) to `data/engagement/inbox/` or `POST /v1/engagement`; formats are in `agents/social-signals/skill/references/export-formats.md`. List the creators to track (company page, executives, influencers) in `agents/social-signals/agent.yaml > config.tracked_creators`.

### Enrichment providers
Enable providers in `agents/enrichment/skill/references/providers.yaml`. Vendor HTTP examples are commented out; check each against the vendor's API docs before turning it on. Secrets are `${ENV_VAR}` references read at call time.

### Updates
`docker compose pull && docker compose up -d` with a valid license. Lapsed licenses keep running; updates and support pause.

### When something breaks
Run `gtm selftest` and send the output. It contains no keys or customer data.
