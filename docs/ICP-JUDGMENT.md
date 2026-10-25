# Judged ICP scoring

ICP fit is the base of everything downstream. Better fit means the right accounts get emailed with the right pain, which drives opens and replies. This page covers how the judged half of ICP fit works and how it learns.

## Two halves

1. **Rule fit** (`core/gtm_core/scoring/icp.py`): firmographics against `config/icp.yaml` (industry, headcount, revenue, country, tech). It is deterministic and explainable. An excluded industry is a hard zero.
2. **Judged fit** (`core/gtm_core/decision/`): typed questions that firmographics cannot answer, such as "Do they sell through reps?", "What is the sales motion?" or "Which of our pains is top of mind?".

```
coverage = answered question weight / total question weight
b        = blend x coverage
icp      = (1 - b) x rule_fit + b x judged_score
```

If evidence is thin, coverage is low and the judgment moves the score only a little. An excluded industry stays out whatever the judgment says.

## Typed questions

Questions live in `config/icp.yaml` under `judgment.models`. Each question has one of three kinds:

| Kind | Valid answer | Score |
| --- | --- | --- |
| `bool` | true or false | 1 or 0 |
| `choice` | one of `options` | the option's value, 0 to 1 |
| `score` | an integer from 1 to 5 | (n - 1) / 4 |

An answer that does not fit its kind is rejected, never coerced. A question with weight 0 is still answered and used. `primary_pain` works this way: it does not move the score, but ICP Outbound uses it to choose the pain to lead with.

## Backends

| Backend | When | Notes |
| --- | --- | --- |
| `rules` | offline, tests, evals, and fallback for every other backend | Answers only from evidence terms and numeric bands set in config. Unknown when there is no evidence. |
| `model` | when a model key is set | The cheap model answers all questions as JSON. Each answer must quote evidence that is found in the account's facts, or it is dropped. |
| `remote` | when `GTM_DECISION_URL` is set | Any HTTP decision service, for example one running on Cloudflare Workers AI or a typed-decision runtime. POST `{model, version, state, questions}` and get back `{answers: {id: {value, evidence, confidence}}}`. Validated the same way. |
| `shadow` | while trialing a new backend | Returns the primary backend's verdict and stores the candidate's answers and agreement rate next to it. |

With `backend: auto`, the order is remote, then model, then rules. If a question goes unanswered, it falls back to rules, so a model outage drops you to the offline answers instead of to nothing.

Verdicts are cached in the `decisions` table by state hash and model fingerprint. An unchanged account is not judged again until `cache_days` pass. A new signal, or any edit to a question, triggers a fresh judgment.

## Signal relevance

The `signal_relevance` model asks how directly the recent signals point at a pain we solve. Signal heat is multiplied by a factor from `floor` (0.85) to `ceiling` (1.15).

## The open-rate loop

1. **Tracking.** ICP Outbound tags every draft and sequence with `angle_key` (for example `signal:funding_round`, or `value_led`) and `value_prop`.
2. **Events.** Sequencer events (sent, open, click, reply, bounce, unsubscribe) arrive at `POST /v1/email-events` or through `record_email_event`. Lemlist and Smartlead webhook names map automatically.
3. **Machine opens.** Opens flagged by the sequencer, or arriving within 5 seconds of the send, are stored but left out of every rate. A reply or click counts as a human open.
4. **Unsubscribes and bounces.** These suppress the contact locally at once, so no agent drafts to that address again.
5. **Choosing the pain.** For each new sequence, ICP Outbound picks the value prop from three inputs: the judged primary pain (a prior), the persona default (a smaller prior), and smoothed open and reply rates by value prop. A small exploration bonus keeps under-tested pains in play. The pick is deterministic: same data, same choice.
6. **Weekly learning** (Signal Scout `weekly_reweight`). Each judged question's weight multiplier moves toward the square root of its engagement lift. Engagement is 0.4 for a human open plus 0.6 for a reply. Multipliers stay between 0.5x and 2x, and a question only moves once 20 emailed accounts sit on each side of it.
7. **Proof.** The weekly post shows open and reply rates by judged ICP band. If better fit is not producing better opens, the questions need work.

## Tools

- Signal Scout: `judge_account`, plus `explain_score` (which now shows rule fit, judged fit and the answers behind it).
- ICP Outbound: `record_email_event`, `angle_performance`, and the `weekly_angle_report` job.

## Editing the questions

Edit `config/icp.yaml` and bump `version` on the model to re-judge every account. Keep questions answerable from facts you actually have: description, keywords, tech, signal titles and firmographics. Clay enrichment (`push_to_clay`, `import_clay`, `POST /v1/enrichment`) fills those fields.
