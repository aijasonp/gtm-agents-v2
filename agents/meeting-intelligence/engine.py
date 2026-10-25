"""Meeting Intelligence engine: rule-based call analysis first, model summary on top when a key exists."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from gtm_core import meddpicc, profile, transcripts, writer

SCHEMA_HINT = ('{"summary": "two sentences", "pain": "buyer pain in their words", '
               '"next_steps": ["owner: action by when"], '
               '"meddpicc": {"metrics": "quote", "economic_buyer": "quote", "decision_criteria": "quote", '
               '"decision_process": "quote", "paper_process": "quote", "identify_pain": "quote", '
               '"champion": "quote", "competition": "quote"}}')


def _now(now):
    return (now or datetime.now(timezone.utc)).replace(microsecond=0)


def _strip_speaker(q: str) -> str:
    return q.split(": ", 1)[1] if ": " in q else q


def analyze_text(ctx, transcript: str) -> dict:
    turns = transcripts.parse(transcript or "")
    a = transcripts.analyze(turns, rep_names=profile.rep_names(ctx), competitors=profile.competitors(ctx))
    out = a.as_dict()
    out["turns"] = len(turns)
    out["pain_context"] = pain_context(turns, out.get("meddpicc_evidence", {}).get("identify_pain", []))
    return out


def pain_context(turns, quotes: list[str]) -> str:
    """The buyer turn behind the strongest pain quote. A short cue sentence ("it is a real problem")
    says little on its own, so use the whole turn it came from, trimmed."""
    best = ""
    for q in quotes:
        speaker, _, sent = q.partition(": ")
        for t in turns:
            if t.speaker == speaker and sent and sent in t.text and len(t.text) > len(best):
                best = t.text
    return best[:280].rsplit(" ", 1)[0] + "..." if len(best) > 280 else best


def rule_summary(meeting: dict, a: dict) -> dict:
    ev = a.get("meddpicc_evidence", {})
    pain = a.get("pain_context") or (_strip_speaker(ev["identify_pain"][0]) if ev.get("identify_pain") else "")
    nxt = [_strip_speaker(s) for s in a.get("next_steps", [])][:4]
    parts = []
    if pain:
        parts.append(f"Pain: {pain}")
    if ev.get("economic_buyer"):
        parts.append(f"Approval: {_strip_speaker(ev['economic_buyer'][0])}")
    if a.get("objections"):
        parts.append("Objections: " + ", ".join(sorted(a["objections"])))
    text = " ".join(parts) or "No pain, approval or objection stated on the call."
    return {"headline": text, "pain": pain, "next_steps": nxt, "source": "rules"}


def summarize(ctx, meeting: dict, a: dict) -> dict:
    s = rule_summary(meeting, a)
    data = writer.extract(ctx, "Summarize this sales call for the CRM. Buyer's words where possible.",
                          meeting.get("transcript") or "", SCHEMA_HINT)
    if isinstance(data, dict):
        if data.get("summary"):
            s["headline"] = str(data["summary"])[:600]
        if data.get("pain"):
            s["pain"] = str(data["pain"])[:300]
        if isinstance(data.get("next_steps"), list) and data["next_steps"]:
            s["next_steps"] = [str(x)[:200] for x in data["next_steps"]][:6]
        md = data.get("meddpicc") or {}
        if isinstance(md, dict):
            ev = a.setdefault("meddpicc_evidence", {})
            for k, v in md.items():
                if k in meddpicc.ELEMENTS and v and k not in ev:
                    ev[k] = [f"(model) {str(v)[:280]}"]
        s["source"] = "model"
    s.update({
        "duration_min": a.get("duration_min"), "talk_ratio": a.get("rep_talk_ratio"),
        "questions_by_rep": a.get("questions_by_rep"), "objections": sorted(a.get("objections", {})),
        "competitors": sorted(a.get("competitors", {})), "flags": a.get("flags", []),
        "meddpicc_found": sorted(a.get("meddpicc_evidence", {})),
    })
    return s


def crm_note(meeting: dict, s: dict, a: dict) -> str:
    lines = [f"Call: {meeting.get('title') or meeting['id']} ({(meeting.get('started_at') or '')[:10]})"]
    if s.get("pain"):
        lines.append(f"Pain: {s['pain']}")
    if s.get("next_steps"):
        lines.append("Next steps:\n" + "\n".join(f"- {n}" for n in s["next_steps"]))
    risks = [f"objection ({k}): {_strip_speaker(v[0])}" for k, v in a.get("objections", {}).items()]
    risks += [f"competitor: {c}" for c in a.get("competitors", {})]
    if not s.get("next_steps"):
        risks.append("no clear next step heard")
    if risks:
        lines.append("Risks:\n" + "\n".join(f"- {r}" for r in risks))
    ev = a.get("meddpicc_evidence", {})
    if ev:
        lines.append("MEDDPICC evidence found:\n" + "\n".join(
            f"- {meddpicc.LABELS[k]}: {_strip_speaker(v[0])}" for k, v in ev.items() if k in meddpicc.LABELS))
    return "\n".join(lines)


def process(ctx, meeting: dict, now: datetime | None = None) -> dict:
    """Analyze one meeting, store summary + insights, hand off, queue the CRM note. Idempotent via processed_at."""
    ts = _now(now).isoformat()
    a = analyze_text(ctx, meeting.get("transcript") or "")
    s = summarize(ctx, meeting, a)
    refs = {"account_id": meeting.get("account_id"), "deal_id": meeting.get("deal_id"), "meeting_id": meeting["id"]}
    when = meeting.get("started_at") or ts
    st, agent = ctx.store, ctx.manifest.id
    for comp, quotes in a.get("competitors", {}).items():
        st.add_insight(agent, "competitor_mention", comp, {"count": len(quotes)}, quotes[0], when, **refs)
    for cat, quotes in a.get("objections", {}).items():
        st.add_insight(agent, "objection", cat, {"count": len(quotes)}, quotes[0], when, **refs)
    for f in a.get("flags", []):
        st.add_insight(agent, "call_flag", f.split(" ")[0].lower(), {"flag": f}, f, when, **refs)
    for q in a.get("pricing_mentions", []):
        st.add_insight(agent, "pricing_mention", "pricing", None, q, when, **refs)
    for q in s.get("next_steps", []):
        st.add_insight(agent, "next_step", "next_step", None, q, when, **refs)

    st.upsert("meetings", {"id": meeting["id"], "summary": s, "processed_at": ts, "analysis": {
        k: a.get(k) for k in ("speakers", "rep_talk_ratio", "questions_by_rep", "longest_monologue_words",
                              "longest_monologue_speaker", "meddpicc_evidence", "objections", "competitors")}})

    out = {"meeting_id": meeting["id"], "title": meeting.get("title"), "summary": s, "handoffs": [], "approvals": []}
    deal = st.get("deals", meeting["deal_id"]) if meeting.get("deal_id") else None
    ev = a.get("meddpicc_evidence", {})
    if deal and ev:
        proposed = meddpicc.merge_evidence(deal.get("meddpicc"), ev, f"call {meeting['id']}")
        hid = ctx.handoffs.send("deal-inspection", "meddpicc_evidence", meeting["id"],  # one per call, never merged away
                                {"deal_id": deal["id"], "meeting_id": meeting["id"], "evidence": ev,
                                 "proposed": {k: v for k, v in proposed.items() if v["source"] == f"call {meeting['id']}"}})
        if hid:
            out["handoffs"].append(("deal-inspection", hid))
    if deal and deal.get("crm_id"):
        out["approvals"].append(ctx.request_approval(
            "deal_note", {"crm_id": deal["crm_id"], "body": crm_note(meeting, s, a), "meeting_id": meeting["id"]},
            summary=f"call note for {deal.get('name')} ({meeting.get('title')})"))
    hid = ctx.handoffs.send("seller-follow-up", "meeting_recap", meeting["id"], {
        "meeting_id": meeting["id"], "deal_id": meeting.get("deal_id"), "account_id": meeting.get("account_id"),
        "summary": s.get("headline"), "pain": s.get("pain"), "next_steps": s.get("next_steps", []),
        "attendees": meeting.get("attendees") or [], "owner": meeting.get("owner")})
    if hid:
        out["handoffs"].append(("seller-follow-up", hid))
    return out


def digest_block(meeting: dict, s: dict, account_name: str | None = None) -> str:
    who = ", ".join(x for x in [account_name, meeting.get("owner"),
                                f"{s['duration_min']:.0f} min" if s.get("duration_min") else None] if x)
    lines = [f"*{meeting.get('title') or meeting['id']}*" + (f" ({who})" if who else ""),
             f"Summary: {s.get('headline')}",
             "Next steps: " + ("; ".join(s.get("next_steps") or []) or "none heard"),
             "Flags: " + ("; ".join(s.get("flags") or []) or "none")]
    if s.get("competitors"):
        lines.append("Competitors: " + ", ".join(s["competitors"]))
    if s.get("meddpicc_found"):
        lines.append("MEDDPICC evidence: " + ", ".join(meddpicc.LABELS[e].lower() for e in s["meddpicc_found"]))
    return "\n".join(lines)


def missed_areas(ctx, meeting: dict, a: dict) -> list[str]:
    deal = ctx.store.get("deals", meeting["deal_id"]) if meeting.get("deal_id") else None
    if not deal:
        return []
    found = set(a.get("meddpicc_evidence", {}))
    return [g["label"] for g in meddpicc.gaps(deal.get("meddpicc"), deal.get("stage")) if g["element"] not in found]


def coaching(ctx, meeting: dict) -> dict:
    a = analyze_text(ctx, meeting.get("transcript") or "")
    tips = []
    r = a.get("rep_talk_ratio")
    if r is not None and r > 0.65:
        tips.append(f"Talk ratio {int(r * 100)}%. Pause after key points and ask a question; aim for under 60%.")
    if a.get("questions_by_rep", 0) < 3 and r is not None:
        tips.append(f"Only {a['questions_by_rep']} questions from your side. Aim for 5 or more open questions.")
    reps = profile.rep_names(ctx)
    if a.get("longest_monologue_words", 0) > 250 or (a.get("longest_monologue_words", 0) > 150 and any(
            n.lower() in (a.get("longest_monologue_speaker") or "").lower() for n in reps)):
        tips.append(f"{a['longest_monologue_speaker']} spoke {a['longest_monologue_words']} words in one turn. "
                    "Break it up with a check-in question.")
    for cat, quotes in a.get("objections", {}).items():
        tips.append(f"Objection ({cat}): \"{_strip_speaker(quotes[0])}\" Acknowledge it, then ask what it is compared to.")
    if not a.get("next_steps"):
        tips.append("No next step heard. Close every call with an agreed, dated next step and an owner.")
    return {"meeting_id": meeting["id"], "title": meeting.get("title"), "owner": meeting.get("owner"),
            "talk_ratio": r, "questions_by_rep": a.get("questions_by_rep"),
            "longest_monologue": {"speaker": a.get("longest_monologue_speaker"), "words": a.get("longest_monologue_words")},
            "tips": tips[:4], "missed_meddpicc_areas": missed_areas(ctx, meeting, a)}


def find_meeting(ctx, ref: str) -> dict | None:
    m = ctx.store.get("meetings", ref)
    if m:
        return m
    rows = ctx.store.select("meetings", "LOWER(title) LIKE ? OR account_id=? OR deal_id=?",
                            (f"%{ref.lower()}%", ref, ref), order="started_at IS NULL, started_at DESC")
    return rows[0] if rows else None


def looks_like_transcript(text: str) -> bool:
    return "\n" in text and (bool(re.search(r"^\s*(?:\[?[\d:.]+\]?\s+)?[A-Z][\w .'\-]{0,40}:\s", text, re.M))
                             or text.lstrip().startswith(("WEBVTT", "[", "{")))
