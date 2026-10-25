# Hygiene rules

## Duplicate accounts

- Domain: lowercase, drop the scheme, `www.` and any path. Two accounts with the same result are duplicates.
- Name: lowercase, `&` becomes `and`, punctuation removed, trailing suffixes removed (Inc, LLC, Ltd, Corp, Co, Company, PLC, GmbH, Holdings, Group and the rest in config). Two accounts with the same result are duplicates even with different domains, so review these before approving.
- A group already found by domain is not repeated by name.

## Duplicate contacts

- Same email, any case.
- Same normalized name at the same account (for contacts not already matched by email).

## Record to keep

1. Has a CRM id.
2. Most recent update.
3. Most fields filled.
4. Smallest id, so the pick never changes between runs.

## Contacts with no account

Match the work email domain to an account domain. Personal domains (gmail.com, outlook.com, yahoo.com, hotmail.com, icloud.com and the rest in config) never match. No email means no match.

## Bounces

A contact with `email_invalid` set (from a bounce event or the CRM) needs a new email. Enrichment gets an `enrich_request` handoff for the email field.

## Stale deals

- Close date in the past: propose a new close date 30 days out and ask the owner to confirm or close lost.
- No activity longer than the stage limit (`stage_max_days`, default 45): ask the owner for the next step. No field change is proposed.

## Fix actions

| Fix | Approval action |
| --- | --- |
| Merge | `crm_merge` (a person merges in the CRM; losers are marked merged locally) |
| Link contact with a CRM id | `contact_update` on the account field |
| Link contact without a CRM id | `crm_contact` under the matched account |
| Deal revision | `deal_update` with the proposed close date |
