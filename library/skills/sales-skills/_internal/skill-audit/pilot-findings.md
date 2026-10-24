# Pilot findings — Pass 2 (quality) & Pass 3 (API currency)

Ran 2026-06-13 to validate the LLM/web passes and measure per-skill cost before the
full sweep. One subagent per skill, structured return.

## Pass 3 — API currency (3 oldest dated skills)

Cost: ~45–75K tokens, ~75–80s wall-clock per skill. **All 3 found drift** even though
the corpus is only ~2 months old → the full 258-skill sweep is justified.

| Skill | Verdict | Key drift found |
|---|---|---|
| sales-fathom | minor drift | NEW `/meeting_types` endpoint; NEW heavy-request rate-limit tier (30→5/min on transcript/summary calls) that **contradicts the skill's flat-60/min backfill advice**; new `include_highlights`/`meeting_type`/`meeting_url` fields; nonprofit offer is 10 free Team (not Business) seats; pricing host moved fathom.video → fathom.ai |
| sales-grain | **significant drift** | Endpoints are versioned `/_/public-api/v2/...` with a **required `Public-Api-Version` header**; real rate limit is **300/min** (skill said "no published limit, 1/sec"); **webhooks entirely missing** from the skill; MCP prompt set changed (9, plan-gated) vs the 4 "free on all plans" the skill claims; API tier gate (Business vs Enterprise-beta) ambiguous → manual check |
| sales-sembly | current (minor) | Core model accurate (outbound-webhook-only, no inbound REST; MCP on Pro+). Only new detail: per-user native automation counts (Basic 3 / Pro 5 / MAX 20). Webhook signing UNVERIFIED (helpdesk 403) |

Method works. Agents were appropriately skeptical (marked UNVERIFIED rather than guessing
when docs were inaccessible). Each returns ready-to-apply ACTIONS (file + change).

## Pass 2 — semantic quality (3 skills: platform / strategy / first-party)

Cost: ~44–56K tokens, ~25–35s per skill.

| Skill | Grade | Most important fix |
|---|---|---|
| sales-apollo | B | Step 3 inline module knowledge (dialer/analytics/credits/admin) should move to `references/platform-guide.md` — body reads as a knowledge dump |
| sales-note-taker | A | Exemplary strategy skill; only re-verify the stale pricing baseline |
| sales-deal-room | B | Add the required negative-trigger clause to the description; **remove dead `/sales-close` route** |

## What the pilots taught the tooling (already applied to lint-skills.py)

1. **Section check was heading-literal** → false-flagged Apollo's "Step 5 — Related skills"
   and similar. Fixed to match by heading keyword; section WARNs 57 → 10.
2. **Cross-ref integrity is a real gap** the linter can check deterministically. Added a
   dead-route validator: **10 distinct dead routes, 21 references** corpus-wide —
   `/sales-outreach` ×5, `/sales-discovery` ×3, `/sales-close` ×3, `/sales-pipeline` ×3,
   `/sales-objection` ×2, plus `/sales-research`, `/sales-positioning`, `/sales-follow-up`,
   `/sales-proposal`, `/sales-enablement`. These need mapping to their real targets
   (renames) or removal — judgment per case, not mechanical.

## Cost extrapolation for the full sweep
- Pass 3 (API currency), all 258 API skills: ~258 × ~55K ≈ **~14M tokens**, runnable in
  waves of ~16 concurrent agents.
- Pass 2 (quality), all 538: ~538 × ~50K ≈ **~27M tokens**.
Best run as a `Workflow` pipeline (verify → adversarially confirm "changed/removed" →
apply edits in a worktree → restamp date → append learnings → re-run that skill's evals).
