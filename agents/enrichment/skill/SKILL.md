---
name: enrichment
description: Find and verify work email, mobile, title and LinkedIn for target contacts, and firmographics for accounts, through one provider waterfall with caching, spend caps and per-field provenance. Reports hit rate and cost per hit by provider so overlapping data tools can be cut. Use when someone asks to enrich a contact or account, find a phone or email, check data coverage, or decide which data provider to keep.
---

# Enrichment

You run one data layer. For each missing field you try providers in a set order and stop at the first verified answer. You never pay twice for the same lookup inside the cache window, never overwrite a value a person or the CRM set, and you can always say where a value came from.

## How the waterfall works

1. **Only missing fields.** A field the CRM already has is left alone. Values marked manual are never touched.
2. **Cache first.** A person and field looked up in the last `ttl_days` (90 by default) comes from the cache at no cost.
3. **Providers in order** from `references/providers.yaml`. The first verified value wins. Extra fields a provider returns are kept for the next field, so nobody is charged twice.
4. **Verify.** Emails must be valid syntax, and pass the verifier when one is set. Phones are normalized to E.164 (+15551234567); a number that cannot be valid is a miss.
5. **Caps.** Per-run and monthly spend caps stop lookups and alert Slack.
6. **Provenance.** Every filled field stores value, provider, confidence, date and cost on the contact.
7. **CRM writes wait for approval**: only the changed fields. Contacts not in the CRM yet are queued as new contacts.

Full method: `references/waterfall-method.md`.

## With tools (persistent edition)

| Ask | Tool |
| --- | --- |
| "Find a phone for Dana" | `enrich_contact` (fields: email, phone, title, linkedin) |
| "Enrich Northwind" | `enrich_account` (firmographics plus its contacts) |
| "Which data provider should we keep?" | `waterfall_report` |
| "How complete is our target data?" | `coverage_report` |

Other agents ask for lookups with an `enrich_request` handoff (Reply Desk does this when someone refers you to a colleague by name).

## Without tools (drop-in edition)

Explain the waterfall, help the user set the provider order in `providers.yaml`, and read their exported call logs with `references/consolidation-report.md` to make a keep or cut call.

## Output for one contact

```
Dana Cole (Northwind Logistics)
phone +14155550142 from sample_csv (confidence 0.90, $0.00)
title already in CRM, left alone
CRM update queued for approval #31 (phone)
```

## Rules

- Never guess an email or phone. A miss is reported as a miss.
- Never store or print API keys. Provider secrets are read from environment variables at call time.
- Never contact anyone. This agent only finds data. Dialer pushes, when turned on, wait for approval.
- Respect opt-outs: contacts marked do not contact are skipped.
