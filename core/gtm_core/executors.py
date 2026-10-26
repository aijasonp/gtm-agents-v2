"""Executors for approved actions shared by every agent.

Agents queue these with ctx.request_approval(action, payload). Nothing here runs until a
human approves the request (`gtm approvals <agent> approve <id>` then `execute`).

action            payload
crm_update        crm_id, fields                       account fields
crm_note          crm_id, body                         note on the account
deal_update       crm_id, fields                       deal / opportunity fields
deal_note         crm_id, body                         note on the deal
crm_task          subject, body, due_at, account_crm_id, deal_crm_id, owner
crm_contact       fields{name,email,title}, account_crm_id
sequence_enroll   contact{email,name,company}, steps[{subject,body}], campaign, draft_ids
                  (sequence_release: per_step sends step 1 and holds the rest; see sequences.py)
sequence_step     held_id, contact, subject, body, draft_id, owner     one held step, confirmed by its owner
pipeline_email    contact, subject, body, draft_id, owner, cadence_id   one pipeline follow-up the owner confirmed
sequence_stop     email, reason                        stop every active sequence for this person
contact_update    crm_id, fields                       contact fields (enriched email/phone, opt-out)
dialer_enqueue    contact{name,phone,email,company}, owner, script

Agent-owned executors (registered in that agent's jobs.register_executors):
crm_merge         CRM Hygiene: survivor and losers; Slack instruction plus local merged_into marks
discount_approval Proposal Builder: quote id and approved discount level
proposal_send     Proposal Builder: marks the quote and draft sent, CRM note; the rep sends the file
github_pr         Rep Feedback: branch, commit and pull request for an approved rule change
social_post       Content Studio: approved post handed to the publishing tool
"""
from __future__ import annotations

from . import engagement, profile, sequences
from .approvals import CURRENT, executor
from .store import now_iso
from .suppression import reason as suppressed_reason

_CTX: dict = {}


def register_core_executors(ctx) -> None:
    _CTX["ctx"] = ctx

    def c():
        return _CTX["ctx"]

    @executor("crm_update")
    def _crm_update(p: dict) -> dict:
        return c().crm.update_account(p["crm_id"], p["fields"])

    @executor("crm_note")
    def _crm_note(p: dict) -> dict:
        return c().crm.add_note(p["crm_id"], p["body"])

    @executor("deal_update")
    def _deal_update(p: dict) -> dict:
        return c().crm.update_deal(p["crm_id"], p["fields"])

    @executor("deal_note")
    def _deal_note(p: dict) -> dict:
        return c().crm.add_deal_note(p["crm_id"], p["body"])

    @executor("crm_task")
    def _crm_task(p: dict) -> dict:
        return c().crm.create_task(p["subject"], p.get("body", ""), p.get("due_at"), p.get("account_crm_id"),
                                   p.get("deal_crm_id"), p.get("owner"))

    @executor("crm_contact")
    def _crm_contact(p: dict) -> dict:
        return c().crm.create_contact(p["fields"], p.get("account_crm_id"))

    @executor("sequence_enroll")
    def _enroll(p: dict) -> dict:
        ctx = c()
        if not (p.get("contact") or {}).get("email"):
            raise ValueError("sequence_enroll needs contact.email")
        why = suppressed_reason(ctx.store, p["contact"]["email"])
        if why:  # opt-out arrived after approval: never send
            for did in p.get("draft_ids", []):
                ctx.store.execute("UPDATE drafts SET status=? WHERE id=?", ("rejected", did))
            return {"ok": False, "skipped": f"suppressed: {why}"}
        steps = p.get("steps", [])
        rules = ctx.approvals.policy.rules
        if rules.get("sequence_release") == "per_step" and len(steps) > 1:
            res = ctx.sequencer.enroll(p["contact"], steps[:1], p.get("campaign"), p.get("meta"))
            ids = p.get("draft_ids", [])
            if ids:
                ctx.store.execute("UPDATE drafts SET status=? WHERE id=?", ("sent", ids[0]))
            tz = profile.company(ctx).get("timezone") or "UTC"
            res["held"] = sequences.hold(ctx.store, CURRENT.get(), p["contact"], steps, ids,
                                         (p.get("meta") or {}).get("owner"), int(rules.get("step_gap_business_days", 3)),
                                         tz, p.get("meta"))
            ctx.audit.log("sequence.enrolled", email=p["contact"]["email"], at=now_iso(), held=len(res["held"]))
            return res
        res = ctx.sequencer.enroll(p["contact"], steps, p.get("campaign"), p.get("meta"))
        for did in p.get("draft_ids", []):
            ctx.store.execute("UPDATE drafts SET status=? WHERE id=?", ("sent", did))
        ctx.audit.log("sequence.enrolled", email=p["contact"]["email"], at=now_iso())
        return res

    def _send_single(p: dict, kind: str) -> dict:
        ctx = c()
        email = (p.get("contact") or {}).get("email")
        if not email:
            raise ValueError(f"{kind} needs contact.email")
        why = suppressed_reason(ctx.store, email)
        if why:
            if p.get("draft_id"):
                ctx.store.execute("UPDATE drafts SET status=? WHERE id=?", ("rejected", p["draft_id"]))
            return {"ok": False, "skipped": f"suppressed: {why}"}
        res = ctx.sequencer.send_one(p["contact"], {"subject": p.get("subject", ""), "body": p.get("body", "")},
                                     {"kind": kind, "owner": p.get("owner"), "draft_id": p.get("draft_id"),
                                      "cadence_id": p.get("cadence_id"), "campaign": p.get("campaign")})
        if p.get("draft_id"):
            ctx.store.execute("UPDATE drafts SET status=? WHERE id=?", ("sent", p["draft_id"]))
        # the send is the touch: the cadence ledger and engagement rates both read this event
        engagement.record(ctx.store, email, "sent", None, p.get("draft_id"), p.get("step") or kind, source=kind)
        ctx.audit.log(f"{kind}.sent", email=email, draft=p.get("draft_id"))
        return res

    @executor("pipeline_email")
    def _pipeline_email(p: dict) -> dict:
        return _send_single(p, "pipeline_email")

    @executor("sequence_step")
    def _sequence_step(p: dict) -> dict:
        res = _send_single(p, "sequence_step")
        if p.get("held_id"):
            sequences.mark(c().store, p["held_id"], sequences.SENT if res.get("ok", True) else sequences.CANCELLED,
                           res.get("skipped", ""))
        return res

    @executor("sequence_stop")
    def _stop(p: dict) -> dict:
        ctx = c()
        res = ctx.sequencer.stop(p["email"], p.get("reason", ""), p.get("meta"))
        res["held_cancelled"] = sequences.cancel_for(ctx.store, p["email"], p.get("reason") or "sequence stopped")
        if res.get("manual"):
            ctx.slack.post(f":warning: {res['note']}")
        return res

    @executor("contact_update")
    def _contact_update(p: dict) -> dict:
        return c().crm.update_contact(p["crm_id"], p["fields"])

    @executor("dialer_enqueue")
    def _dialer(p: dict) -> dict:
        if not (p.get("contact") or {}).get("phone"):
            raise ValueError("dialer_enqueue needs contact.phone")
        why = suppressed_reason(c().store, (p.get("contact") or {}).get("email"))
        if why:
            return {"ok": False, "skipped": f"suppressed: {why}"}
        return c().dialer.enqueue(p["contact"], p.get("owner"), p.get("script", ""), p.get("meta"))
