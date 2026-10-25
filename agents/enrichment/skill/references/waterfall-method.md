# Waterfall method

## Identifiers
A person is looked up by work email, else LinkedIn URL, else full name plus company domain. Without one of these the lookup is refused, not guessed.

## Order
`providers.yaml > order` lists providers per field. Put the cheapest provider with the best hit rate first. Use `waterfall_report` after two to four weeks to reorder with real numbers.

## Provider types
| Type | Use | Notes |
| --- | --- | --- |
| csv | an export or a purchased list | match on email, linkedin, name_domain or domain |
| http | any API that returns JSON | URL and JSON body templates take {email} {domain} {name} {first} {last} {linkedin} {company}; headers take ${ENV_VAR}; outputs map fields to JSON paths like `data.0.phone` |
| manual | end of the line | the field is listed for a person to research |

A provider whose secret is not set is skipped and logged, not treated as a miss.

## Validation
- Email: syntax check, lower case; with a verifier set, only accepted statuses pass and a passed email gets confidence 0.95.
- Phone: digits only, extensions dropped, country code from the number, else from the contact or account country, else `default_country`. Kept only when it forms a valid E.164 number (8 to 15 digits; North American numbers are 11 with the leading 1).
- Numbers (employees, revenue) are parsed; titles and industries are trimmed text.

## Overwrite rules
| Current value | Result |
| --- | --- |
| empty | filled |
| from the CRM or typed by a person | never replaced |
| listed in the contact's `manual_fields` | never replaced |
| from an earlier enrichment, and force is on | replaced, provenance updated |

## Spend
Each call adds its `cost_per_call`. A run stops at `caps.per_run_usd`; all lookups stop for the month at `caps.monthly_usd`. Slack is told once per run.
