# Targeting rules

Precision beats volume. A short list of accounts with a real reason to talk now beats a long list.

## Who gets on the list

1. Start from the latest Signal Scout ranking (Tier A, then B, then C). With no ranking, use ICP fit alone.
2. Drop any account below the ICP floor (30) or in an excluded industry.
3. Drop any account with an open deal. This is an active pipeline conflict: show it, do not draft.
4. Drop any account where someone was contacted in the last 45 days (a sent draft or a `last_touched` date).
5. Drop any domain or email in `do-not-contact.yaml`.

Every dropped account is listed with its reason. Nothing is dropped silently.

## Who to contact

- Match titles against the buyer and champion functions in `company.yaml`.
- Keep people at or above the minimum seniority. Rank by seniority, then buyer function before champion function.
- At most 3 contacts per account. If nobody matches, flag "no buyer contact found" and draft nothing.

## Why now

- Use the account's freshest signal that has a `say_it` line in the Signal Scout taxonomy.
- Timing-only signals (pricing page visits, intent data, competitor contracts, layoffs, incidents) can raise the rank but never appear in copy.
- No usable signal: lead with the value prop for the contact's function.
