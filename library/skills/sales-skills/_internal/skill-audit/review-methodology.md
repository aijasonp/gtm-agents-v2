# Skill Review System — top-to-bottom audit of `skills/`

Goal: every skill (1) follows the authoring standards in `memory/skill-standards.md`
and (2) is current with the API / pricing / behavior of the platform it documents.

538 skills is too many to eyeball. The review is split into **three passes** ordered
by cost. Cheap deterministic checks run first and produce the worklist that the
expensive LLM/web passes consume, so we never spend tokens re-discovering things a
script can find for free.

| Pass | What it checks | Cost | Tool | State |
|---|---|---|---|---|
| 1. Static lint | Mechanical standards: frontmatter, sizes, sections, evals, structure, forbidden tokens | Free, seconds | `scripts/lint-skills.py` | `lint-report.json` |
| 2. Semantic quality | Judgment: trigger realism, 250-char front-loading, routing-shell vs knowledge-dump, eval meaningfulness, cross-ref correctness | LLM, ~1 agent/skill | subagents / `dspy-skill-quality` skill | per-skill verdicts |
| 3. API currency | Live diff of endpoints, auth, rate limits, webhooks, pricing tiers vs the platform's current docs | LLM + web, several fetches/skill | subagents w/ WebFetch+WebSearch | restamped `learnings.md` |

The lint report is the **shared backbone**: it ranks skills by staleness and flags
coverage gaps, which is how passes 2 and 3 decide what to look at first.

---

## Pass 1 — Static lint (`scripts/lint-skills.py`)

Deterministic, no network, no LLM. Run:

```bash
python3 scripts/lint-skills.py --json _internal/skill-audit/lint-report.json
# PII guardrail (patterns kept OUT of the repo — see below):
SKILL_LINT_PII_FILE=~/.config/skill-pii.txt python3 scripts/lint-skills.py
```

Severities: **ERROR** = hard rule violation, **WARN** = soft/heuristic, **INFO** = staleness/coverage.

Checks: required frontmatter fields; `name` == folder, kebab-case, no reserved words;
description ≤1024 chars, has a negative trigger, no XML, flags pricing/years;
license=MIT; semver; tags array; body ≤200 lines (≤500 for routers/strategy skills);
presence of Examples / Troubleshooting / Related sections (matched by heading keyword);
evals exist with ≥3 cases and 2-4 assertions each; `learnings.md` present; references
one level deep; **dead-route validation** (every `/sales-*` reference must name a real
skill folder); and the two **universal forbidden-token rules** below.

### Universal rule: no self-attribution ("author")
No skill may credit a human/maker. Scoped **precisely** to attribution forms — a YAML
`author:` key, an `Author:` label, an `## Author` heading. It deliberately does NOT
match third-party API field names (`"author":` JSON fields, Ghost's `/authors/`
endpoint, Tomba's "Author Finder" product, "co-author"): those are accurate platform
docs and scrubbing them would corrupt the references. Current corpus: **1 real hit**
(`sales-request-skill` ships an `author:` line in a frontmatter template — fix because
that skill scaffolds new skills and would propagate the field).

### Universal rule: no PII (user's real name / email / company)
The user's real identity must never appear in any file. Patterns are supplied **out of
band** so the literal email/name is never written into the committed linter (which
would itself violate the rule):
- `SKILL_LINT_PII` — comma-separated literals, or
- `SKILL_LINT_PII_FILE` — path (keep it **outside** the repo, e.g. `~/.config/`) to a
  file of one regex per line, e.g. `\bLars\b`, `@buzztrail\.ai`, `\bbuzztrail\b`.

If neither is set the PII scan is skipped (report prints `PII scan: OFF`). With the real
patterns loaded the corpus is **clean — 0 hits**; the guardrail exists to catch a future
accidental paste. Do NOT derive patterns from `git config` — the git identity here is an
intentional alias (yahoo address) unrelated to the real user, and deriving a company
name from a generic mail domain produced 60+ false "Yahoo/Gmail" matches.

### Current Pass-1 results (rerun to refresh)
11 ERRORs / 8 skills, all trivial: 7 missing `license: MIT`; `sales-enrich` needs a 3rd
eval; `sales-request-skill` author-template + license; `sales-third-party` missing
argument-hint, license, and `evals.json`. Plus soft WARNs: 85 descriptions embed pricing
(policy call — recent practice intentionally keeps key price gates), 48 missing a
Related-skills section, 66 strategy/long bodies, and 39 eval shape nits.

---

## Pass 2 — Semantic quality (LLM)

What a regex can't judge. One subagent per skill (batch via a workflow), each returning
a structured verdict. Prioritize skills the linter WARNed and the highest-traffic skills.

Check per skill:
- **Description** — first 250 chars carry WHAT + primary trigger; triggers are real
  user problem-language, not feature jargon; negative triggers point to the right
  sibling skill.
- **Body is a routing shell**, not a knowledge dump (detail lives in `references/`);
  follows the 5-step pattern; steps explicitly load/unload references.
- **Evals are meaningful** — cover typical + edge + confusion; assertions test concepts
  not exact phrasing (per `feedback_resilient_evals`).
- **Cross-refs resolve** — Related-skills and router pointers name skills that exist;
  disambiguation rules in `sales-do` are consistent.

The installed `dspy-skill-quality` skill already encodes much of this checklist and can
drive the per-skill pass.

---

## Pass 3 — API currency (LLM + web) — the hard one

For each **platform** skill, diff the recorded API/pricing against the platform's current
docs. This is where "up to date with the API they call" is actually verified.

**The blocking gap:** of 258 API-calling skills, only **13 carry a datable research
stamp** — 245 have no recorded capture date, so freshness is unknowable without a live
check. 57 skills mention an API in their description but ship **no** `*-api-reference.md`.
First remediation step is therefore to **stamp every skill** with its research date so
staleness becomes measurable going forward.

Per-skill procedure (one subagent, given the skill's current refs):
1. Find the source — `learnings.md` / `*-api-reference.md` usually cite doc URLs; else
   WebSearch `"<platform>" API docs / pricing`.
2. Fetch current docs; compare base URL, auth scheme, endpoints, params, rate limits,
   webhook events + payload + signing, and pricing tiers / plan gates.
3. Emit a structured diff: `unchanged | changed | removed | new`, with the doc URL as
   evidence (adversarially verify "changed/removed" before trusting — docs move and 404).
4. If drift is real: update the reference file, restamp the research date, append a dated
   note to `learnings.md`, re-run that skill's evals.

**Prioritize:** dated-and-stale first (13 skills, oldest = `sales-fathom`/`sales-grain`/
`sales-sembly` at ~2mo), then high-traffic platforms (Apollo, HubSpot, Salesforce,
Klaviyo, Stripe…), then the 245 undated. Volatile surfaces (pricing, rate limits) drift
fastest; static surfaces (auth scheme) rarely change — weight effort accordingly.

---

## Orchestration & cadence

- **Pass 1** every run / pre-commit — it's free. The JSON report is the state file.
- **Pass 2 & 3** are batched fan-outs (the `Workflow` tool, or `Agent` subagents in
  parallel). They are token-heavy at 538 skills — run in waves (stalest/highest-traffic
  first), review each wave's structured output, then proceed. Re-running Pass 1 after a
  wave measures progress (errors burned down, dates restamped).
- Track remediation against `lint-report.json` so "done" is measurable, not vibes.

## Calibration decisions baked in
- Strategy skills (carry `references/platforms.md`) get the 500-line cap like routers.
- Pricing-in-description is a WARN, not an ERROR — current practice intentionally keeps
  decision-critical price gates in the description. Decide policy before mass-scrubbing.
- "author" rule is attribution-only by design (see above) to avoid corrupting API docs.
