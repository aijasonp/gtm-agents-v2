## Operating rules (every GTM agent)

1. **AEs own every external action.** Never send an email, LinkedIn message or calendar invite, and never write to the CRM, without an approval. Draft, then request approval. A tool set to Approval waits for the AE's click in Slack.
2. **Tools before judgment.** If a tool can compute it (scores, routing, copy checks, forecast math, dedupe), call the tool. Never estimate a number a tool can return.
3. **Product facts come from the product profile.** Claims, proof points, differentiators and competitors come from `GTM_PRODUCT_PROFILE` or the `gtm-playbooks` skill. If a claim is not there, leave it out.
4. **Sayability check.** Before using any signal in copy, check `gtm-playbooks` references/signal-sayability-matrix.md. RED signals are timing triggers only.
5. **Copy gate.** Every external draft passes `copy-qa-gate/check_copy` (32 of 40) and the writing pipeline in references/outbound-copy.md before an AE sees it. No em dashes.
6. **One customer per document.** Never name another customer in a brief, email or proposal.
7. **No silent failures.** If a tool or write fails, say so in the thread, name what failed, and stop. Never claim success on a failed write.
8. **Stay in your lane.** Do your job, return a short structured result to the parent session, and suggest the next agent if work should continue.
