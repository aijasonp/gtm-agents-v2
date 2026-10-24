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
2. `cp .env.example .env` and fill in: `POSTGRES_PASSWORD`, one model key, `HUBSPOT_TOKEN` (or Salesforce), `SLACK_WEBHOOK_URL`. Keys stay in this file or the customer's secrets manager; they are never logged.
3. Put `license.json` next to `docker-compose.yml`.
4. Edit `agents/signal-scout/skill/references/icp.yaml` to the customer's ICP.
5. `docker compose up -d`
6. `docker compose exec agents gtm selftest` and confirm every check is ok.
7. First run: `docker compose exec agents gtm run signal-scout sync_accounts`, then `gtm run signal-scout daily_sweep`.
8. Review queued CRM updates: `gtm approvals signal-scout list`, then `approve <ids>` and `execute`.

### HubSpot private app scopes
`crm.objects.companies.read`, `crm.objects.companies.write`, `crm.objects.notes.write`. Create custom company properties `gtm_signal_score` (number), `gtm_signal_tier` (single-line text) and `gtm_signal_reasons` (multi-line text), or map other names in `agent.yaml > config.crm_fields`.

### Feeding signals
Drop CSV or JSON files into `data/signals/inbox/` (columns: `account_id, signal_type, observed_at, url, title, source, strength`). The daily sweep ingests and archives them. Valid `signal_type` values are in `skill/references/signal-taxonomy.yaml`. Enrichment-provider connectors write to the same inbox.

### Updates
`docker compose pull && docker compose up -d` with a valid license. Lapsed licenses keep running; updates and support pause.

### When something breaks
Run `gtm selftest` and send the output. It contains no keys or customer data.
