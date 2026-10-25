# Running the agents

No agent shell is required. The `gtm` runtime in this repo is the shell: it schedules every agent's jobs, holds memory in Postgres, serves the chat assistant (terminal, Slack, MCP), takes intake over HTTP, and routes model calls to whatever models you point it at. A plain Linux VM with Docker is enough; no one-click agent host is needed.

## 1. Test on a laptop first (10 minutes, no keys)

```bash
git clone <repo> && cd gtm-agents
pip install -e ".[mcp,dev]"
make test        # unit and integration tests
make evals       # golden cases for every agent (deterministic, no model)
make demo        # every agent runs once on fictional sample data, in pipeline order
```

`make demo` prints each agent's Slack output, the approval queue, the handoffs between agents and the drafts. Then look closer:

```bash
export DATABASE_URL=sqlite:///demo.db PYTHONPATH=core:.
python3 -m gtm_core.cli drafts --full
python3 -m gtm_core.cli approvals lead-triage list --all-agents
python3 -m gtm_core.cli call rep-brief my_brief --args '{"owner": "Sam Rivera"}'
```

Add a model key (or an open-weight endpoint, below) and run `gtm models`, then `gtm ask "who should Sam call today?"` to use the assistant.

## 2. Pick your models

Two tiers, routed independently:

| Tier | Used for | Good fits |
| --- | --- | --- |
| `cheap` | classification, extraction, reply sorting, chat routing | Claude Haiku, or an open-weight 8B to 32B instruct model |
| `frontier` | first-touch copy, recaps, briefs, battlecards | Claude Sonnet, or a strong open-weight model (70B class or a large MoE) |

Three ways to run each tier:

1. **Frontier API**: set `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY`). Nothing else to host.
2. **Hosted open-weight API** (no GPU to manage): any OpenAI-compatible provider. Set `GTM_CHEAP_BASE_URL`, `GTM_CHEAP_API_KEY`, `GTM_MODEL_CHEAP` to the provider's model name.
3. **Self-hosted open-weight on the VM**:
   - CPU or small GPU: `docker compose --profile local-model up -d ollama`, then `docker compose exec ollama ollama pull <model>` and set `GTM_CHEAP_BASE_URL=http://ollama:11434/v1`.
   - GPU VM: `docker compose --profile gpu-model up -d vllm` with `VLLM_MODEL=<hf model id>`, then `GTM_*_BASE_URL=http://vllm:8000/v1`.

A common cost-saving mix: cheap tier on open-weight, frontier tier on Claude for anything a buyer reads. Every outbound draft still has to pass the Copy QA Gate, whichever model wrote it, and every agent falls back to templates if a model is down.

For the chat assistant on a smaller open-weight model, limit the tools it sees: `GTM_ASSISTANT_AGENTS=rep-brief,lead-triage,deal-inspection`. Use a model with tool calling (vLLM needs `--enable-auto-tool-choice` and a tool parser for the model family).

## 3. Stand up the VM

| Item | Minimum |
| --- | --- |
| VM | 2 vCPU, 4 GB RAM, 40 GB disk for the runtime and Postgres (API models). Add a GPU only if you self-host the frontier tier. |
| Network | Outbound HTTPS to your CRM, Slack, model endpoints. Inbound only if web forms post leads directly (otherwise keep it private and use Socket Mode for Slack). |
| Software | Docker and Docker Compose |

```bash
git clone <repo> && cd gtm-agents
cp .env.example .env          # keys, CRM token, Slack, sequencer, dialer, API tokens
# edit config/icp.yaml and config/company.yaml (who you sell to, what you sell, team, competitors)
docker compose up -d                         # Postgres, scheduler, intake/approvals API
docker compose --profile slack up -d         # optional: Slack chat bot
docker compose exec agents gtm selftest      # every check ok
docker compose exec agents gtm models        # both model tiers answer
docker compose exec agents gtm sync deal-inspection   # read accounts, contacts, deals from the CRM
```

## 4. Go live in shadow mode first

1. **Week 1, shadow:** let the scheduler run. Agents draft, score and queue approvals, but nobody executes them. Review `gtm drafts --full` and the Slack briefs with two or three reps.
2. **Week 2, approve by hand:** approve a handful of items per day (`gtm approvals <agent> approve <ids>` then `execute`, or `approve 12` in Slack for listed approvers).
3. **Week 3 onward:** widen to the team. Keep the approval queue; it is the control that makes the system safe to run unattended.

`ops-monitor` posts when a job misses its schedule, a handoff fails, an approval is stuck or a budget pauses an agent.

## 5. Day-to-day commands

| Need | Command |
| --- | --- |
| Is everything healthy? | `gtm selftest`, `gtm call ops-monitor health_report` |
| Run a job now | `gtm run <agent> <job>` |
| Ask anything | `gtm ask "..."`, `gtm assistant`, or mention the bot in Slack |
| Review and approve | `gtm approvals <agent> list --all-agents`, `approve`, `execute` |
| Spend | `gtm usage <agent>`; budgets per agent in `agent.yaml` |
| Connect Claude Desktop or ChatGPT to one agent's tools | `gtm serve-mcp <agent>` (config in `dist/<agent>/.../claude/<agent>-plugin/.mcp.json`) |
