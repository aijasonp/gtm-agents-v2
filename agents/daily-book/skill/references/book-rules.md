# Book rules

## Slots

| Setting | Where | Default |
| --- | --- | --- |
| Slots per AE | `team.owners[].book.slots` in company.yaml, else `slots` | 40, held to 25..50 |
| Warm share | `team.owners[].book.warm_ratio`, else `warm_ratio` | 0.5 |
| People per account | `max_per_account` | 3 |

## Warm pool

| Source | Who | Reason shown |
| --- | --- | --- |
| `engaged` | Human opens or clicks in `engaged_days`, no reply | Timing only; action is a call or LinkedIn |
| `quiet_deal` | Primary contact on the AE's open deal idle past `idle_days` | The deal and its stage |
| `champion_moved` | A `champion_joined` signal on the AE's account | Where they landed |
| `inbound` | The AE's inbound lead not worked after `inbound_days` | The lead source |
| `event` | Attended an event, no meeting on the account since | The event |
| `social` | Engaged with company or influencer content | Content engagement |
| `recycle` | Closed-lost over `recycle_days` ago | Check whether timing changed |

## Cold pool

The AE's accounts (CRM owner, open-deal owner, then territory), skipping tier X, excluded industries, accounts below `icp_floor` with no score, and accounts with an open deal. Accounts on today's Signal Sourcing send list come first, then Signal Scout score. Buyers come from Rep Brief's contact rules. With `fill_contacts` on, an account with no buyer on file is filled from the `people_search` capability in config/mcp.yaml (stored locally, never in the CRM).

## Exclusions (any pool)

- No email, opted out, bounced or do-not-contact.
- Already teed up for an AE or in a live Follow-Through cadence.
- Touched within Rep Brief's `recent_touch_days` (except engaged contacts, who were emailed by design).
- An open deal on the account owned by someone else, or an inbound thread in progress (except for that inbound or event lead itself).
- Over `max_per_account` for the account. Each person appears once.

## Shortfall

Filled = warm taken + cold taken + backfill. Anything left is the shortfall, posted with the book and logged for Ops Monitor.
