#!/usr/bin/env python3
"""Build the NetClaw GTM fleet from netclaw/fleet.yaml.

    python3 netclaw/build.py [--profile path/to/product_profile.yaml] [--out dist/netclaw]

For each instance it writes:
    <out>/<instance>/skills/<name>/...        curated skill set (dir name == skill name)
    <out>/<instance>/agents/<agent>.md        NetClaw subagent files (~/.netclaw/agents/)
    <out>/<instance>/config/netclaw.json      config template (${VARS} filled by install.sh)
    <out>/<instance>/config/webhooks/*.json   inbound webhook routes
    <out>/<instance>/reminders/*.json         scheduled reminders (netclaw reminder import)
    <out>/<instance>/MANIFEST.md              what is in this instance

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

# Approval defaults per MCP server. Reads on scoring and QA run on autopilot;
# anything that can change a customer-facing system waits for an AE's click.
SERVER_APPROVAL = {
    "signal-scout": "Auto",
    "copy-qa-gate": "Auto",
    "scoring-engine": "Auto",
    "enrichment": "Auto",
    "call-recorder": "Auto",
    "crm": "Approval",
    "workspace": "Approval",
    "sequencer": "Approval",
}
TOOL_OVERRIDES = {
    "signal-scout/push_to_crm": "Approval",
    "signal-scout/record_outcome": "Approval",
}


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


def build_playbooks(dest: Path, profile: Path) -> None:
    copy_skill(HERE / "shared" / "gtm-playbooks", dest)
    refs = dest / "references"
    refs.mkdir(exist_ok=True)
    for f in sorted((ROOT / "library" / "references").glob("*.md")):
        shutil.copy2(f, refs / f.name)
    shutil.copy2(profile, refs / "product-profile.yaml")
    with open(dest / "SKILL.md", "a", encoding="utf-8") as fh:
        fh.write("\n## Product profile\n`references/product-profile.yaml` is this deployment's product profile: "
                 "what we sell, ICP, pain points, differentiators, competitors and the only proof points "
                 "writers may state as fact.\n")


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
        mcp[name] = {"Transport": s["transport"], "Url": s["url"], "Enabled": True}
    approval = {
        "DefaultMode": "Approval",
        "McpServerDefaults": {n: SERVER_APPROVAL[n] for n in spec["mcp"]},
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
    ap.add_argument("--profile", default=str(ROOT / "library/outbound-engine/product_profile.example.yaml"))
    ap.add_argument("--out", default=str(ROOT / "dist/netclaw"))
    a = ap.parse_args()

    fleet = yaml.safe_load((HERE / "fleet.yaml").read_text())
    rules = (HERE / "shared" / "operating-rules.md").read_text().strip()
    profile = Path(a.profile).resolve()
    if not profile.is_file():
        fail(f"product profile not found: {profile}")
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
        shared = [read_skill(ROOT / p) for p in fleet["shared_skills"]]
        for ag, aspec in spec["agents"].items():
            agent_skills[ag] = [read_skill(ROOT / p) for p in aspec["skills"]]
        for sk in shared + [s for lst in agent_skills.values() for s in lst]:
            prev = chosen.get(sk["name"])
            if prev and prev["path"] != sk["path"]:
                fail(f"{inst}: two skills named {sk['name']}: "
                     f"{prev['path'].relative_to(ROOT)} and {sk['path'].relative_to(ROOT)}")
            chosen[sk["name"]] = sk

        for name, sk in chosen.items():
            if name == "gtm-playbooks":
                build_playbooks(base / "skills" / name, profile)
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
                     "Always available: `gtm-playbooks` (copy rules, sayability matrix, brief template, product profile)."]
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
