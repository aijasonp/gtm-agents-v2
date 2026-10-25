#!/usr/bin/env python3
"""Build the NetClaw GTM fleet from netclaw/fleet.yaml.

    python3 netclaw/build.py [--config config] [--out dist/netclaw]

For each instance it writes:
    <out>/<instance>/skills/<name>/...        curated skill set (dir name == skill name)
    <out>/<instance>/agents/<agent>.md        NetClaw subagent files (~/.netclaw/agents/)
    <out>/<instance>/config/netclaw.json      config template (${VARS} filled by install.sh)
    <out>/<instance>/config/webhooks/*.json   inbound webhook routes
    <out>/<instance>/reminders/*.json         scheduled reminders (netclaw reminder import)
    <out>/<instance>/MANIFEST.md              what is in this instance

Skill entries: `lib:<name>` resolves through library/index.json, `lib:<name>@<source>`
picks one source when a name repeats, anything else is a path from the repo root.

It fails (exit 1) on: a missing skill, a SKILL.md without name or description,
two different skills with the same name in one instance, or any banned
identifier anywhere in the output (see check_clean.py).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from check_clean import scan  # noqa: E402

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".pytest_cache", ".venv"}
FRONT = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)

# Runtime agent tools run on Auto in NetClaw: they compute, draft, or queue a write in
# the runtime's approval queue (nothing reaches the CRM, sequencer or an inbox until a
# human approves it there). Tools that queue a customer-facing write also ask in Slack,
# so the AE sees the request where they are working.
TOOL_OVERRIDES = {
    "signal-scout/push_to_crm": "Approval",
    "signal-scout/record_outcome": "Approval",
    "lead-triage/route_lead": "Approval",
    "reply-desk/handle_reply": "Approval",
    "reply-desk/opt_out": "Approval",
    "deal-inspection/update_meddpicc": "Approval",
    "seller-follow-up/log_next_step": "Approval",
}
TOOLS_HOST = "gtm-tools"


def fail(msg: str) -> None:
    print(f"BUILD FAILED: {msg}", file=sys.stderr)
    sys.exit(1)


def read_skill(path: Path) -> dict:
    sk = path / "SKILL.md"
    if not sk.is_file():
        fail(f"{path.relative_to(ROOT)} has no SKILL.md")
    text = sk.read_text(encoding="utf-8", errors="replace")
    m = FRONT.match(text)
    if not m:
        fail(f"{sk.relative_to(ROOT)} has no YAML frontmatter")
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        fail(f"{sk.relative_to(ROOT)} frontmatter is not valid YAML: {str(e).splitlines()[0]}")
    name, desc = meta.get("name"), meta.get("description")
    if not name or not desc:
        fail(f"{sk.relative_to(ROOT)} needs both name and description")
    desc = " ".join(str(desc).split())
    return {"name": str(name).strip(), "description": desc, "path": path, "lines": text.count("\n") + 1}


def copy_skill(src: Path, dest: Path) -> None:
    def ignore(d, names):
        return [n for n in names if n in SKIP_DIRS or n.endswith(".pyc")]
    shutil.copytree(src, dest, ignore=ignore)


def first_sentence(desc: str) -> str:
    desc = desc.replace(" \u2014 ", ": ").replace("\u2014", ", ").replace(" \u2013 ", ": ")
    s = re.split(r"(?<=[.!?])\s", desc, maxsplit=1)[0]
    return s if len(s) <= 220 else s[:217] + "..."


def build_playbooks(dest: Path, config: Path) -> None:
    copy_skill(HERE / "shared" / "gtm-playbooks", dest)
    refs = dest / "references"
    refs.mkdir(exist_ok=True)
    for name in ("company.yaml", "icp.yaml"):
        src = config / name
        if not src.is_file():
            fail(f"missing {src}; the playbooks ship this deployment's {name}")
        shutil.copy2(src, refs / name)


def resolve(entry: str, index: dict) -> Path:
    if not entry.startswith("lib:"):
        return ROOT / entry
    name, _, source = entry[4:].partition("@")
    hits = [i for i in index.get(name, []) if not source or i["source"] == source]
    if not hits:
        fail(f"{entry}: not in library/index.json")
    if len(hits) > 1:
        fail(f"{entry}: {len(hits)} sources have this name; pick one with @source")
    return ROOT / hits[0]["path"]


def desk_skill(inst: str, spec: dict, agents: dict, rules: str) -> str:
    rows = "\n".join(
        f"| `{a}` | {agents[a]['stage']} | {agents[a]['job']} |" for a in spec["agents"]
    )
    return f"""---
name: {inst}-desk
description: How the {inst} GTM workspace runs. Load at the start of any request in this workspace to decide which subagent handles it.
metadata:
  version: 1.0.0
---

# {inst.title()} desk

{spec['purpose']}

Delegate with `spawn_agent` (agent name, task, context). Give the subagent everything it needs in `task` and `context`: account, deal, AE, links, the AE's exact ask. One subagent per job; chain them when work continues (for example Signal Scout, then Prospecting Writer, then Copy QA Gate).

| Subagent | Stage | Job |
| --- | --- | --- |
{rows}

If a request fits no subagent, answer it directly using the skills in this workspace, or tell the AE which workspace owns it (pipeline, deals or revops).

{rules}
"""


def netclaw_json(inst: str, spec: dict, servers: dict) -> dict:
    mcp = {}
    for name in spec["mcp"]:
        s = servers[name]
        mcp[name] = {"Transport": "http", "Url": f"http://{TOOLS_HOST}:{s['port']}/mcp", "Enabled": True}
    approval = {
        "DefaultMode": "Approval",
        "McpServerDefaults": {n: "Auto" for n in spec["mcp"]},
        "ToolOverrides": {k: v for k, v in TOOL_OVERRIDES.items() if k.split("/")[0] in spec["mcp"]},
    }
    trusted = {"McpServersMode": "Allowlist", "AllowedMcpServers": list(spec["mcp"]), "ApprovalPolicy": approval}
    return {
        "Slack": {
            "Enabled": True,
            "DefaultChannelName": spec["slack_channel"],
            "AllowedChannelIds": ["${SLACK_CHANNEL_ID}"],
            "AllowDirectMessages": True,
            "AllowedUserIds": [],
            "ChannelAudiences": {"${SLACK_CHANNEL_ID}": "team", "dm": "personal"},
        },
        "Scheduling": {"Enabled": True},
        "Webhooks": {"Enabled": True},
        "SkillSync": {"Enabled": True, "DisableSystemSkillSync": False},
        "ExternalSkills": {"Sources": [
            {"Name": f"gtm-{inst}", "Path": "/opt/gtm/skills", "Enabled": True, "AllowSymlinks": False}
        ]},
        "McpServers": mcp,
        "Tools": {"AudienceProfiles": {
            "Personal": trusted,
            "Team": trusted,
            "Public": {"McpServersMode": "Allowlist", "AllowedMcpServers": [],
                       "ApprovalPolicy": {"DefaultMode": "Deny"}},
        }},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=str(ROOT / "config"), help="folder with company.yaml and icp.yaml")
    ap.add_argument("--out", default=str(ROOT / "dist/netclaw"))
    a = ap.parse_args()

    fleet = yaml.safe_load((HERE / "fleet.yaml").read_text())
    rules = (HERE / "shared" / "operating-rules.md").read_text().strip()
    config = Path(a.config).resolve()
    index: dict[str, list] = {}
    for item in json.loads((ROOT / "library" / "index.json").read_text()):
        index.setdefault(item["name"], []).append(item)
    agents_dir = ROOT / "agents"
    for name, s in fleet["mcp_servers"].items():
        if not (agents_dir / name / "agent.yaml").is_file():
            fail(f"mcp server {name} has no runtime agent at agents/{name}")
    out = Path(a.out).resolve()
    if out.exists():
        shutil.rmtree(out)

    servers = fleet["mcp_servers"]
    summary = []
    agent_total = 0
    for inst, spec in fleet["instances"].items():
        base = out / inst
        (base / "skills").mkdir(parents=True)
        missing_srv = [s for s in spec["mcp"] if s not in servers]
        if missing_srv:
            fail(f"{inst}: unknown MCP servers {missing_srv}")

        # Resolve and validate every skill for this instance.
        chosen: dict[str, dict] = {}
        agent_skills: dict[str, list[dict]] = {}
        shared = [read_skill(resolve(p, index)) for p in fleet["shared_skills"]]
        for ag, aspec in spec["agents"].items():
            agent_skills[ag] = [read_skill(resolve(p, index)) for p in aspec["skills"]]
            for tool in aspec["tools"]:
                server, _, fn = tool.partition("/")
                if server not in spec["mcp"]:
                    fail(f"{inst}/{ag}: tool {tool} uses a server not in this instance's mcp list")
                if fn:
                    tools = yaml.safe_load((agents_dir / server / "agent.yaml").read_text()).get("tools", [])
                    if fn not in tools:
                        fail(f"{inst}/{ag}: {server} has no tool {fn} (has: {', '.join(tools)})")
        for sk in shared + [s for lst in agent_skills.values() for s in lst]:
            prev = chosen.get(sk["name"])
            if prev and prev["path"] != sk["path"]:
                fail(f"{inst}: two skills named {sk['name']}: "
                     f"{prev['path'].relative_to(ROOT)} and {sk['path'].relative_to(ROOT)}")
            chosen[sk["name"]] = sk

        for name, sk in chosen.items():
            if name == "gtm-playbooks":
                build_playbooks(base / "skills" / name, config)
            else:
                copy_skill(sk["path"], base / "skills" / name)
        desk = base / "skills" / f"{inst}-desk"
        desk.mkdir()
        (desk / "SKILL.md").write_text(desk_skill(inst, spec, spec["agents"], rules))

        # Subagents
        (base / "agents").mkdir()
        for ag, aspec in spec["agents"].items():
            tmpl = HERE / "agents" / f"{ag}.md"
            if not tmpl.is_file():
                fail(f"{inst}: no subagent template netclaw/agents/{ag}.md")
            lines = ["## Skills to load (skill_load)",
                     "Always available: `gtm-playbooks` (operating rules, signal sayability, this deployment's company.yaml and icp.yaml)."]
            for sk in agent_skills[ag]:
                lines.append(f"- `{sk['name']}`: {first_sentence(sk['description'])}")
            lines.append("")
            lines.append("## Tools")
            lines.append(", ".join(f"`{t}`" for t in aspec["tools"]))
            body = tmpl.read_text().replace("{{SKILLS}}", "\n".join(lines)).replace("{{RULES}}", rules)
            (base / "agents" / f"{ag}.md").write_text(body)
            agent_total += 1

        # Config, webhooks, reminders
        (base / "config" / "webhooks").mkdir(parents=True)
        (base / "config" / "netclaw.json").write_text(json.dumps(netclaw_json(inst, spec, servers), indent=2) + "\n")
        src_inst = HERE / "instances" / inst
        for kind, dest in (("webhooks", base / "config" / "webhooks"), ("reminders", base / "reminders")):
            dest.mkdir(parents=True, exist_ok=True)
            for f in sorted((src_inst / kind).glob("*.json")):
                json.loads(f.read_text())  # must be valid JSON
                shutil.copy2(f, dest / f.name)

        n_rem = len(list((base / "reminders").glob("*.json")))
        n_hook = len(list((base / "config" / "webhooks").glob("*.json")))
        long = sorted(n for n, s in chosen.items() if s["lines"] > 500)
        (base / "MANIFEST.md").write_text(
            f"# {inst}\n\n{spec['purpose']}\n\n"
            f"- Subagents: {', '.join(spec['agents'])}\n"
            f"- Skills: {len(chosen) + 1} (including `{inst}-desk`)\n"
            f"- MCP servers: {', '.join(spec['mcp'])}\n"
            f"- Reminders: {n_rem}, webhooks: {n_hook}\n\n"
            "## Skills\n" + "\n".join(f"- `{n}` ({chosen[n]['path'].relative_to(ROOT)})" for n in sorted(chosen)) + "\n"
            + (f"\nSKILL.md files over 500 lines (third-party, loaded on demand only): {', '.join(long)}\n" if long else "")
        )
        summary.append((inst, len(spec["agents"]), len(chosen) + 1, len(spec["mcp"]), n_rem, n_hook))

    hits = scan(out)
    if hits:
        for h in hits[:20]:
            print(f"  banned identifier in {h}", file=sys.stderr)
        fail(f"{len(hits)} banned identifiers in build output")

    print(f"{'instance':<10} {'agents':>6} {'skills':>6} {'mcp':>4} {'reminders':>9} {'webhooks':>8}")
    for row in summary:
        print(f"{row[0]:<10} {row[1]:>6} {row[2]:>6} {row[3]:>4} {row[4]:>9} {row[5]:>8}")
    print(f"total agents: {agent_total}; output: {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}; clean scan: passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
