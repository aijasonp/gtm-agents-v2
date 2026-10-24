import json
import subprocess
import sys
import zipfile
from pathlib import Path

from evals.runner import run_agent_evals


def test_all_agent_evals_pass(manifests):
    for m in manifests.values():
        r = run_agent_evals(m)
        assert r["passed"], json.dumps(r, indent=2)


def test_compile_outputs(tmp_path):
    out = subprocess.run([sys.executable, "build/compile.py"], capture_output=True, text=True, check=True)
    report = json.loads(out.stdout)
    for r in report:
        base = Path("dist") / r["agent"] / r["version"]
        z = base / "claude" / f"{r['agent']}-skill.zip"
        assert zipfile.ZipFile(z).namelist()[0].startswith(r["agent"] + "/")
        for t in ("chatgpt", "gemini", "copilot"):
            assert r["targets"][t]["instructions_chars"] <= 8000
            assert (base / t / "instructions.md").exists()
