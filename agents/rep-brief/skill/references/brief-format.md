# Brief format

```
Your brief, Sam Rivera (2026-10-23)
Do next
1. Reply to Dana Cole today and book the meeting.
2. Respond to hot lead Omar Haddad (Proseware) before 07:55 UTC.
3. Push-button Fourth Coffee: start with Rosa Diaz (VP of Sales).
Replies: positive from Dana Cole; objection from Lee Wong
Leads: Omar Haddad (Proseware, hot)
Top accounts
- Fourth Coffee | A 84 | why now: New executive in the buying function (2026-10-08) | Rosa Diaz (VP of Sales), Kai Moore (Head of Revenue Operations)
- Northwind Logistics | A 82 | open deal: Northwind Logistics - Platform
New signals: 4 | Fourth Coffee: Raised a funding round | timing only: 2
Pipeline: open $236,000 vs $400,000 left to quota (0.59x, target 3.0x) | gap $964,000
Deal hygiene: Contoso Health - Agents (next step 13d late); Contoso Health - Agents (28d quiet)
```

## Sections

| Section | Source | Shown when |
| --- | --- | --- |
| Do next | ranked actions, at most 3 | always, if any |
| Replies | reply classifications (positive, referral, objection, question) for the rep's accounts | any unhandled |
| Leads | Lead Triage leads routed to the rep, hot or warm, no reply sent | any |
| Top accounts | rep's accounts by Signal Scout score, then ICP fit | always |
| New signals | signals recorded since the last brief | any |
| Pipeline | rep deals, rep quota, coverage target | always |
| Deal hygiene | open deals missing a next step, next step late, or quiet past `idle_days` | any |

## Ownership

An account belongs to the rep who owns it in the CRM, else the owner of its open deal, else a stable territory match from `config/company.yaml` (region, then segment). The territory match never changes between runs.

## Quota

A rep's quota is the `quota` on their entry in `config/company.yaml > team.owners`. Without one, the team quarter quota is split evenly. Coverage is open pipeline divided by quota left this quarter; the gap is coverage target times quota left, minus open pipeline.
