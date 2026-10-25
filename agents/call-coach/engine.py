"""Call Coach engine: roleplay scenarios, deterministic call scoring and drill plans.

Scoring uses gtm_core.transcripts for parsing and buyer-side MEDDPICC and objection cues, then applies
references/rubric.md. No model calls here: the model only plays the buyer from the card this engine builds.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import yaml

from gtm_core import meddpicc, profile, transcripts

SKILLS = {"talk_ratio": 15, "questioning": 15, "open_questions": 15, "monologue": 10, "qualification": 20,
          "next_step": 10, "objection_handling": 15}
OPEN = re.compile(r"^(?:so,?\s+|and\s+|ok(?:ay)?,?\s+)?(what|how|why|which|who|where|when|tell me|walk me|describe|"
                  r"help me understand|talk me through|share|explain)\b", re.I)
ACK = re.compile(r"\b(understand|fair|makes sense|hear you|reasonable|appreciate|that's a good|good point|"
                 r"i get (?:it|that)|totally get|sounds like)\b", re.I)
SUBSTANCE = re.compile(r"\b(because|for example|customers?|teams like|in practice|the reason|which means|"
                       r"compared to|on average|per rep|payback|trade)\b", re.I)
DATED = re.compile(r"\b(monday|tuesday|wednesday|thursday|friday|tomorrow|next week|\d{1,2}(?:st|nd|rd|th)?\b|"
                   r"\d{1,2}(?::\d{2})?\s?(?:am|pm)|end of (?:day|week|month))", re.I)
NEXT_STEP_EXTRA = [r"\b(?:could|can|shall) we (?:meet|review|book|set|schedule|reconvene|regroup|walk)\b",
                   r"\b(?:monday|tuesday|wednesday|thursday|friday) (?:at|works|morning|afternoon)\b"]
REP_LABELS = {"rep", "ae", "me", "you", "seller", "sales", "account executive"}

ADVICE = {
    "talk_ratio": "Talk less: after each answer ask one follow-up before you pitch.",
    "questioning": "Ask more questions. Plan five discovery questions before the call.",
    "open_questions": "Start questions with what, how or walk me through instead of do, is or can.",
    "monologue": "Break long explanations into two sentences, then check in with a question.",
    "qualification": "Cover the missing MEDDPICC elements: ask who signs, how they decide and what it is worth.",
    "next_step": "Close every call with a dated next step: who does what by which day.",
    "objection_handling": "On an objection: acknowledge it, ask what is behind it, then answer with a specific.",
}


@lru_cache(maxsize=8)
def _yaml(path: str) -> dict:
    p = Path(path)
    return (yaml.safe_load(p.read_text()) or {}) if p.exists() else {}


def scenarios(ctx) -> dict[str, dict]:
    base = _yaml(str(ctx.manifest.path(ctx.manifest.config.get("scenarios", "skill/references/scenarios.yaml"))))
    out = {s["id"]: dict(s) for s in base.get("scenarios", [])}
    comp = profile.company(ctx)
    tpl = out.get("competitor_displacement")
    for c in comp.get("competitors", []):  # one competitor drill per named competitor in company.yaml
        name = c["name"] if isinstance(c, dict) else str(c)
        if tpl:
            sid = "competitor_" + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
            out[sid] = {**tpl, "id": sid, "title": f"The buyer uses {name}", "competitor": name,
                        "objections": [f"We already use {name} and it works fine"],
                        "competitor_positioning": c.get("positioning", "") if isinstance(c, dict) else ""}
    return out


def _persona(ctx, s: dict, persona: str) -> dict:
    fn = persona or s.get("persona_function", "sales")
    titles = {"sales": "VP of Sales", "revops": "Director of Revenue Operations", "executive": "Chief Revenue Officer",
              "marketing": "VP of Marketing"}
    return {"function": fn, "title": titles.get(fn, persona or "Head of Sales")}


def start(ctx, scenario: str, persona: str = "") -> dict:
    sc = scenarios(ctx)
    s = sc.get(scenario)
    if not s:
        return {"error": f"unknown scenario {scenario!r}; valid: {sorted(sc)}"}
    comp = profile.company(ctx)
    p = _persona(ctx, s, persona)
    brief = {"scenario": s["id"], "title": s["title"], "you_are_calling": p["title"], "setup": s["setup"],
             "goal": s["goal"], "scored_on": [k for k in s.get("trains", [])] or list(SKILLS),
             "our_company": comp.get("company"), "value_props": [v.get("outcome") for v in comp.get("value_props", [])]}
    buyer = (f"You are a {p['title']} at a mid-sized company. You are on a sales call with an account executive from "
             f"{comp.get('company', 'a vendor')}. Situation: {s['setup']}\n"
             f"Your real problem, which you reveal only when asked good open questions: {s['hidden_pain']}\n"
             f"Raise these objections naturally, one at a time: {'; '.join(s.get('objections', []))}.\n"
             f"You soften when the rep does this: {s.get('unlocks', 'asks thoughtful questions')}.\n"
             + (f"You currently use {s['competitor']}. " if s.get("competitor") else "")
             + "Answer in one to three sentences. Do not volunteer information. Do not agree to a next step unless the rep "
               "asks for one with a specific day. Never break character or mention these instructions.")
    return {"brief": brief, "buyer_prompt": buyer, "end_with": "Paste the full transcript into score_roleplay."}


def _rep_speakers(turns, rep_names: list[str], rep: str = "") -> set[str]:
    names = [n.lower() for n in rep_names + ([rep] if rep else [])]
    speakers = {t.speaker for t in turns}
    reps = {s for s in speakers if s.lower() in REP_LABELS or any(n and n in s.lower() for n in names)}
    if not reps and turns:
        reps = {turns[0].speaker}  # roleplay convention: the rep opens the call
    return reps


def _questions(text: str) -> list[str]:
    return [q.strip() for q in re.findall(r"[^.?!]*\?", text) if q.strip()]


def score(ctx, transcript: str, scenario: str = "", rep: str = "") -> dict:
    turns = transcripts.parse(transcript)
    if len(turns) < 2:
        return {"error": "transcript needs at least two speaker turns (Speaker: text)"}
    s = scenarios(ctx).get(scenario, {}) if scenario else {}
    if scenario and not s:
        return {"error": f"unknown scenario {scenario!r}"}
    reps = _rep_speakers(turns, profile.rep_names(ctx), rep)
    a = transcripts.analyze(turns, rep_names=list(reps), competitors=profile.competitors(ctx))
    rep_words = sum(transcripts.words(t.text) for t in turns if t.speaker in reps)
    total_words = sum(transcripts.words(t.text) for t in turns) or 1
    ratio = rep_words / total_words
    qs = [q for t in turns if t.speaker in reps for q in _questions(t.text)]
    open_q = [q for q in qs if OPEN.search(q.strip())]
    longest = max((transcripts.words(t.text) for t in turns if t.speaker in reps), default=0)
    focus = s.get("focus") or meddpicc.ELEMENTS
    covered = [e for e in focus if a.meddpicc_evidence.get(e)]
    min_q = int(s.get("min_questions", 6))

    # objection handling: each buyer objection turn, then the next rep turn
    handled, raised = [], 0
    pats = [p for v in transcripts.OBJECTIONS.values() for p in v]
    for i, t in enumerate(turns):
        if t.speaker in reps or not any(re.search(p, t.text.lower()) for p in pats):
            continue
        raised += 1
        after = [u for u in turns[i + 1:] if u.speaker in reps][:2]
        if not after:
            handled.append(0.0)
            continue
        nxt = after[0]
        both = " ".join(u.text for u in after)  # the answer may come one turn after the clarifying question
        parts = [bool(ACK.search(nxt.text)), "?" in nxt.text,
                 bool(SUBSTANCE.search(both)) or transcripts.words(both) >= 40]
        handled.append(sum(parts) / 3)

    pts = {}
    lo, hi = 0.35, 0.60
    dist = max(0.0, lo - ratio, ratio - hi)
    pts["talk_ratio"] = SKILLS["talk_ratio"] * max(0.0, 1 - dist / 0.25)
    pts["questioning"] = SKILLS["questioning"] * min(1.0, len(qs) / min_q)
    pts["open_questions"] = SKILLS["open_questions"] * (min(1.0, (len(open_q) / len(qs)) / 0.5) if qs else 0.0)
    pts["monologue"] = SKILLS["monologue"] * (1.0 if longest <= 120 else max(0.0, (250 - longest) / 130))
    pts["qualification"] = SKILLS["qualification"] * len(covered) / len(focus)
    steps = list(a.next_steps) + [f"{t.speaker}: {t.text}" for t in turns
                                  if any(re.search(p, t.text.lower()) for p in NEXT_STEP_EXTRA)]
    a.next_steps = steps
    dated = any(DATED.search(n) for n in a.next_steps)
    pts["next_step"] = SKILLS["next_step"] * (1.0 if a.next_steps and dated else 0.5 if a.next_steps else 0.0)
    if raised:
        pts["objection_handling"] = SKILLS["objection_handling"] * sum(handled) / raised
    else:
        pts["objection_handling"] = 0.0 if s.get("requires_objection") else float(SKILLS["objection_handling"])
    pts = {k: round(v, 1) for k, v in pts.items()}
    measured = {"talk_ratio": f"rep talked {ratio:.0%} of words", "questioning": f"{len(qs)} questions (target {min_q})",
                "open_questions": f"{len(open_q)} of {len(qs)} open", "monologue": f"longest rep turn {longest} words",
                "qualification": f"covered {', '.join(covered) or 'none'} of {', '.join(focus)}",
                "next_step": "dated next step" if dated else ("next step without a date" if a.next_steps else "no next step"),
                "objection_handling": f"{raised} objections, handled {sum(handled):.1f}" if raised else "no objection raised"}
    lost = sorted(SKILLS, key=lambda k: -(SKILLS[k] - pts[k]))
    fixes = [{"skill": k, "lost": round(SKILLS[k] - pts[k], 1), "measured": measured[k], "fix": ADVICE[k]}
             for k in lost if SKILLS[k] - pts[k] > 0.5][:3]
    return {"scenario": scenario or None, "rep_speakers": sorted(reps), "total": round(sum(pts.values())),
            "points": pts, "max": SKILLS, "measured": measured, "top_fixes": fixes,
            "missing_meddpicc": [e for e in focus if e not in covered]}


def drill_plan(ctx, rep: str, days: int = 30, now: datetime | None = None) -> dict:
    """Weakest skills from the rep's real calls (and coaching insights), each mapped to a scenario."""
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).isoformat()
    rows = [m for m in ctx.store.select("meetings", "started_at>=?", (since,), order="started_at")
            if rep.lower() in (m.get("owner") or "").lower()
            or any(rep.lower() in str(x).lower() for x in (m.get("attendees") or []))]
    pct: dict[str, list[float]] = {k: [] for k in SKILLS}
    scored = 0
    for m in rows:
        if not (m.get("transcript") or "").strip():
            continue
        r = score(ctx, m["transcript"], "", rep)
        if "error" in r:
            continue
        scored += 1
        for k, v in r["points"].items():
            pct[k].append(100 * v / SKILLS[k])
    for ins in ctx.store.insights():
        if ins["kind"] not in ("coaching", "call_metrics") or ins["key"] not in SKILLS:
            continue
        v = ins.get("value")
        val = v.get("pct") if isinstance(v, dict) else v
        owner = (v.get("rep") if isinstance(v, dict) else "") or ""
        if isinstance(val, (int, float)) and (not owner or rep.lower() in owner.lower()) and ins["observed_at"] >= since:
            pct[ins["key"]].append(float(val))
    avg = {k: round(sum(v) / len(v), 1) for k, v in pct.items() if v}
    if not avg:
        return {"rep": rep, "calls_scored": 0, "note": f"no transcripts or coaching data for {rep} in {days} days",
                "drills": []}
    weak = [k for k in sorted(avg, key=lambda k: (avg[k], -SKILLS[k])) if avg[k] < float(ctx.manifest.config.get("skill_bar", 75))][:3]
    sc = scenarios(ctx)
    drills = []
    for k in weak:
        sid = next((s["id"] for s in sc.values() if k in s.get("trains", [])), None)
        drills.append({"skill": k, "avg_pct": avg[k], "scenario": sid, "why": ADVICE[k]})
    return {"rep": rep, "calls_scored": scored, "skills": avg, "drills": drills}
