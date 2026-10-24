"""Compile each agent (agent.yaml + skill/) into drop-in packages for every target.

    python build/compile.py                # all agents, all targets
    python build/compile.py signal-scout   # one agent

Outputs to dist/<agent>/<version>/:
  claude/<agent>-skill.zip      upload in Claude: Settings > Capabilities > Skills
  claude/<agent>-plugin/        Claude Code / Cowork plugin: skill + MCP server config
  chatgpt/                      Custom GPT or Project: instructions.md + knowledge/ + mcp.json
  gemini/                       Gem: instructions.md + knowledge/
  copilot/                      Copilot Studio: instructions.md + knowledge/ + agent.json
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))

from gtm_core.agents import Manifest, discover  # noqa: E402

INSTRUCTION_LIMITS = {"chatgpt": 8000, "gemini": 8000, "copilot": 8000}  # characters
KNOWLEDGE_EXT = {".yaml": ".md", ".yml": ".md", ".txt": ".txt", ".md": ".md", ".json": ".json"}


def split_frontmatter(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n?", text, re.S)
    if not m:
        return {}, text
    import yaml
    return yaml.safe_load(m.group(1)) or {}, text[m.end():]


def condense(body: str, limit: int, knowledge_name: str) -> tuple[str, bool]:
    """Fit instructions under a platform cap by moving trailing sections to a knowledge file."""
    note = f"\n\nFull instructions, rules and formats are in the knowledge file `{knowledge_name}`. Follow them."
    if len(body) <= limit:
        return body, False
    sections = re.split(r"(?m)^(?=## )", body)
    kept = ""
    for s in sections:
        if len(kept) + len(s) + len(note) > limit:
            break
        kept += s
    return kept.rstrip() + note, True


def knowledge_files(m: Manifest, dest: Path) -> list[str]:
    dest.mkdir(parents=True, exist_ok=True)
    names = []
    for rel in m.references:
        src = m.path(rel)
        ext = KNOWLEDGE_EXT.get(src.suffix.lower(), src.suffix)
        out = dest / (src.stem + ext)
        if src.suffix.lower() in (".yaml", ".yml"):
            out.write_text(f"# {src.name}\n\n```yaml\n{src.read_text()}```\n")
        else:
            shutil.copy2(src, out)
        names.append(out.name)
    return names


def mcp_config(m: Manifest) -> dict:
    return {"mcpServers": {m.id: {"command": "gtm", "args": ["serve-mcp", m.id],
                                  "env": {"GTM_AGENTS_DIR": "${GTM_AGENTS_DIR}", "DATABASE_URL": "${DATABASE_URL}"}}}}


def build_claude(m: Manifest, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    skill_dir = m.path("skill")
    zpath = out / f"{m.id}-skill.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(skill_dir.rglob("*")):
            if f.is_file():
                z.write(f, Path(m.id) / f.relative_to(skill_dir))
    plug = out / f"{m.id}-plugin"
    if plug.exists():
        shutil.rmtree(plug)
    (plug / ".claude-plugin").mkdir(parents=True)
    (plug / ".claude-plugin" / "plugin.json").write_text(json.dumps({
        "name": m.id, "version": m.version, "description": " ".join(m.description.split())}, indent=2))
    shutil.copytree(skill_dir, plug / "skills" / m.id)
    if m.tools:
        (plug / ".mcp.json").write_text(json.dumps(mcp_config(m), indent=2))


def build_chat(m: Manifest, out: Path, target: str) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    fm, body = split_frontmatter(m.path(m.skill).read_text())
    know = out / "knowledge"
    names = knowledge_files(m, know)
    full_name = "instructions-full.md"
    text, moved = condense(body.strip(), INSTRUCTION_LIMITS[target], full_name)
    if moved:
        (know / full_name).write_text(body)
        names.append(full_name)
    (out / "instructions.md").write_text(text + "\n")
    meta = {"name": m.name, "description": fm.get("description", m.description), "version": m.version,
            "instructions_chars": len(text), "knowledge": names,
            "tools": "connect the MCP server in mcp.json (persistent edition)" if m.tools else "none"}
    if target == "chatgpt" and m.tools:
        (out / "mcp.json").write_text(json.dumps(mcp_config(m), indent=2))
    if target == "copilot":
        (out / "agent.json").write_text(json.dumps({"name": m.name, "description": meta["description"],
                                                    "instructions": "instructions.md", "knowledge": names}, indent=2))
    (out / "README.md").write_text(SETUP[target].format(name=m.name, n=len(names)))
    return meta


SETUP = {
    "chatgpt": ("# {name} for ChatGPT\n\n1. Create a Custom GPT (or a Project).\n2. Paste `instructions.md` into Instructions.\n"
                "3. Upload the {n} files in `knowledge/`.\n4. Persistent edition: add the MCP server from `mcp.json` as a connector.\n"),
    "gemini": ("# {name} for Gemini\n\n1. Create a Gem.\n2. Paste `instructions.md` into Instructions.\n"
               "3. Upload the {n} files in `knowledge/`.\n"),
    "copilot": ("# {name} for Microsoft Copilot\n\n1. In Copilot Studio, create an agent.\n2. Paste `instructions.md` into Instructions.\n"
                "3. Add the {n} files in `knowledge/` as knowledge sources.\n"),
}


def compile_agent(m: Manifest, dist: Path) -> dict:
    base = dist / m.id / m.version
    if base.exists():
        shutil.rmtree(base)
    build_claude(m, base / "claude")
    report = {"agent": m.id, "version": m.version, "targets": {"claude": "ok"}}
    for t in ("chatgpt", "gemini", "copilot"):
        report["targets"][t] = build_chat(m, base / t, t)
    return report


def main(argv: list[str]) -> int:
    ms = discover(ROOT / "agents")
    targets = argv or list(ms)
    dist = ROOT / "dist"
    reports = [compile_agent(ms[t], dist) for t in targets]
    print(json.dumps(reports, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
