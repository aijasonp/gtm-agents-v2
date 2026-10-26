# gtm-agents

A full-stack GTM agent pack a mid-market sales team installs in its own environment and runs on the model keys it already pays for, frontier or open-weight. Twenty-seven agents cover the revenue motion from first signal and event to signed proposal and the board forecast, on one runtime with a chat assistant (terminal and Slack), approvals for every write, and a licensed library of 716 sales and marketing playbooks. No agent host is required: see [docs/RUNNING.md](docs/RUNNING.md).

Every agent ships in two editions from one source:

| Edition | What the buyer gets | Runs where |
| --- | --- | --- |
| Drop-in | Skill pack for Claude, ChatGPT, Gemini or Copilot (instructions, references, bundled playbooks), plus an MCP server for the agent's tools | The buyer's chat workspace |
| Persistent | Docker runtime: scheduled jobs, Postgres memory, CRM and sequencer write-back after approval, HTTP intake, agent-to-agent handoffs | The buyer's VM, keys and database |

## The agents

| # | Agent | Tier | Job | Main schedule |
| --- | --- | --- | --- | --- |
| 1 | **Lead Triage** | A | Qualifies inbound and event leads in minutes: account and open-deal match, ICP, persona and intent score, owner and SLA, first follow-up drafted | every 15 min |
| 2 | **ICP Outbound** | A | Short ranked target list from ICP fit and fresh signals, conflicts removed (open deals, inbound in progress, recent touches), buyers picked, 3-step signal-led sequence drafted; the pain it leads with is picked from the judged ICP and learned open and reply rates | weekly list, daily drafts, weekly engagement report |
| 3 | **Seller Follow-Up** | A | One short daily list per rep (overdue tasks, missed next steps, quiet deals, late leads, calls with no recap); recap email, CRM note and tasks drafted after every call | daily, every 30 min |
| 4 | **Deal Inspection** | A | Every open deal checked for stage age, activity, slips, next step, MEDDPICC gaps by stage, coverage and fit; risk score with progress / fix / disqualify and the fixes | weekly, hourly evidence |
| 5 | **Meeting Intelligence** | A | Reads call transcripts: summary, pain, next steps, objections, competitors, pricing talk, MEDDPICC evidence, coaching flags; hands work to Follow-Up and Deal Inspection; pulls transcripts from Gong, Fireflies or Fathom | every 30 min |
| 6 | **Sales Execution** | B | Pre-call brief for every upcoming meeting, MEDDPICC questions, objection help, proposal outline, next-steps summary | daily 7am |
| 7 | **Product Marketing** | B | Competitor trends, win/loss by competitor and segment, objection library with gaps, evidence-backed battlecards, messaging and launch briefs | weekly, monthly |
| 8 | **Revenue Pulse** | B | Weekly leadership summary computed from the CRM: pipeline, coverage, created / won / lost, slips, stage moves, stale deals, forecast rollup, owner scorecards, top risks; plus a daily whole-funnel GTM report | Monday 8am, weekdays 7:30am |
| 9 | **Rep Brief** | A | One daily brief per AE: top accounts, top people, new signals, pipeline gaps, replies, what to do next; plus the push-button AE workflow (research, gated first touch, sequence and call task in one approval) | weekdays 7:30am |
| 10 | **Social Signals** | A | Engagement with company and influencer LinkedIn and YouTube content resolved to contacts and accounts, scored, and routed to the owner as signals | every 30 min |
| 11 | **Reply Desk** | A | Every reply sorted (bounce, opt-out, out of office, referral, not now, objection, interested, question) and handled: stops, opt-outs, tasks, drafted answers | every 10 min |
| 12 | **Enrichment** | B | Provider-agnostic email and phone waterfall with caching, spend caps and provenance (CSV, HTTP or hosted MCP providers such as MoltSets or Apollo); hit rate and cost per hit decide which data vendor stays; Clay and Floqer push and import | hourly |
| 13 | **Forecast Prep** | B | Forecast call prep at AE, manager and exec level: commit vs suggested commit, changes since last week, questions to ask, change alerts; stores every rep's forecast call, tracks call accuracy and builds the board forecast range | weekly, daily alerts, Friday board |
| 14 | **Stack Audit** | B | Tool inventory, utilization, overlap, renewal calendar with notice dates, savings scenarios, side-by-side against agent signals, tool-cut memo | weekly, monthly |
| 15 | **Signal Scout** | A | Scores every account on ICP fit (rules plus judged, evidence-checked typed questions that learn from email opens and replies) and decayed, stacked buying signals; feeds Outbound, Triage, Rep Brief and Sales Execution | daily |
| 16 | Copy QA Gate | C | Scores any outbound copy 0 to 40 (32 passes); every agent's drafts go through it | on call |
| 17 | Ops Monitor | C | Watches the runtime: missed jobs, failures, stuck approvals, failed handoffs, budget pauses, spend | every 15 min |
| 18 | **CRM Hygiene** | B | Duplicate accounts and contacts, contacts with no account, bounced contacts sent back for re-enrichment, stale stages and past close dates; every fix queued for approval | weekly |
| 19 | **Quality Monitor** | B | Re-scores a fixed daily sample of live drafts with the Copy QA Gate, flags unsourced claims, alerts when quality drops against the 28-day baseline | weekdays |
| 20 | Rep Feedback | C | Turns AE feedback on agent output into a one-line rule for the right file and a reviewed GitHub pull request | weekly digest |
| 21 | **Event Campaigns** | B | Invite lists for dinners, booths and webinars from tiers, region and personas; invites, reminders, follow-ups; attendee import as leads and signals; event report | weekdays |
| 22 | Content Studio | C | LinkedIn posts from call themes and approved proof, timed video scripts, SRT captions, frame QA; publishing waits for approval | weekly ideas |
| 23 | **Proposal Builder** | B | Exact quote math from the price book (tiers, term and extra discounts, floor, role limits), branded proposal document from deal evidence; discounts and sends go through approval | weekly expiring quotes |
| 24 | **Call Coach** | B | AE roleplays with the model as the buyer, 100-point scoring of any roleplay or real call, weekly drills from each AE's own calls | weekly |
| 25 | **Signal Sourcing** | A | Finds dated, sourced signals: 10-K and 10-Q quotes (Risk Factors, MD&A), 8-K officer changes, newsroom initiatives and funding, buyer-team hiring on public job boards, or job search sites for enterprises with no public board; changedetection.io page changes (careers, leadership, trust, newsroom, pricing, scripts); first-party PostHog web and product events (pricing, demo and security visits, downloads, trials, repeat visits, product-qualified accounts); no signal, no send; discovers new companies from SEC full-text search | weekdays 5am, weekly discovery |
| 26 | **Follow-Through** | A | Engagement triggers from a RevOps decision table (3 human opens, a click, 2 opens on tier A) pause automation and tee up the AE with a business-hours SLA; a cadence ledger gives every contact after a meeting, event, tee-up or proposal one next touch, drafts the gaps for the AE to confirm one email at a time, escalates anything missed to the owner then the manager, and reports any deal with no follow-up | every 10 and 15 min, weekdays 8am |
| 27 | **Daily Book** | A | A full, ranked book of 25 to 50 people per AE every weekday: warm from the CRM and engagement (engaged, quiet deals, champions who moved, unworked inbound, events, social, closed-lost recycle), cold from owned signals (today's sourced accounts first); per-rep warm/cold split, backfill between pools, shortfall reported never padded; cold first touches drafted for approval | weekdays 6:45am |

How they hand work to each other, what each one reads and writes, and which playbooks each bundles: [docs/AGENTS.md](docs/AGENTS.md).

## Guarantees built into the runtime

- **Opt-outs win everywhere.** One suppression list, checked by every agent and again by the sequence and dialer executors at send time; stops run at once.
- **Nothing is written or sent without a human.** CRM writes, notes, tasks and sequence enrollments are queued in the approval queue. Approve from the CLI, Slack or the HTTP API.
- **Sends need a named person.** A buyer-facing send is approved by someone on the team (never `operator` or a shared token), pipeline emails by their owner, and the check runs again at send time. Approvers can edit the copy first; the edit is recorded.
- **Numbers come from code.** Scores, risk, routing, SLAs, coverage and every pipeline metric are deterministic Python with golden-case evals. Models only draft and summarize, from facts handed to them.
- **No invented facts.** Drafts use only the facts given plus `config/company.yaml`. Proof points and competitor claims come from that file or field evidence; everything else is marked "to verify".
- **Works with no model key.** Every agent has template drafts, so it runs in demos, evals and air-gapped installs. With a key, drafts are model-written and must pass the Copy QA Gate (up to two rewrites).
- **Every draft is traced and every AE decision is feedback.** Model calls are recorded with tokens, cost and latency; each draft keeps the facts it was written from; approve, reject and edits become scores (sent as written vs rewritten). Optional export to Langfuse.
- **The drafter learns from AE edits, in code.** Every Monday the emails AEs approved become a gate-checked, varied few-shot set per message kind, and phrases AEs keep cutting become rules in the prompt. An optional DSPy pass can propose better examples; they replace the set only if they score higher on held-out approvals.
- **Budgets.** Daily token and monthly spend caps per agent, auto-pause and alert.
- **One agent never steps on another.** Outbound skips accounts with an open deal or an inbound lead in progress; Triage routes leads on open deals to the deal owner instead of drafting; handoffs are deduplicated.

## Optional: Slack front end on NetClaw

`netclaw/` adds three Slack bots (pipeline, deals, revops) with 13 conversational subagents for an AE-only team. They call these 27 agents' tools over MCP; the runtime still does every calculation and holds every write for approval. See [netclaw/README.md](netclaw/README.md).

## Quick start (development)

```bash
pip install -e ".[mcp,dev]"
make test        # 194 tests
make evals       # 524 golden cases across 25 agents (release gate)
make demo        # every agent runs once on the fictional sample data, in pipeline order
make compile     # drop-in packages in dist/<agent>/<version>/{claude,chatgpt,gemini,copilot}
```

## Customer install (persistent edition)

```bash
cp .env.example .env          # their model key, CRM token, Slack, sequencer, API token
# edit config/icp.yaml (who they sell to) and config/company.yaml (what they sell, team, competitors)
docker compose up -d          # Postgres + pgvector, scheduler, intake/approvals API
docker compose exec agents gtm selftest
```

Full steps: [docs/INSTALL.md](docs/INSTALL.md). How it fits together: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## The `gtm` command

| Command | Does |
| --- | --- |
| `gtm agents` | List installed agents |
| `gtm sync <agent>` | Read accounts, contacts and deals from the CRM (read-only) |
| `gtm import <agent> accounts\|contacts\|signals\|leads\|deals\|tasks\|meetings\|outcomes <path>` | Load CSV, JSON or a folder of transcripts (zero-integration path) |
| `gtm run <agent> <job>` | Run a job now |
| `gtm schedule` | Run every agent's jobs on their cron |
| `gtm approvals <agent> list\|approve\|reject\|execute` | Human approval queue (`--all-agents` for everything) |
| `gtm drafts [--agent X] [--full]` | Review drafted emails, recaps, battlecards |
| `gtm handoffs [--all]` | Work passed between agents |
| `gtm call <agent> <tool> --args '{...}'` | Call any tool from the shell |
| `gtm serve-mcp <agent>` | MCP server for Claude, ChatGPT or any MCP client |
| `gtm serve-api` | HTTP intake (leads, meetings, signals, replies, engagement) and approvals |
| `gtm ask "..."` / `gtm assistant` / `gtm slack-bot` | Chat with every agent's tools from the terminal or Slack |
| `gtm models` | Check both model tiers (Claude, OpenAI or any open-weight endpoint) |
| `gtm usage <agent>` / `gtm resume <agent>` | Token and spend budgets |
| `gtm selftest` / `gtm eval <agent>` | Diagnostics and golden-case evals |
| `gtm license keygen\|issue\|verify` | Offline Ed25519 license files |

## Skill library

`library/` holds 716 public playbooks from 11 MIT-licensed sources, each with its license and source note. Agents list the ones they use under `library:` in `agent.yaml`; the build bundles them with the license notice. See [library/README.md](library/README.md) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Rules for this repo

See [CLAUDE.md](CLAUDE.md). In short: clean room, deterministic code for anything that must be right, no write or send without approval, every agent passes its evals, fictional sample data only.

Agent code, runtime and documentation: proprietary, all rights reserved. Files under `library/` keep their original MIT licenses.
