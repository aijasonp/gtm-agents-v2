# Engagement scoring

Two numbers come out of every engagement:

1. **A Signal Scout signal** (for matched people at known accounts), with a type, a base weight from the taxonomy and a strength.
2. **Points** used to rank people in `top_engagers`.

## Signal types (social category in the Signal Scout taxonomy)

| Engagement | Signal type | Base weight | Half-life | Can the rep mention it? |
| --- | --- | --- | --- | --- |
| Comment with a buying question | social_buying_question | 0.85 | 14 days | Yes, to the commenter, by topic |
| Comment | social_comment | 0.60 | 21 days | Yes, to the commenter, by topic |
| Share or repost | social_share | 0.50 | 21 days | Yes, to the person who shared |
| Follow or subscribe | social_follow | 0.30 | 30 days | No |
| Reaction or like | social_reaction | 0.25 | 14 days | No |
| Two or more video views in 30 days | content_view_repeat | 0.30 | 14 days | No |

A single view is recorded but makes no signal.

A comment is a buying question when it mentions pricing, cost, a demo, a trial, evaluating, migrating, replacing, integrating, comparing, alternatives or asks how something works.

## Strength (0 to 1.5)

strength = persona x repeat x creator, capped at 1.5

- **Persona:** 1.0 for a buyer function at or above the minimum seniority in `company.yaml`; 0.85 for a champion function; 0.6 for anyone else or no title.
- **Repeat:** 1 + 0.25 for each earlier engagement by the same person in the last 30 days, capped at 1.5.
- **Creator:** the weight in `tracked_creators` (company page 1.0 by default).

## Points (for ranking people)

points = type points x persona x repeat x creator, x1.5 for a buying question

Type points: comment 5, share 4, follow 2.5, reaction 1, view 0.5.

## Dedupe

The same person, post, engagement type and day counts once, however many times the export repeats it.
