"""Chief of staff: one front door that routes each request to the one to three agents it needs.

The flat assistant hands the model every installed agent's tools on every message (159 tools across 27 agents),
which fills the context window before any work starts and makes smaller models pick wrong tools. The chief of
staff never sees tools. It reads a one-line catalog of agents, decides who should handle the request, and runs
each step in a fresh context that holds only those agents' tools and their SKILL.md.

    request ─► keyword routing (code, no model) ─┐
             └► routing model (catalog only) ────┴─► step 1: agents X (their tools + skills only)
                                                     step 2: agents Y, given step 1's answer
                                                     ─► one reply

Routing rules, domains and keywords live in config/routing.yaml. Commands (status, approve, stop, run...)
never reach here; see slack_commands.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .assistant import Answer, Assistant
from .config import Settings
from .store import Store

ROUTER_SYSTEM = """You are the chief of staff for a revenue team's AI agents. You do not answer questions yourself.
You decide which agents should handle the request. Each agent loads its own tools only when you pick it, so pick
the fewest agents that fully cover the request.

Reply with JSON only, no prose:
{"steps": [{"agents": ["agent-id"], "task": "what this step must do, in one or two sentences"}]}

Rules:
- One step with one agent for most requests. Use two or three agents in one step only when they must work together.
- Use several steps (at most {max_steps}) only when a later step needs an earlier step's result, in order.
- Use only agent ids from the catalog. At most {max_agents} agents per step.
- Rewrite the task so it stands alone (fill in names and dates from the conversation).
- If the request is unclear or no agent fits, reply {"reply": "one short clarifying question or answer"}.

Agent catalog:
{catalog}"""

STEP_SYSTEM = """You are {names}, part of a revenue team's agent system. Answer with data from your tools, never from memory.

Rules:
- Use tools for every number, score, list, deal, account or draft. If no tool covers it, say what is missing.
- Tools that write (CRM, sequences, dialer, notes, tasks) only queue a request for approval unless autonomy is set to
  auto for that action. Report what the tool returned ("queued for approval #N" or "written").
- Be brief: a few lines or a short list. Plain words, no em dashes, no filler.
- When a tool returns an error, say what is missing and how to fix it in one line.
- Never invent names, emails, numbers, customers or quotes.
{context}
{skills}"""


@dataclass
class Step:
    agents: list[str]
    task: str


@dataclass
class Plan:
    steps: list[Step] = field(default_factory=list)
    reply: str | None = None      # the router answered or asked a clarifying question
    method: str = ""              # keywords | model | fallback | sticky


def _words(text: str) -> str:
    return " " + re.sub(r"[^a-z0-9/&.\- ]+", " ", (text or "").lower()) + " "


def load_routing(settings: Settings) -> dict:
    path = Path(os.environ.get("GTM_ROUTING") or Path(settings.agents_dir).resolve().parent / "config" / "routing.yaml")
    return yaml.safe_load(path.read_text()) if path.exists() else {}


class ChiefOfStaff:
    def __init__(self, settings: Settings, store: Store | None = None, manifests: dict | None = None,
                 gateway=None, assistant: Assistant | None = None, routing: dict | None = None):
        # Binding every agent's tools is cheap (Python functions); what matters is that only a step's
        # tools are ever sent to the model.
        self.a = assistant or Assistant(settings, store=store, manifests=manifests, gateway=gateway)
        self.s, self.store = settings, self.a.store
        self.cfg = routing if routing is not None else load_routing(settings)
        lim = self.cfg.get("limits") or {}
        self.max_agents = int(lim.get("max_agents_per_step", 3))
        self.max_steps = int(lim.get("max_steps", 3))
        self.max_tools = int(lim.get("max_tools_per_step", 24))
        self.skill_chars = int(lim.get("skill_chars", 6000))
        self.history_turns = int(lim.get("history_turns", 4))
        kr = self.cfg.get("keyword_routing") or {}
        self.min_score, self.margin = float(kr.get("min_score", 2)), float(kr.get("margin", 2.0))
        self.agents = set(self.a.manifests)
        self.keywords = {a: [k.lower() for k in ks or []] for a, ks in (self.cfg.get("keywords") or {}).items()
                         if a in self.agents}
        self.router_tier = os.environ.get("GTM_ROUTER_TIER", "cheap")
        self._skills: dict[str, str] = {}

    # ---------------- catalog ----------------
    def domain_of(self, agent: str) -> str:
        for d, spec in (self.cfg.get("domains") or {}).items():
            if agent in (spec.get("agents") or []):
                return d
        return "other"

    def catalog(self) -> str:
        """One line per agent, grouped by domain: what the router reads instead of tool definitions."""
        lines, done = [], set()
        groups = [(d, spec.get("description", ""), spec.get("agents") or [])
                  for d, spec in (self.cfg.get("domains") or {}).items()]
        groups.append(("other", "", sorted(self.agents)))
        for d, desc, ags in groups:
            ags = [a for a in ags if a in self.agents and a not in done]
            if not ags:
                continue
            lines.append(f"[{d}] {desc}".rstrip())
            for a in ags:
                m = self.a.manifests[a]
                first = re.split(r"(?<=\.)\s", " ".join((m.description or m.name).split()), maxsplit=1)[0]
                lines.append(f"- {a}: {first[:220]}")
                done.add(a)
        return "\n".join(lines)

    # ---------------- routing ----------------
    def keyword_scores(self, text: str) -> dict[str, float]:
        t = _words(text)
        out: dict[str, float] = {}
        for agent, kws in self.keywords.items():
            score = 0.0
            for k in kws:
                if f" {k} " in t:
                    score += len(k.split())
            if score:
                out[agent] = score
        return out

    def route(self, question: str, history: list[dict] | None = None, last_route: list[str] | None = None) -> Plan:
        scores = self.keyword_scores(question)
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])
        if ranked:
            top, s1 = ranked[0]
            s2 = ranked[1][1] if len(ranked) > 1 else 0
            if s1 >= self.min_score and s1 >= self.margin * s2:
                return Plan([Step([top], question)], method="keywords")
        plan = self._model_route(question, history, last_route)
        if plan is not None:
            return plan
        # No model: best keyword guess, else the agent that handled this thread last, else ask.
        if ranked:
            return Plan([Step([a for a, _ in ranked[:min(2, self.max_agents)]], question)], method="fallback")
        if last_route:
            return Plan([Step(last_route, question)], method="sticky")
        return Plan(reply=self.help_text(), method="fallback")

    def _router_gateway(self):
        g = self.a.gateway
        if g is None:
            return None, None
        for tier in (self.router_tier, "frontier"):
            if g.available(tier):
                return g, tier
        return None, None

    def _model_route(self, question: str, history, last_route) -> Plan | None:
        g, tier = self._router_gateway()
        if g is None:
            return None
        system = (ROUTER_SYSTEM.replace("{catalog}", self.catalog()).replace("{max_steps}", str(self.max_steps))
                  .replace("{max_agents}", str(self.max_agents)))
        convo = []
        for h in (history or [])[-2 * self.history_turns:]:
            convo.append(f"{h['role']}: {str(h.get('content', ''))[:400]}")
        prompt = question
        if convo or last_route:
            prompt = ("Conversation so far:\n" + "\n".join(convo) +
                      (f"\nLast request was handled by: {', '.join(last_route)}" if last_route else "") +
                      f"\n\nNew request: {question}")
        try:
            c = g.chat([{"role": "user", "content": prompt}], system=system, model_class=tier, max_tokens=400)
        except Exception:
            return None
        return self.parse_plan(c.text, question)

    def parse_plan(self, text: str, question: str) -> Plan | None:
        m = re.search(r"\{.*\}", text or "", re.S)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
        if data.get("reply") and not data.get("steps"):
            return Plan(reply=str(data["reply"]), method="model")
        steps = []
        for st in (data.get("steps") or [])[:self.max_steps]:
            ags = [a for a in dict.fromkeys(st.get("agents") or []) if a in self.agents][:self.max_agents]
            if ags:
                steps.extend(self._fit(Step(ags, str(st.get("task") or question))))
        return Plan(steps[:self.max_steps], method="model") if steps else None

    def _fit(self, step: Step) -> list[Step]:
        """Split a step whose agents together exceed the tool limit into one step per agent."""
        if len(self.a.tool_specs(step.agents)) <= self.max_tools or len(step.agents) == 1:
            return [step]
        return [Step([a], step.task) for a in step.agents]

    # ---------------- running ----------------
    def skill(self, agent: str) -> str:
        if agent not in self._skills:
            m = self.a.manifests[agent]
            try:
                body = m.path(m.skill).read_text()
            except OSError:
                body = ""
            body = re.sub(r"^---.*?---\s*", "", body, flags=re.S)  # frontmatter
            self._skills[agent] = body[:self.skill_chars]
        return self._skills[agent]

    def step_system(self, step: Step, prior: list[tuple[Step, str]]) -> str:
        names = ", ".join(self.a.manifests[a].name for a in step.agents)
        ctx = ""
        if prior:
            ctx = "\nEarlier steps of this request already found:\n" + "\n".join(
                f"- {', '.join(s.agents)}: {txt[:1500]}" for s, txt in prior)
        skills = "\n\n".join(f"## Skill: {self.a.manifests[a].name}\n{self.skill(a)}" for a in step.agents)
        return STEP_SYSTEM.format(names=names, context=ctx, skills=skills)

    def ask(self, question: str, history: list[dict] | None = None, thread_key: str | None = None,
            max_steps_per_agent: int = 8) -> Answer:
        last = self.store.get_state(f"{thread_key}:route") if thread_key else None
        plan = self.route(question, history, last)
        if plan.reply is not None:
            return Answer(plan.reply, [{"route": [], "method": plan.method}])
        prior: list[tuple[Step, str]] = []
        trace, usd = [], 0.0
        recent = (history or [])[-2 * self.history_turns:]
        for st in plan.steps:
            ans = self.a.ask(st.task, recent if not prior else None, max_steps=max_steps_per_agent,
                             agents=st.agents, system=self.step_system(st, prior))
            n_tools = len(self.a.tool_specs(st.agents))
            trace.append({"route": st.agents, "method": plan.method, "tools_loaded": n_tools, "task": st.task})
            trace.extend(ans.trace)
            usd += ans.usd
            prior.append((st, ans.text))
        if thread_key:
            self.store.set_state(f"{thread_key}:route", plan.steps[-1].agents)
        text = prior[-1][1] if len(prior) == 1 else "\n\n".join(
            f"*{', '.join(self.a.manifests[a].name for a in s.agents)}*\n{t}" for s, t in prior)
        if os.environ.get("GTM_COS_SHOW_ROUTE", "1") != "0":
            used = sorted({a for s, _ in prior for a in s.agents})
            loaded = sum(x["tools_loaded"] for x in trace if "route" in x)
            text = f"{text}\n_via {', '.join(self.a.manifests[a].name for a in used)}, {loaded} tools loaded_"
        return Answer(text, trace, usd)

    def explain(self, question: str) -> str:
        """What `route <question>` shows: the plan and how many tools each step would load, without running it."""
        plan = self.route(question)
        if plan.reply is not None:
            return f"No agent picked ({plan.method}). Reply would be: {plan.reply}"
        lines = [f"Routed by {plan.method}; {len(self.a.tools)} tools exist in total."]
        for i, st in enumerate(plan.steps, 1):
            lines.append(f"{i}. {', '.join(st.agents)} ({len(self.a.tool_specs(st.agents))} tools): {st.task}")
        return "\n".join(lines)

    def help_text(self) -> str:
        doms = self.cfg.get("domains") or {}
        rows = [f"- *{d}*: {spec.get('description', '')}" for d, spec in doms.items()]
        return "I could not tell which team should take that. Ask about one of these:\n" + "\n".join(rows)


def router_enabled() -> bool:
    return os.environ.get("GTM_ROUTER", "on").lower() not in ("off", "0", "flat")
