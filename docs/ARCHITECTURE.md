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
  connectors/                HubSpot, Salesforce (accounts, contacts, deals, notes, tasks), Slack,
                             sequencer (webhook or Smartlead); writes only via approvals
  executors.py               shared executors for approved actions (crm_task, deal_note, sequence_enroll...)
  handoffs.py                agent-to-agent work queue in the customer's database
  writer.py                  drafting on the customer's keys + Copy QA Gate rewrites + template fallback
  sync.py                    read-only CRM sync; deal snapshots for stage age and slips
  personas.py                title -> seniority and function
  transcripts.py             transcript parsing (VTT, SRT, plain, JSON) and rule-based call analysis
  meddpicc.py                MEDDPICC scoring and stage-aware gaps
  pipeline.py                deal timing and pipeline math
  profile.py                 shared config/icp.yaml and config/company.yaml
  api.py                     HTTP intake (leads, meetings, signals) and approvals
  mcp_server.py              exposes an agent's tools over MCP
  scheduler.py               cron for persistent jobs
  license.py                 offline signed license files with expiry
  selftest.py                diagnostic report

config/                      icp.yaml and company.yaml: edited once per customer, read by every agent
library/                     716 licensed playbooks (MIT); agents bundle the ones listed in agent.yaml `library:`
build/compile.py             agent -> Claude skill zip + plugin, ChatGPT, Gemini, Copilot packages, with playbooks and notices
scripts/demo_all.py          every agent once on the sample data, in pipeline order
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

See `docs/AGENTS.md` for the full multi-agent flow, handoffs and conflict rules.

No model call is needed for scoring. Model spend starts with agents that write (First-Touch Writer, Research Brief), which route classification to the cheap model and drafting to the frontier model through `gateway.py`, under `budgets.py` caps.

## Adding an agent

1. `agents/<id>/agent.yaml` with tools and jobs.
2. `skill/SKILL.md` under 500 lines; references split by topic.
3. Deterministic logic in `core/` if other agents will reuse it, else `engine.py`.
4. `tools.py` with typed functions; writes go through `ctx.approvals.request`.
5. `evals/golden.yaml` and `evals/evaluator.py` with `evaluate(manifest, spec, make_ctx)` (picked up by `evals/runner.py`).
6. Optional `library:` list of playbook folders under `library/`.
7. `make test evals compile`.
