# Architecture

```
agents/<id>/                 one folder per sellable agent
  agent.yaml                 manifest: tier, editions, tools, jobs, budgets, config
  skill/SKILL.md             portable instructions (drop-in edition)
  skill/references/          taxonomy, ICP, method, formats: loaded by both editions
  engine.py                  agent-specific logic built on core
  tools.py                   MCP tools: TOOLS = {name: fn(ctx, ...)}
  jobs.py                    scheduled jobs and approval executors (persistent edition)
  evals/golden.yaml          release gate

core/gtm_core/               shared runtime, built once
  store.py                   SQLite (dev) or Postgres + pgvector (prod); customer-owned
  scoring/                   taxonomy, decay, stacking, ICP fit, account score, weekly reweight
  copy_gate.py               deterministic copy checks
  approvals.py               approval queue + executor registry
  budgets.py                 daily token and monthly spend caps, auto-pause, Slack alert
  gateway.py                 model router on the customer's keys (Anthropic or OpenAI-compatible)
  guardrails.py              hard step limits
  audit.py                   append-only audit log with secret masking
  connectors/                HubSpot, Salesforce, Slack (CRM writes only via approvals)
  mcp_server.py              exposes an agent's tools over MCP
  scheduler.py               cron for persistent jobs
  license.py                 offline signed license files with expiry
  selftest.py                diagnostic report

build/compile.py             agent -> Claude skill zip + plugin, ChatGPT, Gemini, Copilot packages
evals/runner.py              runs every agent's golden cases
```

## Signal Scout data flow

```
CRM (read) ----> sync_accounts ---> accounts
CSV/JSON inbox -> daily_sweep ingest -> signals (deduped by account+type+source+day)
                     |
                     v
       score = 0.4 x ICP fit + 0.6 x signal heat
       heat  = squash(sum(weight x strength x decay)) x stacking multiplier
                     |
          +----------+-----------+
          v                      v
   Slack daily brief     approvals: crm_update (pending)
                                 |
                       human approves -> executor writes CRM
outcomes ----> weekly_reweight ----> learned weights (bounded 0.25x to 3x base)
```

No model call is needed for scoring. Model spend starts with agents that write (First-Touch Writer, Research Brief), which route classification to the cheap model and drafting to the frontier model through `gateway.py`, under `budgets.py` caps.

## Adding an agent

1. `agents/<id>/agent.yaml` with tools and jobs.
2. `skill/SKILL.md` under 500 lines; references split by topic.
3. Deterministic logic in `core/` if other agents will reuse it, else `engine.py`.
4. `tools.py` with typed functions; writes go through `ctx.approvals.request`.
5. `evals/golden.yaml` and an evaluator in `evals/runner.py`.
6. `make test evals compile`.
