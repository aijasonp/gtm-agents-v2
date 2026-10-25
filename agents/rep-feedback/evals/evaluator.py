"""Rep Feedback evaluator: routing, sanitizing, Rules-section insertion, grouping and library refusal."""
from __future__ import annotations

from gtm_core.agents import load_module


def evaluate(m, spec, make_ctx) -> list[dict]:
    ctx = make_ctx(m)
    eng = load_module(m, "engine")
    ex, out = spec["expect"], []

    def add(name, ok, detail=""):
        out.append({"case": name, "passed": bool(ok), "detail": str(detail)[:400]})

    ids = []
    for f in spec["feedback"]:
        r = eng.submit(ctx, f["agent"], f["text"])
        ids.append(r.get("feedback_id"))
        add(f"route: {f['text'][:40]}", r.get("target") == f["expect"], r)
    add("unknown or library agent refused", "error" in eng.submit(ctx, ex["unknown_agent"], "x"), "")
    add("library path never a target", not eng.safe_target("library/sales-skills/skills/sales-cadence/SKILL.md")
        and not eng.safe_target("agents/x/../../library/a.md"), "")
    s = eng.sanitize(spec["feedback"][ex["em_dash_removed_from"]]["text"])
    add("em dash removed", "\u2014" not in s and "\u2013" not in s, s)
    add("long text capped", len(eng.sanitize("word " * 100, 200)) <= 203, "")
    mixed = eng.propose(ctx, [ids[i] for i in ex["mixed_targets_refused"]])
    add("mixed targets refused", "error" in mixed and len(mixed.get("targets", [])) == 2, mixed)
    p = eng.propose(ctx, ids[:2])
    added = [l for l in p.get("patch", "").splitlines() if l.startswith("+- ")]
    add("two bullets added to Rules", len(added) == ex["rules_section_gets"], p.get("patch", "")[:300])
    txt = "# A\n\n## Rules\n\n- one\n\n## Output\n\nx\n"
    new = eng.apply_rules(txt, "agents/a/skill/SKILL.md", ["two"])
    add("inserted at end of Rules, before next heading", new == "# A\n\n## Rules\n\n- one\n- two\n\n## Output\n\nx\n", new)
    add("yaml gets a review comment", eng.apply_rules("a: 1\n", "config/icp.yaml", ["x"]).endswith("# Rep feedback, encode then remove: x\n"), "")
    q = eng.open_pr(ctx, p["proposal_id"])
    add("PR waits for approval", q.get("queued_for_approval") and ctx.approvals.list()[0]["action"] == "github_pr", q)
    return out
