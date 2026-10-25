# Call analysis method

Everything below is rule-based and repeatable. A model may add a better summary, but it never replaces these counts.

## Inputs

- Transcript as plain "Speaker: text", WebVTT/SRT, or JSON turns. Zoom, Teams, Meet, Gong, Fathom and most notetakers export one of these.
- Your side of the call: `team.rep_names` in `company.yaml`. Everyone else is the buyer side.
- Competitor names: `competitors` in `company.yaml`.

## What gets measured

| Measure | How |
| --- | --- |
| Talk ratio | Words spoken by your side divided by all words |
| Questions | Question marks in your side's turns |
| Longest monologue | Most words in one uninterrupted turn |
| Next steps | Sentences with "next step", "follow up", "send over", "by Friday", "next week" and similar |
| Pricing talk | Sentences with price, budget, cost, quote, discount, contract or a dollar figure |
| Objections | Buyer sentences matching price, timing, authority, competition, need, security or integration patterns |
| Competitors | Any sentence naming a competitor from `company.yaml` |
| MEDDPICC evidence | Buyer sentences that hint at each element (see the element cues below) |

## MEDDPICC cues (buyer side only)

- Metrics: percentages, ROI, "save hours", "reduce", "increase"
- Economic buyer: "signs off", "final say", "budget owner", "CFO", "approval"
- Decision criteria: "must have", "requirement", "needs to support"
- Decision process: "process", "committee", "pilot", "evaluation"
- Paper process: "procurement", "legal", "MSA", "security review", "purchase order"
- Identified pain: "problem", "struggle", "manual", "takes forever"
- Champion: "I'll push this internally", "introduce you to"
- Competition: "alternative", "evaluating", "already use", or a named competitor

Evidence found on a call only raises a missing element to "partial". Confirmation needs a person or an explicit CRM value. The agent proposes; Deal Inspection and the rep decide.

## Flags

- Your side talked more than 65% of the call
- Fewer than 3 questions from your side
- A rep monologue over 250 words
- No clear next step heard
