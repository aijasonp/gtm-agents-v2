---
name: copy-qa-gate
description: Check and fix outbound sales copy (cold emails, follow-ups, LinkedIn messages, posts) so it reads like a person wrote it. Scores AI tells, banned phrases, em dashes, readability, length, unsourced claims and the number of asks, then rewrites to pass. Use whenever someone asks to review, score, humanize, de-slop or tighten outbound copy, or before any draft goes to a prospect.
---

# Copy QA Gate

Every draft gets a score out of 40. 32 passes. Below 32, rewrite and score again.

## With tools

Call `check_copy` with the draft (or `check_batch` for several). Report the score, then fix each item in `fix`. Re-run `check_copy` on your rewrite and show the new score. Do not claim a pass the tool did not return.

## Without tools

Score by hand with `references/rubric.md`, check every phrase in the built-in list below and in `references/banned-phrases.txt`, and show a one-line result per check.

Built-in banned phrases (always applied): delve, leverage, utilize, robust, seamless, synergy, game-changer, cutting-edge, best-in-class, world-class, revolutionize, unlock, empower, elevate, supercharge, streamline, holistic, tapestry, testament, "in today's fast-paced", ever-evolving, "I hope this email finds you well", "just checking in", "just following up", "touching base", "circle back", "quick question", "reach out", "I wanted to", "at the end of the day", "it's worth noting", "pain points", "move the needle", "low-hanging fruit".

## Rewriting

Use `references/rewrite-patterns.md`. Keep the sender's facts and offer; change only wording and structure. Never add a statistic, customer name or claim the original did not contain. If a claim needs a source, flag it instead of inventing one.

## Output

```
Score: 26/40 (fail)
Fix: banned phrases (leverage, reach out); 2 em dashes; 3 questions
Rewrite:
<rewritten draft>
New score: 36/40 (pass)
```
