# Chief of staff routing

One Slack bot, one front door, and the model only ever sees the tools of the agents a request needs.

## Why

The flat assistant sends every installed agent's tool definitions on every model call: 167 tools across 29 agents,
about 13,800 tokens before the question, repeated on every step of the tool loop. That crowds out the data the
tools return, costs money on every turn, and makes smaller open-weight models pick the wrong tool.

## How a request runs

```
Slack message
  ├─ command? (status, approve 12, stop, run <agent> <job>, route ...) ─► handled in code, no model
  └─ question
       1. keyword routing (config/routing.yaml), no model
            clear winner ─► step with that agent
       2. otherwise one routing call on the cheap tier
            input: one-line catalog of agents grouped by domain (no tool definitions, about 1,500 tokens)
            output: {"steps": [{"agents": [...], "task": "..."}]} or a clarifying question
       3. each step runs in a fresh context
            tools: only the step's agents (2 to 10 tools, at most 24, split if larger)
            prompt: those agents' SKILL.md files and the results of earlier steps
       4. one reply, ending "via <agent>, N tools loaded"
```

| | Flat assistant | Chief of staff |
| --- | --- | --- |
| Tools sent per model call | 167 | 2 to 10 |
| Prompt before the question | about 13,800 tokens | about 1,100 to 2,000 tokens per step, plus about 1,500 for routing when keywords miss |
| Skills in context | none | only the routed agents' |
| A tool outside the route | can be called | refused, even if the model names it |

## Follow-ups

The agents that answered last in a Slack thread are remembered for that thread. A short follow-up ("and last
quarter?") goes to the routing model with that context, or straight back to the same agents when no model is set.

## Tuning

- `config/routing.yaml`: domains, per-agent keywords, `min_score` and `margin` for keyword routing, step limits,
  how much of each SKILL.md goes into a step.
- `route <question>` in Slack or `gtm route "..."` shows the plan and the tool count without running anything. Use
  it when a question lands on the wrong agent, then add the team's words to that agent's keywords.
- `GTM_ROUTER_TIER` picks the routing model tier (default cheap). `GTM_ROUTER=off` goes back to the flat assistant.

## Adding an agent

Give it an `agent.yaml` description whose first sentence says what it does (that sentence is its catalog line), add
it to a domain and give it keywords in `config/routing.yaml`. Nothing else changes.
