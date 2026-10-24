# gtm-agents

Turnkey GTM agents a mid-market sales team installs in its own environment and runs on the model keys it already pays for. Each agent ships in two editions from one source:

| Edition | What the buyer gets | Runs where |
| --- | --- | --- |
| Drop-in | Skill pack for Claude, ChatGPT, Gemini or Copilot, plus an MCP server for the agent's tools | The buyer's chat workspace |
| Persistent | Docker runtime: scheduled jobs, Postgres memory, CRM write-back after approval, weekly learning | The buyer's VM, keys and database |

## Agents in this release

| Agent | Tier | Job | Tools | Jobs |
| --- | --- | --- | --- | --- |
| Signal Scout | A | Scores every account on ICP fit plus decayed, stacked buying signals; ranked daily brief to Slack; CRM updates queued for approval | score_account, list_priority_accounts, explain_score, add_signal, record_outcome, push_to_crm | sync_accounts, daily_sweep, weekly_reweight |
| Copy QA Gate | C | Scores outbound copy 0 to 40 (32 passes) and lists exactly what to fix | check_copy, check_batch | none |

## Full GTM fleet on NetClaw

`netclaw/` runs a full-cycle GTM engine for an AE-only team (lead in to closed deal out) on NetClaw: 3 instances, 10 subagents, each loading only its own skills from `library/`. Signal Scout, Copy QA Gate and the JEV/CLEF scoring engine are served to it over MCP. See [netclaw/README.md](netclaw/README.md).

| Folder | What is in it |
| --- | --- |
| `library/skills/` | Shared skill library (SKILL.md format) |
| `library/outbound-engine/` | Scoring engine + product profile, forecast alerts, rep feedback PRs |
| `library/references/` | Playbooks: copy rules, voice system, sayability matrix, brief template |
| `netclaw/` | Fleet definition, subagents, schedules, webhooks, build and install |

## Quick start (development)

```bash
pip install -e ".[mcp,dev]"
make test        # 18 tests
make evals       # golden cases for every agent (release gate)
make demo        # sample accounts and signals -> daily brief in the terminal
make compile     # drop-in packages in dist/<agent>/<version>/{claude,chatgpt,gemini,copilot}
```

## Customer install (persistent edition)

```bash
cp .env.example .env          # their keys, CRM token, Slack webhook
docker compose up -d          # Postgres + pgvector + scheduler
docker compose exec agents gtm selftest
```

Full steps: [docs/INSTALL.md](docs/INSTALL.md). How it fits together: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## The `gtm` command

| Command | Does |
| --- | --- |
| `gtm init` | Create tables |
| `gtm agents` | List installed agents |
| `gtm import signal-scout accounts|signals|outcomes <file>` | Load CSV or JSON (zero-integration path) |
| `gtm run <agent> <job>` | Run a job now |
| `gtm schedule` | Run all persistent-edition jobs on their cron |
| `gtm approvals <agent> list|approve|reject|execute` | Human approval queue for every CRM write |
| `gtm call <agent> <tool> --args '{...}'` | Call a tool from the shell |
| `gtm serve-mcp <agent> [--transport streamable-http --host 0.0.0.0 --port 8000]` | MCP server for Claude, ChatGPT, NetClaw or any MCP client |
| `gtm usage <agent>` / `gtm resume <agent>` | Token and spend budgets; resume after an auto-pause |
| `gtm selftest` | Shareable diagnostic report, no secrets |
| `gtm eval <agent>` | Golden-case evals |
| `gtm license keygen|issue|verify` | Offline Ed25519 license files |

## Rules for this repo

- Clean room: written fresh for this business. Nothing is copied from any employer system.
- Deterministic code for anything that must be right every time; prompts only for judgment and writing.
- No send and no live CRM write without an approved request.
- Every agent passes its evals before release; the Docker build runs them.
- No customer data in this repo. Sample data uses fictional companies.

Proprietary. All rights reserved.
