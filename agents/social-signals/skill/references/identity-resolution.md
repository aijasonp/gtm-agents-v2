# Identity resolution

Match each engager to a CRM contact and account. Stop at the first rule that matches.

| Order | Rule | Confidence | Result |
| --- | --- | --- | --- |
| 1 | Profile URL equals the contact's LinkedIn URL (scheme, www, country prefix, query string and trailing slash ignored) | 0.98 | Contact and account |
| 2 | Email equals the contact's email | 0.95 | Contact and account |
| 3 | Exact name match to one contact at the account the company resolves to | 0.85 | Contact and account |
| 4 | Company resolves to an account, person not found | 0.60 | Account only ("not in CRM yet") |
| 5 | Nothing matches | 0 | Unresolved, counted in stats |

## Company to account

- Lowercase, drop punctuation, turn "&" into "and", and remove legal suffixes (Inc, LLC, Ltd, Corp, Co, Company, GmbH, PLC, SA, AG, BV, Pty, Group, Holdings).
- Equal normalized names match.
- A company written as a domain (northwind.example) matches the account domain.
- The first label of the account domain equals the normalized company name with spaces removed.

## Rules

- Two contacts with the same name at the same account: no match at rule 3. Fall to account only.
- Never match on first name alone, or on name without a company.
- The person key is the contact id when matched, else the profile URL, else name plus company. Repeat engagement is counted on this key.
