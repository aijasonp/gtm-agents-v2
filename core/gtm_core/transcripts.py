"""Meeting transcript parsing and rule-based call analysis.

Accepts plain "Speaker: text" transcripts, WebVTT/SRT exports (Zoom, Teams, Meet,
Gong, Fathom and most notetakers export one of these) and JSON lists of
{speaker, text, start}. Everything here is deterministic; models only add judgment
on top (see agents/meeting-intelligence).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

TS = r"\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?"


@dataclass
class Turn:
    speaker: str
    text: str
    start: float | None = None


def _secs(ts: str | None) -> float | None:
    if not ts:
        return None
    parts = re.split(r"[:]", ts.replace(",", "."))
    try:
        vals = [float(p) for p in parts]
    except ValueError:
        return None
    while len(vals) < 3:
        vals.insert(0, 0.0)
    return vals[0] * 3600 + vals[1] * 60 + vals[2]


def parse(raw: str) -> list[Turn]:
    raw = (raw or "").strip()
    if not raw:
        return []
    if raw[0] in "[{":
        try:
            data = json.loads(raw)
            items = data if isinstance(data, list) else data.get("turns") or data.get("transcript") or []
            return [Turn(str(i.get("speaker") or i.get("name") or "Unknown"), str(i.get("text") or ""),
                         i.get("start") if isinstance(i.get("start"), (int, float)) else _secs(str(i.get("start") or "")))
                    for i in items if isinstance(i, dict) and i.get("text")]
        except json.JSONDecodeError:
            pass
    turns: list[Turn] = []
    pending_start = None
    for line in raw.splitlines():
        line = line.strip()
        if not line or line == "WEBVTT" or line.isdigit():
            continue
        m = re.match(rf"^({TS})\s*-->\s*({TS})", line)
        if m:
            pending_start = _secs(m.group(1))
            continue
        m = re.match(r"^<v\s+([^>]+)>(.*?)(?:</v>)?$", line)  # VTT voice tag
        if not m:
            m = re.match(rf"^(?:\[?({TS})\]?\s+)?([A-Z][\w .'\-]{{0,40}}?)\s*:\s+(.+)$", line)
            if m:
                pending_start = _secs(m.group(1)) if m.group(1) else pending_start
                speaker, text = m.group(2), m.group(3)
            else:
                if turns:  # continuation line
                    turns[-1].text += " " + line
                continue
        else:
            speaker, text = m.group(1), m.group(2)
        speaker, text = speaker.strip(), text.strip()
        if turns and turns[-1].speaker == speaker:
            turns[-1].text += " " + text
        else:
            turns.append(Turn(speaker, text, pending_start))
        pending_start = None
    return turns


def words(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", text))


NEXT_STEP = [r"\bnext step", r"\bfollow[- ]up\b", r"\bsend (?:over|you|the)\b", r"\bschedule\b", r"\bset up (?:a|time)\b",
             r"\bby (?:monday|tuesday|wednesday|thursday|friday|end of (?:day|week|month))\b",
             r"\bnext (?:week|call|meeting)\b", r"\bloop in\b", r"\bintroduce\b", r"\bi'?ll (?:send|share|get)\b"]
PRICING = [r"\bpric(?:e|ing)\b", r"\bbudget\b", r"\bcost\b", r"\bquote\b", r"\bdiscount\b", r"\bper (?:seat|user)\b",
           r"\bcontract\b", r"\$\s?\d"]
OBJECTIONS = {
    "price": [r"too expensive", r"\bcost(?:s)? too\b", r"\bno budget\b", r"budget is (?:tight|frozen)", r"cheaper"],
    "timing": [r"not (?:a )?(?:priority|right now)", r"next (?:quarter|year)", r"bad timing", r"revisit (?:in|later)"],
    "authority": [r"not my (?:call|decision)", r"need to (?:check|run it by)", r"my boss", r"leadership (?:has|needs) to"],
    "competition": [r"already (?:use|using|have)", r"happy with", r"evaluating (?:other|another)", r"\bincumbent\b"],
    "need": [r"don'?t (?:really )?need", r"not a problem for us", r"works fine", r"not sure (?:we|it)"],
    "security": [r"security review", r"\bsoc ?2\b", r"\bgdpr\b", r"data (?:privacy|residency)", r"infosec"],
    "integration": [r"integrat", r"\bapi\b", r"work with our", r"\bsso\b"],
}
MEDDPICC_CUES = {
    "metrics": [r"\b\d+%", r"\bsave\b.*\b(?:hours|time|money)\b", r"\broi\b", r"\breduce\b", r"\bincrease\b"],
    "economic_buyer": [r"\bsign(?:s|ed)? off\b", r"\bfinal (?:say|decision)\b", r"\bbudget owner\b", r"\bcfo\b",
                       r"\bapprov(?:e|al)\b"],
    "decision_criteria": [r"\bcriteria\b", r"\bmust[- ]have\b", r"\brequirement", r"\bneeds? to (?:support|have)\b"],
    "decision_process": [r"\bprocess\b", r"\bsteps?\b.*\bdecid", r"\bcommittee\b", r"\bpilot\b", r"\bproof of\b",
                         r"\bevaluation\b"],
    "paper_process": [r"\bprocurement\b", r"\blegal\b", r"\bmsa\b", r"\bredline", r"\bpurchase order\b", r"\bsecurity review\b",
                      r"\bvendor (?:onboarding|form)\b"],
    "identify_pain": [r"\bproblem\b", r"\bstruggl", r"\bpain\b", r"\bfrustrat", r"\bbroken\b", r"\bmanual(?:ly)?\b",
                      r"\btakes (?:too long|forever)\b", r"\bby hand\b", r"\bspreadsheets?\b", r"\bstale\b"],
    "champion": [r"\bi'?ll (?:push|champion|advocate|sell (?:it|this) internally)\b", r"\bon board\b",
                 r"\bi'?m (?:a fan|convinced)\b", r"\bintroduce you to\b"],
    "competition": [r"\bcompetitor", r"\balternative", r"\bevaluating\b", r"\balready (?:use|using)\b"],
}


@dataclass
class CallAnalysis:
    duration_min: float | None
    speakers: dict[str, int]
    rep_talk_ratio: float | None
    questions_by_rep: int
    longest_monologue_words: int
    longest_monologue_speaker: str
    next_steps: list[str] = field(default_factory=list)
    pricing_mentions: list[str] = field(default_factory=list)
    objections: dict[str, list[str]] = field(default_factory=dict)
    competitors: dict[str, list[str]] = field(default_factory=dict)
    meddpicc_evidence: dict[str, list[str]] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _hits(turns: list[Turn], pats: list[str], limit: int = 5, speakers: set[str] | None = None) -> list[str]:
    out = []
    for t in turns:
        if speakers is not None and t.speaker not in speakers:
            continue
        for s in _sentences(t.text):
            if any(re.search(p, s.lower()) for p in pats):
                q = f"{t.speaker}: {s}"
                if q not in out:
                    out.append(q[:300])
                if len(out) >= limit:
                    return out
    return out


def analyze(turns: list[Turn], rep_names: list[str] | None = None, competitors: list[str] | None = None) -> CallAnalysis:
    """Rule-based call analysis. rep_names marks your side; everyone else is the buyer side."""
    counts: dict[str, int] = {}
    for t in turns:
        counts[t.speaker] = counts.get(t.speaker, 0) + words(t.text)
    total = sum(counts.values()) or 1
    reps = {s for s in counts if any(r.lower() in s.lower() for r in (rep_names or []))}
    buyers = set(counts) - reps
    ratio = round(sum(counts[s] for s in reps) / total, 2) if reps else None
    questions = sum(t.text.count("?") for t in turns if t.speaker in reps)
    longest, who = 0, ""
    for t in turns:
        if words(t.text) > longest:
            longest, who = words(t.text), t.speaker
    starts = [t.start for t in turns if t.start is not None]
    duration = round((max(starts) - min(starts)) / 60, 1) if len(starts) >= 2 else None

    comp_hits = {}
    for c in competitors or []:
        pat = r"(?<![a-z0-9])" + re.escape(c.lower()) + r"(?![a-z0-9])"
        q = _hits(turns, [pat], limit=3)
        if q:
            comp_hits[c] = q
    objections = {k: q for k, pats in OBJECTIONS.items() if (q := _hits(turns, pats, 3, buyers or None))}
    evidence = {k: q for k, pats in MEDDPICC_CUES.items() if (q := _hits(turns, pats, 3, buyers or None))}
    if comp_hits:
        evidence.setdefault("competition", [])
        evidence["competition"] = (evidence["competition"] + [v[0] for v in comp_hits.values()])[:3]

    a = CallAnalysis(duration, counts, ratio, questions, longest, who,
                     _hits(turns, NEXT_STEP, 6), _hits(turns, PRICING, 4), objections, comp_hits, evidence)
    if ratio is not None and ratio > 0.65:
        a.flags.append(f"Rep talked {int(ratio * 100)}% of the call (aim for under 60%)")
    if reps and questions < 3:
        a.flags.append(f"Only {questions} questions asked by the rep side")
    if longest > 250 and who in reps:
        a.flags.append(f"{who} spoke {longest} words in one stretch")
    if not a.next_steps:
        a.flags.append("No clear next step heard on the call")
    return a
