# GTM Fleet on NetClaw

A full-cycle GTM engine for an AE-only sales team, from lead in to closed deal out, running on [NetClaw](https://netclaw.dev) (open source, Apache 2.0, self-hosted). There are no BDRs: agents do the research, routing, sequencing, prep and admin, and AEs approve every external action.

## Shape

**3 NetClaw instances, 10 subagents.** Each instance is its own Slack bot, with its own memory and its own skills. Each subagent loads only the skills for its job.

```
LEAD IN ──► PIPELINE ─────────────────────► DEALS ──────────────────────────► CLOSED
            Inbound Router                  Meeting Prep                       │
            Signal Scout ──► Prospecting    Call Intel                         ▼
                             Writer         Deal Manager                REVOPS
            Copy QA Gate ◄── (every draft)  Proposal & Close            Forecast & Hygiene
                                                                        Win/Loss Learning
                    ▲                                                          │
                    └────────── reweighted ICP + signal scoring ◄──────────────┘
```

| Instance | Slack channel | Subagents | Skills | Tools (MCP) |
| --- | --- | --- | --- | --- |
| pipeline | #gtm-pipeline | inbound-router, signal-scout, prospecting-writer, copy-qa-gate | 50 | signal-scout, copy-qa-gate, scoring-engine, crm, workspace, enrichment, sequencer |
| deals | #gtm-deals | meeting-prep, call-intel, deal-manager, proposal-close | 43 | scoring-engine, copy-qa-gate, crm, workspace, call-recorder |
| revops | #gtm-forecast | forecast-hygiene, win-loss-learning | 20 | signal-scout, scoring-engine, crm, workspace |

`fleet.yaml` is the source of truth: which agent loads which skills and tools. `build.py` turns it into deployable folders.

## What runs where

| Piece | Runs as | Source |
| --- | --- | --- |
| Signal Scout tools | `gtm serve-mcp signal-scout` (HTTP, port 8000) | `agents/signal-scout` |
| Copy QA Gate tools | `gtm serve-mcp copy-qa-gate` (HTTP, port 8001) | `agents/copy-qa-gate` |
| Scoring engine (JEV/CLEF) | `scoring_mcp.py` (HTTP, port 8010) | `library/outbound-engine` |
| CRM, workspace, enrichment, sequencer, call recorder | the customer's MCP servers | configured in `.env` |
| NetClaw instances | `ghcr.io/netclaw-dev/netclaw`, one container each | `dist/netclaw/<instance>` |

Deterministic work (scoring, routing, copy checks, forecast math) is a tool call. Prompts handle judgment and writing.

## Safety defaults

- Writes to the CRM, workspace and sequencer default to **Approval**: the AE clicks approve in Slack. Signal Scout's `push_to_crm` and `record_outcome` are always Approval.
- Scoring, QA, enrichment reads and call-recorder reads run on **Auto**.
- **Public** audience: no tools at all.
- After connecting the customer MCP servers, set their read-only tools (search, get) to Auto with `netclaw mcp permissions` so AEs are not asked to approve lookups.

## Schedules (cron in UTC; times shown are US Central daylight time)

| Instance | Reminder | When |
| --- | --- | --- |
| pipeline | daily-priority-list | weekdays 6:30 |
| pipeline | inbound-sla-sweep | every 30 min, weekdays 8:00 to 18:30 |
| pipeline | weekly-sequence-review | Mon 9:00 |
| deals | next-day-meeting-prep | Sun to Thu 17:00 |
| deals | weekly-deal-review | Mon 8:00 |
| deals | proposal-engagement | weekdays 10:00 |
| revops | forecast-reminder-wed / opener-thu / nudge-thu / rollup-fri | Wed 9:00, Thu 8:00, Thu 16:00, Fri 8:00 |
| revops | forecast-report-mon | Mon 8:00 |
| revops | daily-hygiene | weekdays 7:30 |
| revops | win-loss-weekly | Fri 15:00 |
| revops | icp-refresh-monthly | 1st of month 9:00 |

Webhooks: `inbound-lead` (pipeline), `call-completed` (deals), `deal-closed` (revops), HMAC-signed.

## Deploy

```bash
# 1. Product profile: what you sell, ICP, pain points, differentiators, competitors, proof points
mkdir -p config && cp library/outbound-engine/product_profile.example.yaml config/product_profile.yaml
# edit config/product_profile.yaml

# 2. Build the three instances (validates every skill and scans for banned identifiers)
python3 netclaw/build.py --profile config/product_profile.yaml

# 3. Settings
cp .env.netclaw.example .env    # merge with the existing gtm-agents .env

# 4. Run
make image
docker compose -f docker-compose.yml -f docker-compose.netclaw.yml up -d
./netclaw/install.sh
```

## What the host company's IT sets up

1. **A Linux VM** (x64 or ARM64, 4 vCPU and 16 GB RAM is plenty) with Docker and a persistent disk. Each NetClaw instance uses about 80 MB of RAM; Postgres and the tool servers are the bulk.
2. **Model access**: an API key for the main model (Anthropic, OpenAI or OpenRouter), and optionally an internal Ollama endpoint for the small model if data must stay in-house.
3. **Three Slack apps** in Socket Mode (bot token + app token each), named for example "GTM Pipeline", "GTM Deals", "GTM RevOps"; three channels; the bots invited to them; DMs enabled.
4. **MCP endpoints or API credentials** for the CRM (HubSpot or Salesforce), email and calendar (Google Workspace or M365), enrichment (Clay, Apollo, ZoomInfo), the sequencer (Smartlead, Outreach, Salesloft) and the call recorder (Gong, Fathom, Fireflies). Scoped service accounts; CRM writes only through approvals.
5. **Webhook ingress** for the three routes, through their reverse proxy, from the CRM and call recorder only. Signatures are verified on the raw body, so the proxy must not rewrite JSON.
6. **Security review** of where data lives: NetClaw memory is SQLite inside each container volume, agent state is in Postgres on the VM, secrets are in NetClaw's encrypted secrets file and `.env`.
7. **IP terms**: pre-existing code in this repo is licensed into the role, not assigned; work built on company time belongs to the company.

## Verify before go-live

Confirm these against the NetClaw version you install: provider `Type` strings for the model roles, the container's webhook port (set under `netclaw config`, network exposure), and how the webhook payload reaches the session. `install.sh` prints `netclaw mcp list` and `netclaw skill issues` for each instance.

## Keep it clean

`python3 netclaw/check_clean.py` scans the repo (and `build.py` scans every build) for former-employer and internal identifiers. `make clean-check` runs it; the build fails on any hit.
