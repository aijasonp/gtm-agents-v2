---
name: greenhouse
description: >
  Manage Greenhouse recruiting via the Harvest API. Use when the user asks about
  jobs, candidates, applications, interviews, scorecards, offers, or hiring pipeline.
  Supports listing, searching, advancing/rejecting applications, and adding candidates/notes.
  Stdlib only — no external dependencies.
metadata: { "openclaw": { "primaryEnv": "GREENHOUSE_API_KEY" } }
---

# Greenhouse Skill

Interact with Greenhouse's Harvest REST API. Stdlib only (urllib, json, base64). No pip dependencies.

## ⚠️ SAFETY: Write Operations Require Explicit User Request

**Read operations** (jobs, candidates, applications, stages, scorecards, offers, departments, offices, users, sources, rejection-reasons, activity, scheduled-interviews) — use freely.

**Write operations** (add-note, add-candidate, advance, reject, update-candidate) — **ONLY use when the user explicitly asks**. Never create, modify, or advance/reject candidates proactively.

## API Key

Set `GREENHOUSE_API_KEY` env var with a Greenhouse Harvest API token.

Generate at: Greenhouse → Configure → Dev Center → API Credential Management → Create New API Key (type: Harvest).

## Base Command

```bash
python3 {baseDir}/scripts/greenhouse.py [--pretty] <command> [args]
```

`--pretty` / `-p` — pretty-print JSON output. All commands output JSON.

## Pagination

Greenhouse uses `Link` header pagination. List commands support:
- `--limit N` — results per page (default 100, max 500)
- `--all` — auto-paginate and return all results (follows `Link: <url>; rel="next"` headers)

Rate limit: 50 requests per 10 seconds. The client auto-retries on 429.

## Read Commands

### jobs — List jobs
```bash
python3 {baseDir}/scripts/greenhouse.py jobs [--status open|closed|draft] [--department-id ID] [--limit 100] [--all]
```

### job — Get single job details
```bash
python3 {baseDir}/scripts/greenhouse.py job <job_id>
```

### candidates — List candidates
```bash
python3 {baseDir}/scripts/greenhouse.py candidates [--job-id ID] [--created-after ISO8601] [--updated-after ISO8601] [--limit 100] [--all]
```

### candidate — Get single candidate with applications
```bash
python3 {baseDir}/scripts/greenhouse.py candidate <candidate_id>
```

### applications — List applications
```bash
python3 {baseDir}/scripts/greenhouse.py applications [--job-id ID] [--status active|rejected|hired] [--created-after ISO8601] [--updated-after ISO8601] [--limit 100] [--all]
```

### application — Get single application
```bash
python3 {baseDir}/scripts/greenhouse.py application <application_id>
```

### stages — List stages for a job
```bash
python3 {baseDir}/scripts/greenhouse.py stages <job_id>
```

### scorecards — List scorecards for an application
```bash
python3 {baseDir}/scripts/greenhouse.py scorecards <application_id> [--all]
```

### offers — List offers for an application
```bash
python3 {baseDir}/scripts/greenhouse.py offers <application_id> [--all]
```

### departments — List departments
```bash
python3 {baseDir}/scripts/greenhouse.py departments [--all]
```

### offices — List offices
```bash
python3 {baseDir}/scripts/greenhouse.py offices [--all]
```

### users — List users
```bash
python3 {baseDir}/scripts/greenhouse.py users [--limit 100] [--all]
```

### user — Get single user
```bash
python3 {baseDir}/scripts/greenhouse.py user <user_id>
```

### sources — List sources
```bash
python3 {baseDir}/scripts/greenhouse.py sources [--all]
```

### rejection-reasons — List rejection reasons
```bash
python3 {baseDir}/scripts/greenhouse.py rejection-reasons [--all]
```

### activity — Get activity feed for candidate
```bash
python3 {baseDir}/scripts/greenhouse.py activity <candidate_id>
```

### scheduled-interviews — List scheduled interviews for an application
```bash
python3 {baseDir}/scripts/greenhouse.py scheduled-interviews <application_id> [--all]
```

### attachments — List attachments (resumes, cover letters) for a candidate
```bash
python3 {baseDir}/scripts/greenhouse.py attachments <candidate_id>
```
Returns list of attachments with `url`, `filename`, `type` (resume, cover_letter, admin_only, etc.).

### download-attachment — Download an attachment file
```bash
python3 {baseDir}/scripts/greenhouse.py download-attachment <url> [--output filename.pdf]
```
Downloads the file to the current directory. Auto-detects filename if `--output` is omitted.

### custom-fields — List custom fields defined in the account
```bash
python3 {baseDir}/scripts/greenhouse.py custom-fields [--field-type application|candidate|job|offer|opening]
```

### application-detail — Full application with candidate info, attachments, and custom question answers
```bash
python3 {baseDir}/scripts/greenhouse.py application-detail <application_id>
```
Returns a combined object with:
- `application` — full application data including `answers` (custom question responses) and `keyed_custom_fields`
- `candidate` — full candidate record
- `attachments` — all attachments (resumes, cover letters, etc.) with download URLs

**This is the go-to command for reviewing a full application** — includes everything: custom questions, resume links, candidate details.

## Write Commands

### add-note — Add note to a candidate
```bash
python3 {baseDir}/scripts/greenhouse.py add-note \
  --candidate-id <ID> \
  --body "Note text" \
  --user-id <ID>
```

### add-candidate — Add a new candidate
```bash
python3 {baseDir}/scripts/greenhouse.py add-candidate \
  --first-name "Jane" \
  --last-name "Doe" \
  [--company "Acme"] \
  [--title "Engineer"] \
  [--phone "+1234567890"] \
  [--email "jane@example.com"] \
  [--website "https://jane.dev"] \
  [--social "https://linkedin.com/in/jane"] \
  [--tags recruiter-sourced senior]
```

### advance — Advance application to next stage
```bash
python3 {baseDir}/scripts/greenhouse.py advance \
  --application-id <ID> \
  --user-id <ID>
```
Requires `On-Behalf-Of` user ID (the person performing the action).

### reject — Reject an application
```bash
python3 {baseDir}/scripts/greenhouse.py reject \
  --application-id <ID> \
  --user-id <ID> \
  [--rejection-reason-id <ID>] \
  [--notes "Reason for rejection"]
```

### update-candidate — Update candidate info
```bash
python3 {baseDir}/scripts/greenhouse.py update-candidate <candidate_id> \
  [--first-name "Jane"] \
  [--last-name "Smith"] \
  [--company "NewCo"] \
  [--title "Sr. Engineer"] \
  [--tags tag1 tag2]
```

## Common Workflows

### Review pipeline for a job
1. `jobs --status open` → find the job ID
2. `stages <job_id>` → see the hiring stages
3. `applications --job-id <job_id> --status active` → list active applicants
4. `candidate <candidate_id>` → deep-dive on a specific candidate

### Check candidate status
1. `candidate <candidate_id>` → see all applications
2. `scorecards <application_id>` → see interview feedback
3. `scheduled-interviews <application_id>` → see upcoming interviews
4. `activity <candidate_id>` → see full activity history

### Advance a candidate
1. `applications --job-id <job_id> --status active` → find the application
2. `stages <job_id>` → confirm current/next stage
3. `users` → get your user ID for On-Behalf-Of
4. `advance --application-id <ID> --user-id <ID>`

### Reject a candidate
1. `rejection-reasons` → find the appropriate reason ID
2. `reject --application-id <ID> --user-id <ID> --rejection-reason-id <ID> --notes "..."`

### Add a sourced candidate
1. `add-candidate --first-name "..." --last-name "..." --email "..." --tags sourced`
2. Note the returned candidate ID for further actions

## Notes

- All IDs in Greenhouse are integers.
- Output is always JSON. Pipe through `jq` for shell scripting, or use `--pretty` for readability.
- Rate limit: 50 requests per 10 seconds. Auto-retries on HTTP 429.
- The `--all` flag follows pagination Link headers to collect complete result sets. Use with caution on large datasets.
- Write operations (`advance`, `reject`) require an `On-Behalf-Of` user ID — this is the Greenhouse user performing the action.

## Not Covered (use direct API calls for these)

- Job post management (creating/editing job posts)
- Offer management (creating/approving offers)
- EEOC / demographic data
- Custom fields CRUD (create/update/delete — listing is supported)
- Webhook configuration
- Bulk operations
- Prospect management
- Approval flows
