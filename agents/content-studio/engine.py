"""Content Studio engine: LinkedIn posts, short video scripts, captions and on-screen text QA.

Structure, timing, caption splitting and frame checks are deterministic. The model only writes
copy (through gtm_core.writer with template fallbacks). Publishing is a social_post approval.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

from gtm_core import copy_gate, profile, writer

DASHES = ("—", "–", " -- ")


def cfg(ctx, key, default=None):
    return ctx.manifest.config.get(key, default)


def _now(now):
    return now or datetime.now(timezone.utc)


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9'$%.,:;!?&/-]+", text or "")


def _count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", text or ""))


# ---------- facts ----------
def _val(v) -> str:
    if isinstance(v, dict):
        return " ".join(str(x) for x in v.values() if isinstance(x, (str, int, float)))
    return "" if v is None else str(v)


def insight_facts(ctx, topic: str, now: datetime | None = None, days: int | None = None, limit: int = 5) -> list[dict]:
    """Recent insights that match the topic. Only the theme (key and value) is used: account names and
    evidence quotes never go into public content."""
    days = int(days or cfg(ctx, "insight_days", 30))
    since = (_now(now) - timedelta(days=days)).isoformat()
    kinds = set(cfg(ctx, "insight_kinds", ["win_loss", "objection", "theme", "competitor", "pain"]))
    terms = {t for t in re.findall(r"[a-z]{4,}", (topic or "").lower())}
    out = []
    for r in ctx.store.insights(since_iso=since):
        if r["kind"] not in kinds:
            continue
        text = f"{r['key']} {_val(r['value'])}".lower()
        hits = sum(1 for t in terms if t in text)
        if terms and not hits:
            continue
        out.append({"kind": r["kind"], "theme": r["key"].replace("_", " "), "hits": hits})
    out.sort(key=lambda x: -x["hits"])
    seen, uniq = set(), []
    for x in out:
        if x["theme"] not in seen:
            seen.add(x["theme"])
            uniq.append({"kind": x["kind"], "theme": x["theme"]})
    return uniq[:limit]


# ---------- LinkedIn ----------
def post_template(ctx, topic: str, angle: str, facts: list[dict]) -> str:
    comp = profile.company(ctx)
    proof = (comp.get("proof_points") or [""])[0]
    proof = re.sub(r"\s*\(replace with your own\)", "", proof)
    themes = [f["theme"] for f in facts[:3]]
    heard = f"Three things we keep hearing: {', '.join(themes[:-1])} and {themes[-1]}." if len(themes) > 1 else \
        (f"One thing we keep hearing: {themes[0]}." if themes else "")
    lines = [topic.rstrip(".") + ".", ""]
    if angle:
        lines += [angle.rstrip(".") + ".", ""]
    if heard:
        lines += [heard, ""]
    if proof:
        lines += [f"What helped one team: {proof.rstrip('.')}.", ""]
    lines.append("How does your team handle this?")
    return "\n".join(lines)


def linkedin_post(ctx, topic: str, angle: str = "", source: str = "", now: datetime | None = None) -> dict:
    if not (topic or "").strip():
        return {"error": "topic required"}
    facts = insight_facts(ctx, topic, now)
    comp = profile.company(ctx)
    d = writer.write(ctx, "LinkedIn post", {"topic": topic, "angle": angle, "source": source, "themes": facts,
                                           "proof_points": comp.get("proof_points", []), "company": comp.get("company")},
                     "First line is the hook. Short lines. One idea. End with one question. No hashtags beyond two. "
                     "Never name a customer or prospect.", post_template(ctx, topic, angle, facts),
                     max_words=int(cfg(ctx, "post_max_words", 180)))
    did = ctx.store.add_draft(ctx.manifest.id, "linkedin_post", d.body, gate_score=d.score, gate_passed=d.passed,
                              source=d.source, meta={"topic": topic, "angle": angle, "source": source,
                                                     "themes": [f["theme"] for f in facts]})
    return {"draft_id": did, "themes": facts, **d.as_dict()}


def publish_post(ctx, draft_id: int, channel: str = "linkedin") -> dict:
    rows = ctx.store.query("SELECT * FROM drafts WHERE id=? AND agent=?", (int(draft_id), ctx.manifest.id))
    if not rows:
        return {"error": f"draft {draft_id} not found"}
    d = rows[0]
    if d["kind"] != "linkedin_post":
        return {"error": f"draft {draft_id} is a {d['kind']}, not a post"}
    if not d["gate_passed"]:
        return {"error": "draft did not pass the Copy QA Gate; rewrite it first"}
    if d["status"] in ("queued", "sent"):
        return {"error": f"draft {draft_id} is already {d['status']}"}
    rid = ctx.request_approval("social_post", {"channel": channel, "body": d["body"], "draft_id": d["id"]},
                               summary=f"{channel} post: {d['body'].splitlines()[0][:80]}")
    ctx.store.execute("UPDATE drafts SET status=?, approval_id=? WHERE id=?", ("queued", rid, d["id"]))
    return {"queued_for_approval": rid}


# ---------- video ----------
def budget(ctx, seconds: float) -> dict:
    wps = float(cfg(ctx, "words_per_second", 2.4))
    hook_s = float(cfg(ctx, "hook_seconds", 3))
    return {"words": int(seconds * wps), "hook_words": int(hook_s * wps), "wps": wps}


def _beats(seconds: float) -> int:
    return max(2, min(4, int(seconds // 12)))


def script_template(ctx, topic: str, seconds: float, facts: list[dict]) -> list[dict]:
    comp = profile.company(ctx)
    vps = comp.get("value_props", [])
    b = budget(ctx, seconds)
    words = topic.rstrip("?.").split()
    if len(words) <= b["hook_words"]:
        hook = " ".join(words) + "?"
    elif facts and len(facts[0]["theme"].split()) <= b["hook_words"] - 2:
        hook = f"Still fighting {facts[0]['theme']}?"
    else:
        hook = "Sound familiar?"
    beats = []
    for f in facts:
        beats.append(f"We keep hearing about {f['theme']}.")
    for v in vps:
        beats.append(f"{v.get('pain', '').rstrip('.')}. The fix: {v.get('outcome', '').rstrip('.')[:1].lower()}"
                     f"{v.get('outcome', '').rstrip('.')[1:]}.")
    beats = beats[: _beats(seconds)] or ["Here is what changes when the list builds itself."]
    cta = "Follow for part two."
    return [{"label": "hook", "text": hook}] + [{"label": f"beat {i}", "text": t} for i, t in enumerate(beats, 1)] + \
        [{"label": "cta", "text": cta}]


def parse_script(text: str) -> list[dict] | None:
    out = []
    for line in (text or "").splitlines():
        m = re.match(r"^\s*(HOOK|BEAT(?:\s*\d+)?|CTA)\s*:\s*(.+)$", line.strip(), re.I)
        if m:
            lab = m.group(1).lower()
            out.append({"label": "hook" if lab == "hook" else "cta" if lab == "cta" else f"beat {len(out)}",
                        "text": m.group(2).strip()})
    if not out or out[0]["label"] != "hook" or out[-1]["label"] != "cta" or len(out) < 3:
        return None
    return out


def time_sections(sections: list[dict], wps: float) -> list[dict]:
    t = 0.0
    for s in sections:
        dur = round(max(1.0, _count(s["text"]) / wps), 2)
        s["start"], s["end"] = round(t, 2), round(t + dur, 2)
        t += dur
    return sections


def script_checks(ctx, sections: list[dict], seconds: float) -> dict:
    b = budget(ctx, seconds)
    words = sum(_count(s["text"]) for s in sections)
    hook = _count(sections[0]["text"]) if sections else 0
    return {"words": words, "word_budget": b["words"], "within_budget": words <= b["words"],
            "hook_words": hook, "hook_budget": b["hook_words"], "hook_ok": hook <= b["hook_words"],
            "has_cta": bool(sections) and sections[-1]["label"] == "cta"}


def video_script(ctx, topic: str, seconds: float = 45, now: datetime | None = None) -> dict:
    if not (topic or "").strip():
        return {"error": "topic required"}
    seconds = float(seconds)
    if not 10 <= seconds <= 180:
        return {"error": "seconds must be between 10 and 180"}
    b = budget(ctx, seconds)
    facts = insight_facts(ctx, topic, now)
    tpl = script_template(ctx, topic, seconds, facts)
    fallback = "\n".join(f"{'HOOK' if s['label'] == 'hook' else 'CTA' if s['label'] == 'cta' else 'BEAT'}: {s['text']}"
                         for s in tpl)
    d = writer.write(ctx, "short video script", {"topic": topic, "themes": facts, "seconds": seconds,
                                                "value_props": profile.company(ctx).get("value_props", [])},
                     f"Lines start with HOOK:, BEAT: or CTA:. Hook under {b['hook_words']} words and a question. "
                     f"{_beats(seconds)} beats. Whole script under {b['words']} words. Spoken, plain words.",
                     fallback, max_words=b["words"])
    sections = parse_script(d.body)
    source = d.source
    if sections is None or not all(script_checks(ctx, sections, seconds)[k] for k in ("within_budget", "hook_ok")):
        sections, source = tpl, "template"
    sections = time_sections(sections, b["wps"])
    checks = script_checks(ctx, sections, seconds)
    body = "\n".join(f"{s['label'].upper()}: {s['text']}" for s in sections)
    gate = copy_gate.check(" ".join(s["text"] for s in sections), max_words=b["words"],
                           pass_mark=int(cfg(ctx, "pass_mark", 32)))
    did = ctx.store.add_draft(ctx.manifest.id, "video_script", body, gate_score=gate.score, gate_passed=gate.passed,
                              source=source, meta={"topic": topic, "seconds": seconds, "sections": sections})
    return {"draft_id": did, "seconds": seconds, "sections": sections, "checks": checks, "gate_score": gate.score,
            "gate_passed": gate.passed, "fix": gate.failures(), "source": source}


# ---------- captions ----------
def caption_lines(text: str, max_chars: int = 32) -> list[str]:
    lines, cur = [], ""
    for w in (text or "").split():
        if not cur:
            cur = w
        elif len(cur) + 1 + len(w) <= max_chars:
            cur += " " + w
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _ts(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def srt(text: str, seconds: float, max_chars: int = 32, max_lines: int = 2) -> tuple[str, list[dict]]:
    lines = caption_lines(text, max_chars)
    cues = [lines[i:i + max_lines] for i in range(0, len(lines), max_lines)]
    total = sum(_count(" ".join(c)) for c in cues) or 1
    t, out, parts = 0.0, [], []
    for i, c in enumerate(cues, 1):
        dur = seconds * _count(" ".join(c)) / total
        end = seconds if i == len(cues) else t + dur
        out.append({"index": i, "start": round(t, 3), "end": round(end, 3), "lines": c})
        parts.append(f"{i}\n{_ts(t)} --> {_ts(end)}\n" + "\n".join(c) + "\n")
        t = end
    return "\n".join(parts), out


def spoken_text(body: str) -> str:
    return " ".join(re.sub(r"^\s*(HOOK|BEAT(?:\s*\d+)?|CTA)\s*:\s*", "", ln, flags=re.I).strip()
                    for ln in (body or "").splitlines() if ln.strip())


def captions(ctx, script_or_draft_id, seconds: float | None = None) -> dict:
    text, secs = str(script_or_draft_id), seconds
    if re.fullmatch(r"\d+", text.strip()):
        rows = ctx.store.query("SELECT * FROM drafts WHERE id=?", (int(text),))
        if not rows:
            return {"error": f"draft {text} not found"}
        meta = json.loads(rows[0]["meta"] or "{}")
        text = spoken_text(rows[0]["body"])
        spoken = (meta.get("sections") or [{}])[-1].get("end")
        secs = secs or spoken or meta.get("seconds")
    else:
        text = spoken_text(text)
    if not text:
        return {"error": "no text to caption"}
    if not secs:
        secs = round(_count(text) / float(cfg(ctx, "words_per_second", 2.4)), 2)
    out, cues = srt(text, float(secs), int(cfg(ctx, "caption_max_chars", 32)), int(cfg(ctx, "caption_max_lines", 2)))
    return {"seconds": float(secs), "cues": len(cues), "srt": out, "cue_list": cues}


# ---------- frame QA ----------
def frame_qa(ctx, frames: list[dict], width: int = 1080, height: int = 1920, duration: float | None = None) -> dict:
    side = float(cfg(ctx, "safe_side_pct", 10)) / 100
    top = float(cfg(ctx, "safe_top_pct", 0)) / 100
    bottom = float(cfg(ctx, "safe_bottom_pct", 15)) / 100
    max_chars = int(cfg(ctx, "frame_max_chars_per_line", 32))
    per_word = float(cfg(ctx, "min_seconds_per_word", 0.3))
    banned = copy_gate.DEFAULT_BANNED
    fs = sorted(frames or [], key=lambda f: float(f.get("t", 0)))
    results, issues = [], []
    for i, f in enumerate(fs):
        bad = []
        x, y, w, h = (float(f.get(k, 0)) for k in ("x", "y", "w", "h"))
        if x < width * side or x + w > width * (1 - side):
            bad.append("text outside the side safe zone")
        if y < height * top or y + h > height * (1 - bottom):
            bad.append("text outside the top or bottom safe zone")
        text = str(f.get("text") or "")
        for ln in text.splitlines() or [""]:
            if len(ln) > max_chars:
                bad.append(f"line over {max_chars} characters ({len(ln)})")
        end = float(f["end"]) if f.get("end") is not None else (float(fs[i + 1]["t"]) if i + 1 < len(fs) else duration)
        if end is not None:
            need = round(_count(text) * per_word, 2)
            shown = round(end - float(f.get("t", 0)), 2)
            if shown < need:
                bad.append(f"on screen {shown}s, needs {need}s to read")
        low = text.lower()
        hits = [b for b in banned if re.search(r"(?<![a-z])" + re.escape(b) + r"(?![a-z])", low)]
        if hits:
            bad.append("banned words: " + ", ".join(hits))
        if any(d in text for d in DASHES):
            bad.append("dash used; rewrite without it")
        results.append({"t": f.get("t"), "text": text, "passed": not bad, "issues": bad})
        issues += [f"t={f.get('t')}: {b}" for b in bad]
    return {"passed": not issues, "frames": len(fs), "failed_frames": sum(1 for r in results if not r["passed"]),
            "issues": issues, "results": results}


# ---------- ideas ----------
def content_ideas(ctx, now: datetime | None = None, days: int = 7, n: int = 5) -> list[dict]:
    since = (_now(now) - timedelta(days=days)).isoformat()
    kinds = set(cfg(ctx, "insight_kinds", ["win_loss", "objection", "theme", "competitor", "pain"]))
    c = Counter((r["kind"], r["key"]) for r in ctx.store.insights(since_iso=since) if r["kind"] in kinds)
    label = {"objection": "Answer the objection", "win_loss": "What decided a deal", "competitor": "How we compare on",
             "pain": "The problem behind", "theme": "What buyers asked about"}
    return [{"topic": f"{label.get(k, 'On')}: {key.replace('_', ' ')}", "kind": k, "mentions": m}
            for (k, key), m in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]
