"""Content Studio evaluator: themes without names, gate, approval-only publishing, script timing, captions,
frame QA and weekly ideas."""
from __future__ import annotations

import re
from datetime import datetime

from gtm_core.agents import load_module


def setup(ctx, spec):
    for i in spec["insights"]:
        ctx.store.add_insight("meeting-intelligence", i["kind"], i["key"], i.get("value"), evidence=i.get("evidence", ""),
                              observed_at=i["observed_at"], account_id=i.get("account_id"))


def evaluate(m, spec, make_ctx) -> list[dict]:
    ctx = make_ctx(m)
    setup(ctx, spec)
    eng = load_module(m, "engine")
    jobs = load_module(m, "jobs")
    now = datetime.fromisoformat(spec["now"])
    out = []

    def add(name, ok, detail=""):
        out.append({"case": name, "passed": bool(ok), "detail": str(detail)[:400]})

    p = eng.linkedin_post(ctx, spec["post"]["topic"], now=now)
    add("post uses the matching theme", spec["post"]["expect_theme"] in [t["theme"] for t in p["themes"]], p["themes"])
    add("post never names a customer", not any(w in p["body"] for w in spec["post"]["must_not_contain"]), p["body"])
    add("post passes the Copy QA Gate", p["gate_passed"], (p["gate_score"], p["fix"]))
    add("post ends with one question", p["body"].count("?") == 1 and p["body"].rstrip().endswith("?"), p["body"])
    add("nothing posted before approval", not ctx.approvals.list(), "")
    q = eng.publish_post(ctx, p["draft_id"])
    appr = ctx.approvals.list()
    add("publish queues a social_post approval", q.get("queued_for_approval") and appr[0]["action"] == "social_post", q)
    add("no double publish", "error" in eng.publish_post(ctx, p["draft_id"]), "")
    add("empty topic rejected", "error" in eng.linkedin_post(ctx, "  "), "")

    s = spec["script"]
    v = eng.video_script(ctx, s["topic"], s["seconds"], now=now)
    c = v["checks"]
    add("script within word budget (seconds x 2.4)", c["within_budget"] and c["word_budget"] == int(s["seconds"] * 2.4), c)
    add("hook is a question within 3 seconds", c["hook_ok"] and v["sections"][0]["text"].endswith("?")
        and v["sections"][0]["end"] <= 3.0, v["sections"][0])
    beats = [x for x in v["sections"] if x["label"].startswith("beat")]
    add("2 to 4 beats and a CTA", 2 <= len(beats) <= 4 and c["has_cta"], [x["label"] for x in v["sections"]])
    add("sections are timed back to back", all(a["end"] == b["start"] for a, b in zip(v["sections"], v["sections"][1:])), "")
    add("script passes the Copy QA Gate", v["gate_passed"], (v["gate_score"], v["fix"]))
    add("out-of-range length rejected", "error" in eng.video_script(ctx, s["topic"], 400), "")

    cs = spec["captions"]
    cap = eng.captions(ctx, cs["text"], cs["seconds"])
    lines = [ln for ln in cap["srt"].splitlines() if ln and not ln.isdigit() and "-->" not in ln]
    add("caption lines at most 32 characters", all(len(ln) <= cs["max_chars"] for ln in lines), lines)
    add("labels stripped from captions", not any(re.match(r"(HOOK|BEAT|CTA):", ln) for ln in lines), lines)
    add("cue count", cap["cues"] == cs["cues"], cap["cues"])
    add("captions end at the video length", cap["cue_list"][-1]["end"] == cs["seconds"] and cap["cue_list"][0]["start"] == 0,
        cap["cue_list"])
    add("at most 2 lines per cue", all(len(q["lines"]) <= 2 for q in cap["cue_list"]), "")
    from_draft = eng.captions(ctx, str(v["draft_id"]))
    add("captions from a draft use its spoken length", from_draft["seconds"] == v["sections"][-1]["end"], from_draft["seconds"])

    fr = spec["frames"]
    good = eng.frame_qa(ctx, fr["good"], fr["width"], fr["height"])
    add("clean frames pass", good["passed"], good["issues"])
    bad = eng.frame_qa(ctx, fr["bad"], fr["width"], fr["height"])
    text = " | ".join(bad["issues"])
    add("bad frames fail", not bad["passed"] and bad["failed_frames"] == 2, text)
    for k in fr["bad_issues"]:
        add(f"frame issue found: {k}", k in text, text)

    r = jobs.weekly_content_ideas(ctx, now=now)
    add("weekly ideas ranked by mentions", r["ideas"] and r["ideas"][0]["topic"] == spec["expect"]["ideas_top"], r["ideas"])
    add("ideas only from content kinds in the last 7 days", len(r["ideas"]) == spec["expect"]["ideas_count"], r["ideas"])
    add("ideas posted to Slack", "post ideas" in ctx.slack.sent[-1]["text"], "")
    return out
