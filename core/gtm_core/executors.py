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

from .approvals import executor
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
        res = ctx.sequencer.enroll(p["contact"], p.get("steps", []), p.get("campaign"), p.get("meta"))
        for did in p.get("draft_ids", []):
            ctx.store.execute("UPDATE drafts SET status=? WHERE id=?", ("sent", did))
        ctx.audit.log("sequence.enrolled", email=p["contact"]["email"], at=now_iso())
        return res

    @executor("sequence_stop")
    def _stop(p: dict) -> dict:
        ctx = c()
        res = ctx.sequencer.stop(p["email"], p.get("reason", ""), p.get("meta"))
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
