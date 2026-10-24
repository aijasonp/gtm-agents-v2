# Outbound Copy Rules

Standing rules for every email, LinkedIn message, subject line and document an agent writes for a rep. Product claims and proof points come from the product profile, never from memory.

## No Em Dashes
Em dashes are banned from all external content: emails, LinkedIn messages, subject lines, Slack posts and documents. No exceptions, including separators in subject lines.

Instead of em dashes:
- Clause continuation: comma, or period and a new sentence
- Before a customer or product elaboration: period, new sentence
- Subject line separator: colon ( : )
- Parenthetical aside: parentheses or commas
- Before "without", "not", "no": comma
- Between two independent clauses: semicolon or period

Before delivering any content, search for the literal em dash character and fix every hit. This applies to templates and subagent output too.

## Banned Slop Phrases
Never use:
- "If not, no worries" / "No worries at all" / "totally understand" / "I completely understand"
- "feel free to" / "Happy to show you"
- "Last one from me on this thread" / "Last note from me" / "Signing off on my end" / any AI "final email" opener
- "No hard feelings"
- Any sentence that reads as if the recipient works at the seller's company
- Wishy-washy opt-out language that sounds like a chatbot apologizing

The company name in the body is the prospect's company via `{{company_name}}`. Do not name the seller's company in the email body.

## No Fabricated Facts
Never invent stats, incident details, customer names or deployment numbers. Use only the proof points listed in the product profile (`proof_points`). If a claim is not there, leave it out.

Subagents hallucinate specific numbers. Fact-check every draft against the profile before it goes to a rep.

## Cold Email CTA Rules
Never use: "Worth 15 minutes?", "Happy to show you", "I'd love to chat", or time-specific asks.
Use instead: "Interested?", "Let me know if this resonates", "Curious to hear your take", "Open to hearing more?"

## Buyer Mapping
- Most buyers do not have the obvious title. Include architects, directors, platform and operations leads alongside the economic buyer.
- Most contacts are influencers, not signers. Write so a champion can forward the message and build an internal case.

## Writing Pipeline
All external content passes the full anti-slop stack before delivery.

Before drafting:
1. Voice system: `references/anti-slop-voice-system.md` (Section 0 filled in for the seller's brand, Sections 1-4 as written)
2. Product profile: product summary, pain points and proof points

While drafting:
3. No-slop constraints: `skills/no-slop/SKILL.md` and `skills/slopless-rules/writing-voice.md`
4. Banned vocabulary: `skills/no-ai-slop-rossmann/skills/no-ai-slop/references/ai-writing-detection.md`
5. Banned CTA patterns: see Cold Email CTA Rules

After drafting:
6. Pattern scan: `skills/avoid-ai-writing/SKILL.md` and `skills/humanizer-blader/SKILL.md`
7. Score 0-100 for AI tells. Above 30, rewrite.
8. Ask "What makes this obviously AI-generated?" and fix every tell.
9. 5+ banned-vocab hits plus 3+ structural patterns plus uniform rhythm means a full rewrite.
10. Copy QA Gate: `check_copy` must pass (32 of 40).

Outbound sequences also:
11. `python3 skills/unslop/scripts/banned_phrase_scan.py` must score under 3 violations
12. `python3 skills/unslop/scripts/readability_metrics.py` should show high sentence-length variance

## Customer-Facing Commitments Need a Source
Do not write "we're filing X", "we're evaluating Y" or "we're shipping Z" in a customer-facing draft unless you can point to a verifiable artifact: a ticket, a written commitment from someone with authority, or an open PR. Your own analysis is not a source. For every "we will" or "we are" sentence, ask what the source is. If there is none, create the artifact first or drop the sentence. Internal follow-ups go to the rep, not the customer.

## Campaign Copy and Approval
Agents write 100% of campaign copy. Sequencer AI copy generators are never used. Every subject line, body, follow-up and LinkedIn invite is written by the agent, run through the writing pipeline above, and only then pushed to the sequencer.

No campaign sends until the owning AE approves the copy:
1. The agent writes the copy and runs the anti-slop stack (under 3 violations).
2. The agent sends a test email for every sequence step to the approver before activating.
3. The approver confirms the copy.
4. Only after explicit approval does the agent start the campaign.

Never skip the humanizer pass. If copy sounds AI-generated, it is not done. Rewrite until it reads human: varied sentence length, no rule-of-three, no filler, no third-person self-reference, real paragraph breaks.

### Lemlist API notes
- `status: draft` from GET is the validation state, not the run state. Confirm run state with POST `/campaigns/{id}/pause` (200 `state:paused` means it was live) or POST `/campaigns/{id}/start` ("already running" means live). To stop a live campaign use POST `/campaigns/{id}/pause` (PATCH returns 405).
- Update live step copy with PATCH `/sequences/{seq_id}/steps/{step_id}` and body `{"type":"email","subject":...,"message":...}`. The `type` field is required. The campaign-scoped path returns 405.
- Lemlist renders the message as HTML, so `\n` collapses to a space. Convert `\n\n` to `<br><br>` and `\n` to `<br>` before pushing, in build scripts and live updates.

## Spintax + Deliverability Patterns (ported from coldoutboundskills review, 2026-09-21)

These are additions to the rules above. Where one conflicts with a rule above, the rule above wins.

### Smartlead Spintax Rules

**Syntax:** `{option1|option2|option3}`. Smartlead picks one option at random per send, so no two emails are identical. This reduces pattern detection by spam filters. Spintax is Smartlead-native syntax, NOT Jinja/Liquid, so it does not violate the "only `{{variable_name}}` merge tags" rule in `references/smartlead-api.md`.

**Where to use it:** subject lines, openers/greetings, opt-out lines, CTAs, and transition words. Use 2-3 options per block.

**What to spin:**
- Always: greetings (`{Hey|Hi}`), opt-out lines, CTAs, transition words ("just", "also", "actually").
- When natural: verb choices (`{help|work with}`), sentence-level rephrasings.

**Never spin:** Smartlead variables (`{{first_name}}`, `{{company_name}}`, custom vars), signature placeholders (`%signature%`), specific data points (numbers, stats, brand names, pricing), and technical terms that must stay precise.

**The golden rule, no broken combinations:** Every combination Smartlead could randomly assemble must read as a natural, grammatically complete sentence. Make each spintax block a self-contained phrase so options don't depend on a nearby block. Instead of dependent blocks that can break (`{let me know if|would} {{name}} {would be better|be a better person}`), write each option as a full standalone phrase. When sentence structure makes independent blocks risky, wrap the whole sentence in one spintax block with full-sentence alternatives. After adding spintax, mentally walk every adjacent-block pairing; if any sounds off, restructure.

**Tone preservation:** All options must match the register of the original. If the original is casual, all options are casual. Don't mix `{Worth a shot?|Would you be amenable to a trial?}`; that's a register mismatch.

**⚠️ Spintax is a RANDOM chooser, not a conditional.** Never use spintax as an if-populated gate for a variable. `{Saw {{funding_line}}. |}` renders `Saw .` on empty rows about half the time and throws away the personalization about half the time. Instead of spintax-gating a variable, use a self-erasing variable (put the whole sentence in the variable so an empty value renders nothing) or split the list at upload time into populated/empty campaigns. Spintax is for wording variety only, never for conditional content.

### Spam-Word Additions 

Our existing rules already ban the slop phrases ("feel free to", "no worries", "happy to show you", etc.) and the AI-tell vocabulary (leverage, synergy, ecosystem, robust, etc.). The following are NEW deliverability spam-trigger words/phrases we did NOT already ban. Add these to the banned list; they are spam-filter triggers, not just AI tells.

**Banned single words (spam triggers):** `get`, `bank`, `credit`, `access`, `open`, `compare`, `problem`, `now`, `billing`, `deal`, `finance`, `financial`, `claims`, `insurance`, `mortgage`, `soon`, `new`, `performance`, `freedom`, `home`, `sales`, `medical`, `urgent`, `life`, `marketing`, `investment`, `diagnostics`, `friend`, `cash`, `invoice`, `extra`, `purchase`. Punctuation, hyphens, or splits do not make a banned token safe (`cash-cycle` is still `cash`).

**Banned short phrases:** `off chance`, `one time`, `all good`, `following up here`, `last note from me here`, `great fit`, `bumping this once`, `just following up once`, `circle back`, `one more quick follow-up`, `keep this open`, `compare notes`, `compare notes live`, `appreciate the reply`.

**High-risk promotional/pressure wording (banned):** `$$$`, `50% off`, `100% guaranteed`, `100% free`, `100% off`, `100% satisfied`, `access now`, `act fast`, `act immediately`, `act now`, `action required`, `affordable deal`, `amazing`, `amazing deal`, `amazing offer`, `apply here`, `apply now`, `avoid bankruptcy`, `bargain`, `best bargain`, `best deal`, `best offer`, `best price`, `best rates`, `big profit`, `bonus`, `buy now`, `buy today`, `call now`, `can't live without`, `cash bonus`, `cash out`, `claim now`, `claim your discount`, `click`, `click below`, `click here`, `click this link`, `contact us immediately`, `deal ending soon`, `discount`, `don't delete`, `double your money`, `double your wealth`, `drastically reduced`, `earn`, `earn cash`, `earn extra income`, `earn money`, `easy income`, `exclusive deal`, `expires today`, `extra cash`, `extra income`, `fantastic`, `fantastic offer`, `fast cash`, `final call`, `for free`, `free access`, `free consultation`, `free gift`, `free membership`, `free money`, `free quote`, `free trial`, `full refund`, `get it now`, `get out of debt`, `get started now`, `giveaway`, `great news`, `guaranteed deposit`, `guaranteed results`, `hurry up`, `important information`, `immediately`, `increase revenue`, `increase sales`, `incredible deal`, `instant earnings`, `instant income`, `instant savings`, `investment advice`, `join millions`, `limited time`, `lowest price`, `make money`, `million dollars`, `money-back guarantee`, `must read`, `no catch`, `no cost`, `no obligation`, `no strings attached`, `once in a lifetime`, `only $`, `only available here`, `order now`, `order today`, `please read`, `price protection`, `profits`, `promise`, `pure profit`, `quote`, `risk-free`, `satisfaction guaranteed`, `save $`, `save big money`, `save up to`, `sign up free`, `special invitation`, `special offer`, `special promotion`, `supplies are limited`, `take action now`, `the best`, `this won't last`, `thousands`, `time limited`, `today`, `top urgent`, `trial`, `unbeatable offer`, `unbelievable`, `unlimited`, `urgent`, `what are you waiting for?`, `while supplies last`, `why pay more?`, `will not believe`, `winner announced`, `wonderful`, `you are a winner`, `you will not believe your eyes`.

**Phishing/security-warning language (banned):** `access your account`, `account update`, `activate now`, `change password`, `click to verify`, `confirm your details`, `confidential information`, `data breach`, `download now`, `final notice`, `important update`, `immediate action required`, `install now`, `last warning`, `log in now`, `new login detected`, `password reset`, `payment details needed`, `phishing alert`, `security breach`, `security update`, `update account`, `verify identity`, `warning message`.

**Formatting bans (add to existing):** no ALL CAPS, no multiple exclamation marks, no fake urgency, no misleading subject lines, no excessive links.

**Unsubscribe/closeout line rule:** Never write an unsubscribe line that promises to stop following up based on silence. We DO follow up, that's the point of sequences. Instead of "I'll take silence as a no" / "read no reply as a pass" / "if I don't hear back I'll leave it here", write an action-conditional line: "A reply of 'no' / 'pass' is enough and I'll step out of your inbox", "Just say the word and I'll stop", "A one-word reply works fine if you'd rather I stopped". The user has to do something explicit for the sequence to stop; silence keeps the cadence running.

**Safe replacement patterns:** instead of `free consultation` → `open to a short conversation`; instead of `special offer` → `what we're seeing in the market`; instead of `act now` → `if relevant, happy to send details`; instead of `guaranteed results` → `this may be relevant depending on your situation`; instead of `click here` → `let me know and I can send it over`; instead of `limited time` → `not sure if this is timely for you`; instead of `increase revenue` → a precise business outcome.

### Per-Lead Sub-Agent Personalization Pattern

We already do per-lead custom variables (situation/value/CTA lines pushed as Smartlead custom fields). Two rules matter most: the **tune-then-scale approval loop** and the **strict 3-field output schema**. Adopt these:

1. **Tune before you scale.** Don't personalize 500 leads and then discover the prompt is wrong. Instead of fanning out immediately, run a sample on 1 lead, show the user the generated `situation_line`/`value_line`/`cta_soft`, collect edits, then run a batch of 10 with approval. Lock the prompt only after 2 consecutive rounds with zero edits, then scale to the full list.
2. **Keep the output schema to 3 fields max** (`situation_line`, `value_line`, `cta_soft`). Fewer fields = less that can go wrong. Map each to a Smartlead custom var (`{{situation_line}}`, `{{value_line}}`, `{{cta_soft}}`).
3. **Batch size 10-20 leads per sub-agent.** Bigger batches are cheaper but worse quality; smaller are higher quality but more context. For 1,000+ leads, run in rounds of 100 (10 sub-agents × 10 leads).
4. **Never ship a fabricated or thin-data line.** If a lead's `company_description` is missing or <20 chars, set the fields to null and use static copy instead. Filter out any field containing "cannot be generated" before upload.
5. **Spot-check 5 random leads per variant before upload** for repetition, factual errors, unnatural phrasing, and hedging. Add a "assert, don't hedge" rule if lines come out vague.
6. **This must still pass the approval and test-email gate** (see Campaign Copy and Approval above) and must NEVER reintroduce `{{personalization_line}}` (banned in `references/smartlead-api.md`). The tuned prompt replaces the Clay-AI-fabricated field with a human-approved one.

**Sub-agent prompt rules to enforce (port):** never fabricate facts (if thin, be general but not false); never use em dashes; never use "leverage", "synergy", "ecosystem", "world-class", "cutting-edge", "solutions"; never start `situation_line` with "I noticed" (overused); max ~20 words per field; assert, don't hedge.
