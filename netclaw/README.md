# NetClaw front end (optional)

The runtime in this repo already schedules every agent, holds memory, takes intake over HTTP and serves a chat assistant. This folder adds an optional conversational layer on [NetClaw](https://netclaw.dev) (open source, Apache 2.0, self-hosted): three Slack bots that talk to AEs and leaders and call the 25 runtime agents' tools over MCP.

Use it when the team wants to work in Slack with separate workspaces for pipeline, deals and forecasting. Skip it and the runtime still runs end to end.

## Shape: 3 instances, 13 subagents, AE-only team

```
LEAD IN ─► PIPELINE ──────────────────────► DEALS ─────────────────────► CLOSED
           Inbound Router (leads, replies)   Meeting Prep                    │
           Signal Scout ─► Prospecting       Call Intel                      ▼
                           Writer            Deal Manager              REVOPS
           Copy QA Gate ◄── every draft      Proposal & Close          Forecast & Hygiene
                                                                       Win/Loss Learning
```

| Instance | Subagents | Runtime agents it calls | Skills |
| --- | --- | --- | --- |
| pipeline | inbound-router, signal-scout, prospecting-writer, copy-qa-gate, events-content | lead-triage, reply-desk, enrichment, signal-scout, signal-sourcing, social-signals, rep-brief, icp-outbound, copy-qa-gate, event-campaigns, content-studio | 47 |
| deals | meeting-prep, call-intel, deal-manager, proposal-close, call-coach | sales-execution, meeting-intelligence, seller-follow-up, deal-inspection, product-marketing, copy-qa-gate, proposal-builder, call-coach | 34 |
| revops | forecast-hygiene, win-loss-learning, system-quality | forecast-prep, revenue-pulse, ops-monitor, product-marketing, signal-scout, stack-audit, crm-hygiene, quality-monitor, rep-feedback, icp-outbound | 18 |

`fleet.yaml` is the source of truth. Skills come from the licensed library (`lib:<name>`), the runtime agents' own skills (`agents/<id>/skill`), and two first-party skills in `shared/` (`gtm-playbooks`, `forecast-call`).

## Who does what

- **Runtime (`gtm schedule`)** computes on its schedule: triage every 15 minutes, scoring, inspection, forecast prep. Every write goes to its approval queue.
- **NetClaw** holds the conversations: morning briefs, forecast calls, deal reviews, prep on request. It calls the runtime's tools; it never writes to the CRM or sequencer directly.
- **Approvals:** runtime tools are Auto in NetClaw because they only compute, draft or queue. Tools that queue a customer-facing write (route a lead, handle a reply, opt out, MEDDPICC update, next step, CRM push, outcome) also ask in Slack. Public audience gets no tools.

## Schedules (cron in UTC; times shown are US Central daylight time)

| Instance | Reminder | When |
| --- | --- | --- |
| pipeline | daily-brief | weekdays 7:30 |
| pipeline | replies-digest | weekdays 11:00 and 16:00 |
| pipeline | weekly-target-list | Mon 9:00 |
| pipeline | engagement-weekly | Mon 8:30 |
| deals | next-day-meeting-prep | Sun to Thu 17:00 |
| deals | weekly-deal-review | Mon 8:00 |
| deals | daily-follow-ups | Tue to Fri 8:30 |
| revops | forecast reminder / call / nudge / leader prep | Wed 9:00, Thu 8:00, Thu 16:00, Fri 8:00 |
| revops | weekly-pulse-mon | Mon 8:00 |
| revops | daily-gtm-report | weekdays 7:30 |
| revops | board-forecast-fri | Fri 11:00 |
| revops | daily-health | daily 7:00 |
| revops | win-loss-weekly | Fri 15:00 |
| revops | icp-review-monthly | 1st of month 9:00 |

Inbound events (leads, replies, meetings, signals) go to the runtime's HTTP intake (`gtm serve-api`), not to NetClaw.

## Deploy

```bash
# 1. Company and ICP config (the runtime and the fleet both read these)
#    edit config/company.yaml and config/icp.yaml

# 2. Build the three instances (validates every skill and tool, scans for banned identifiers)
make fleet

# 3. Settings
#    .env from .env.example (runtime) plus .env.netclaw.example (NetClaw)

# 4. Run
make image
docker compose -f docker-compose.yml -f docker-compose.netclaw.yml up -d
./netclaw/install.sh
```

## What the host company's IT sets up

1. A Linux VM with Docker and a persistent disk (4 vCPU, 16 GB RAM is plenty).
2. Model access for NetClaw (Anthropic, OpenAI or OpenRouter key; optionally an internal Ollama endpoint for the small model). The runtime uses its own model settings from `.env`.
3. Three Slack apps in Socket Mode (bot and app token each), three channels, bots invited, DMs on.
4. The runtime's CRM, sequencer and Slack credentials, as described in `docs/INSTALL.md`.
5. A security review: NetClaw memory is SQLite in each container volume; runtime state is in Postgres on the VM.

## Verify before go-live

Confirm against the installed NetClaw version: model provider `Type` strings, the exact JSON shape of `Tools.AudienceProfiles`, and that Socket Mode connects. `install.sh` prints `netclaw mcp list` and `netclaw skill issues` per instance.

## Keep it clean

`make clean-check` scans the repo for former-employer and internal identifiers; `make fleet` scans every build. Both fail on any hit.
