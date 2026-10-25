# Event playbook

## Who gets an invite

1. In the event region (`countries`). Webinars leave `countries` empty: anyone may attend.
2. Signal Scout tier in `target_tiers`. Accounts without a score need ICP fit of 60 or more.
3. Not in active pipeline. The deal owner invites those accounts personally.
4. Not on do-not-contact, and the contact is not suppressed (opt-out, bounce, unsubscribe).
5. Contacts match the event personas: function in `personas.functions`, seniority at or above `personas.min_seniority`. Up to 2 per account.
6. Rank by tier, then score. Stop at capacity times `invite_multiplier` (default 3).

## Sequence

| When | Who | Email |
| --- | --- | --- |
| 2 to 4 weeks before | invite list | invite: event, date, place, one reason, registration link |
| last 7 days | registrants | reminder: date and link |
| day after | attendees | thank-you, one takeaway, one meeting ask |
| day after | registrants who missed it | notes offer |

## After the event

- Load the registrant list with an `attended` column. Each registrant becomes a lead tagged with the event; Lead Triage routes it.
- Each attendee at a known account adds an `event_attended` signal, which Signal Scout scores and ICP Outbound may mention ("Good to see your team at ...").
- The report counts meetings and opportunities logged at attending accounts on or after the event date, and new deals created since then.
