"""The NetClaw fleet builds, every agent and skill resolves, and nothing banned ships."""
import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "netclaw"))
from check_clean import scan  # noqa: E402


def test_repo_is_clean():
    assert scan(ROOT) == []


def test_fleet_builds(tmp_path):
    out = tmp_path / "fleet"
    r = subprocess.run([sys.executable, str(ROOT / "netclaw/build.py"), "--out", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    fleet = yaml.safe_load((ROOT / "netclaw/fleet.yaml").read_text())
    agents = [a for i in fleet["instances"].values() for a in i["agents"]]
    assert len(agents) == 13
    for inst, spec in fleet["instances"].items():
        base = out / inst
        cfg = json.loads((base / "config/netclaw.json").read_text())
        assert set(cfg["McpServers"]) == set(spec["mcp"])
        for name, srv in cfg["McpServers"].items():
            assert srv["Url"] == f"http://gtm-tools:{fleet['mcp_servers'][name]['port']}/mcp"
            assert (ROOT / "agents" / name / "agent.yaml").is_file()
        assert cfg["Tools"]["AudienceProfiles"]["Public"]["AllowedMcpServers"] == []
        for ag in spec["agents"]:
            body = (base / "agents" / f"{ag}.md").read_text()
            assert body.startswith("---\nname: " + ag)
            assert "{{SKILLS}}" not in body and "{{RULES}}" not in body
        skills = [d for d in (base / "skills").iterdir() if d.is_dir()]
        assert 10 <= len(skills) <= 60, f"{inst} has {len(skills)} skills"
        for d in skills:
            assert (d / "SKILL.md").is_file()
        assert (base / "skills" / "gtm-playbooks/references/company.yaml").is_file()
    assert scan(out) == []
