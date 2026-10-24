# API currency — Wave 1 report (2026-06-13)

30 stalest API skills audited against live official docs. **All 30 had drift** (16 significant, 14 minor). 254 drift items, 106 files edited. ~2.35M tokens, ~25 min. Corpus re-linted: ERROR=0, PII scan 0 hits, no author/attribution introduced.

## Significant-drift skills (notable corrections)
- **sales-anymailfinder** — endpoint: find person email: SKILL.md + platform-guide.md used POST /v5.1/search/person.json; live path is POST /v5.1/f; find person email: linkedin_url fallback + person_* response fields: Person endpoint now also accepts a linkedin_url param (name+company tried first, LinkedIn 
- **sales-apollo** — People Search endpoint path: API people search is POST /mixed_people/api_search (not /mixed_people/search). It is optim; Search pagination cap: People and company search are capped at 50,000 records (100 per page × up to 500 pages), n
- **sales-enrichso** — endpoint: reverse email lookup: Path is GET /v1/api/person (+ optional in_realtime param), not /v1/api/reverse-email-looku; endpoint: email finder: Is GET /v1/api/find-email with fullName + companyDomain params; skill listed it as POST.
- **sales-getprospect** — V2 find email endpoint path: Was documented as GET /api/v2/email/find; live OpenAPI shows GET /v2/email-finder. Params ; V2 verify email endpoint path: Was GET /api/v2/email/verify; live path is GET /v2/email-verifier (param email). Response 
- **sales-hunter** — API rate limits: Skill claimed per-PLAN limits (Starter 150 / Growth 300 / Scale 600 req/min). Current offi; Discover endpoint HTTP method: Skill listed 'GET /discover'. Current docs show 'POST https://api.hunter.io/v2/discover' w
- **sales-lemlist** — Authentication — Bearer token method: Skill listed Bearer token as a supported auth method alongside Basic auth. Official auth d; Rate limit response headers: Rate limit value unchanged (20 req/2s) but the official docs document four response header
- **sales-lobstr** — credit model: Was documented as flat '1 unique result = 1 credit' throughout. Official docs now state cr; run status lifecycle: Skill listed only running/paused/done/error. Official lifecycle is pending → running → upl
- **sales-mailshake** — Rate limits: Skill claimed a flat 100 requests/minute fixed-window cap with HTTP 429 / rate_limit_excee; Webhook (push) events: Skill listed events Sent/Open/Click/Reply/LeadCatcher/Bounce/Unsubscribe. Actual events ar
- **sales-prospeo** — pricing.plan_structure: Skill listed 5 tiers (Free $0/75cr, Starter $39/1,000, Growth $99/5,000, Pro $199/20,000, ; pricing.free_credits: Free plan credits changed from 75/mo to 100/mo per official help center ("Free: 100 credit
- **sales-qwilr-automation** — POST /pages — variable field name: Skill passed per-block `tokens` objects. Live API uses a SINGLE top-level `substitutions` ; POST /pages — draft flag: Skill used `isPublished: false`. Live API uses boolean `published`. Fixed in create-page e
- **sales-safetymails** — Real-time REST API endpoint: Skill claimed 'no REST endpoint URLs documented' and the API 'operates exclusively through; Authentication scheme: Skill said how the API key is transmitted is undocumented. Current docs specify HMAC-SHA25
- **sales-seamless** — rate_limit: Was '~100 requests per 60 seconds per endpoint'. Live docs: 60 requests/minute per endpoin; webhook.events: Was event names 'contact.research.completed' / 'company.research.completed'. Live docs: 'c
- **sales-seismic** — OAuth token endpoint: Token endpoint is https://auth.seismic.com/tenants/{tenant}/connect/token (OIDC connect/to; Rate limits: Limits are tiered per 60s window, not a flat ~100 req/min: LiveDoc generation 10, LiveSend
- **sales-sendgrid** — 
- **sales-skrapp** — API base URL: Base URL is https://api.skrapp.io (HTTPS only), not https://skrapp.io/api. Finder/account/; Authentication: HTTP Basic Auth via X-Access-Key header (paid accounts only). Old reference to alternative
- **sales-smartlead** — webhook event identifiers: Skill listed LEAD_REPLIED, LEAD_INTERESTED, EMAIL_OPENED, EMAIL_CLICKED, EMAIL_BOUNCED. Ac; webhook endpoint scoping: Skill used global /webhooks (POST/GET/DELETE). Webhooks are campaign-scoped: GET/POST/DELE

## Minor-drift skills
sales-activecampaign, sales-braze, sales-brevo, sales-customerio, sales-getresponse, sales-integration, sales-klaviyo, sales-mailgun, sales-minelead, sales-openwebninja, sales-outscraper, sales-postmark, sales-prospect-list, sales-salesloft

Full structured results: `api-wave1-results.json`. Each skill's `learnings.md` now carries a dated 're-verified against live docs' entry with source URLs.