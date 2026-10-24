# API currency — Wave 2 report (2026-06-13)

30 skills audited. Verdicts: {'significant drift': 14, 'minor drift': 16}. 221 drift items, 103 files edited. ~1.95M tokens.

## Significant-drift skills
- **sales-snov** — Campaign API endpoints; Account balance endpoint; Prospect Management endpoints
- **sales-tomba** — Email Verifier endpoint path; Phone Finder endpoint path + input; Email Sources endpoint path
- **sales-woodpecker** — pricing model; API add-on scope/currency; Lead Finder credits
- **sales-zerobounce** — rate limit (validate / credit endpoints); invalid API key response (validate endpoint); AI Scoring score scale
- **sales-6sense** — People Enrichment API endpoint; API documentation accessibility; Rate limits
- **sales-adroll** — API base URL; Authentication header scheme; CRUD API endpoint style
- **sales-afluencer** — pricing.tier_names; pricing.pro_plus_tier; pricing.boss_tier
- **sales-attention** — info.version (OpenAPI spec version); GET /calendar/events; POST /createDeck
- **sales-beehiiv** — webhook tier event names; pricing presentation (Scale/Max monthly vs annual); API rate limit
- **sales-bliro** — pricing.plan_structure; pricing.api_webhook_plan_gate; webhooks.signature_signed_payload
- **sales-buttondown** — API create-subscriber request body field name; API rate limits; API versioning (X-API-Version header)
- **sales-calendly** — Scheduling API — POST /invitees (Create Event Invitee); Event Type write endpoints — POST /event_types, PATCH /event_types/{uuid}, POST /one_off_event_types; Availability write endpoints — GET/PATCH /event_type_availability_schedules; GET /location
- **sales-churnzero** — pricing/editions; REST API plan gate; custom dashboards plan gate
- **sales-clari-copilot** — Copilot API base URL; Copilot API authentication; Copilot API rate limit

## Minor / current
sales-transactional-email, sales-arrfounder, sales-aspire, sales-attio, sales-audionotes, sales-avoma, sales-betalist, sales-bluedot, sales-boomi, sales-brandwatch, sales-calabrio, sales-calcom, sales-callminer, sales-celigo, sales-circleback, sales-claap