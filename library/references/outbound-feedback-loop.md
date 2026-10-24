# Rep Feedback Loop: Rep Feedback to GitHub PR

**Owner:** Win/Loss Learning agent · **Reviewer:** GTM engine owner · **Status:** Active

This is the human feedback loop for the outbound system. When AEs flag bad data, weak copy, or leads that should be suppressed, the agent turns that feedback into a structured record and a GitHub PR for the engine owner to review. It complements the automated reply-data loop, which is separate.

## How reps submit

Reps describe the problem in plain language. No forms or templates. Either:

- DM the agent, or
- post in the outbound feedback channel.

The agent reads the message, classifies it, and handles the rest. Reps do not need to know the taxonomy.

## Classification taxonomy

Each piece of feedback gets exactly one type:

| Type | Meaning | Examples |
|------|---------|----------|
| `data-quality` | Wrong or stale contact or company data | Wrong email, wrong title, wrong company info, dead domain |
| `copy` | Weak or off-brand sequence language | Reads like AI slop, off-brand tone, bad subject line, confusing CTA |
| `suppression` | Lead should not be contacted | Hard bounce, unsubscribe, wrong person, out of ICP, do not contact |
| `signal-miss` | Company showed intent we did not catch | New funding, hiring spree, leadership change, job posting we missed |
| `process` | Workflow or tooling issue | Campaign misconfigured, duplicate task, broken integration, timing bug |

## What happens

1. The rep submits feedback (DM or the feedback channel).
2. The agent classifies it into one of the five types.
3. The agent writes a record to `gtm-vault/feedback/rep-feedback/YYYY-MM-DD-<slug>.md` (all fields, UTC timestamp, `status: pending-review`).
4. The agent opens a PR in the configured feedback repo (`FEEDBACK_REPO`) on branch `rep-feedback/YYYY-MM-DD-<slug>`.
5. The agent posts the PR link back in the original Slack thread.
6. The owner reviews:
   - **Merge** means accepted, and the agent applies the action mapping below.
   - **Close** means rejected, and nothing happens.

## Action mapping (after merge)

| Type | Action after merge |
|------|--------------------|
| `suppression` | Add the company or domain to the sequencer and enrichment suppression lists |
| `copy` | Update `references/outbound-copy.md` with the corrected language |
| `data-quality` | Note the correction in `account-knowledge/<slug>.md` |
| `signal-miss` | Tune the signal scanner config to catch the missed signal type |
| `process` | Fix the workflow or tooling issue and log the fix |

## SLA

- PR opened within minutes of the feedback.
- The owner reviews at their own pace. No automated nagging. Merge or close is the signal.

## Tooling

- CLI: `python3 outbound-engine/rep_feedback_pr.py`
- Idempotent: identical open PRs are not duplicated.
- Never auto-merges. Merge or close is always a human decision.
- No silent failures: every step logs to stderr, and any failure exits non-zero.
