# Push-button workflow

Goal: an account executive turns "this account looks good" into a ready-to-approve first touch in one step.

## 1. Pick the contact

The contact the rep named, or the best reachable buyer at the account: buyer or champion function, manager or above, not touched in the last 45 days, not on do-not-contact, people who engaged with your content first.

## 2. Conflict checks (any one stops the workflow)

| Check | Why |
| --- | --- |
| Open deal owned by another rep | Their deal, their call |
| Inbound lead in progress at the account | Lead Triage owns that conversation; reply on that thread |
| Account or contact touched in the last 45 days (any agent's sent draft, another agent's queued draft, a recent push) | No double contact |
| Account or contact on the do-not-contact list | Hard stop |
| Excluded industry | Not a customer we can serve |

An open deal owned by the same rep is allowed: that is multi-threading.

## 3. Research brief

Firmographics, ICP fit and reasons, Signal Scout tier and score, the last six signals (marked mentionable or not), open deals, up to five contacts, the last two calls with pain, competitor and objection notes, and what this contact engaged with.

## 4. Draft

Facts only, from the research brief and `config/company.yaml`. One reason to write now, one outcome, one ask, under 110 words. The opener uses a signal the rep may say to this person; a line about someone else is skipped.

## 5. Queue together

| Approval | When |
| --- | --- |
| sequence_enroll | the draft passes the Copy QA Gate |
| crm_task "follow up" in 2 days, with the call script | with the email |
| dialer_enqueue with the call script | the contact has a phone number |

If the draft fails the gate, nothing is queued and the fixes are listed. Rejecting the email approval marks the draft rejected.

## Call script (3 lines)

1. Reason for the call (the same opener as the email, or a plain intro).
2. The problem to test, as a question, from the matching value prop.
3. The ask: 15 minutes next week.
