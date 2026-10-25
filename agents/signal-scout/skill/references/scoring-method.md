# Scoring method

The runtime computes this in code (`gtm_core.scoring`). In the drop-in edition, follow it by hand.

## 1. ICP fit (0 to 100)

Components, each 0 to 1, weighted per `icp.yaml`:

| Component | Rule |
| --- | --- |
| industry | 1.0 if it matches a target industry, 0.2 if not, 0 overall if excluded |
| employees | 1.0 inside the range; outside, 1 - log2(distance ratio) / 2, floor 0 (half credit at 2x away) |
| country | 1.0 if listed, else 0 |
| revenue | same curve as employees |
| tech | 1.0 if any listed tool is in their stack, else 0.3 |

Unknown components are dropped and the remaining weights renormalized. No data at all = 50.

## 2. Signal heat (0 to 100)

For each signal:

```
contribution = weight x strength x 0.5 ^ (age_days / half_life_days)
```

- weight: the learned weight if one exists, otherwise `base_weight` from the taxonomy
- strength: 1.0 unless the source says otherwise (0 to 1.5)
- repeats of the same signal type: sort by contribution; the 1st counts fully, the 2nd half, the 3rd a quarter

```
raw = sum of contributions
heat = 100 x (1 - e^(-raw / 1.5))
```

## 3. Stacking

Count categories with at least one contribution of 0.15 or more. Apply the single best matching rule:

| Rule | Condition | Multiplier |
| --- | --- | --- |
| two_categories | 2+ categories | 1.15 |
| three_categories | 3+ categories | 1.30 |
| money_plus_hiring | money and hiring present | 1.25 |
| change_plus_intent | leadership and intent present | 1.35 |

heat = min(100, heat x multiplier)

## 4. Total and tier

```
score = 0.4 x ICP + 0.6 x heat
```

| Tier | Rule |
| --- | --- |
| X | ICP below 30 (never surfaced) |
| A | 75+ |
| B | 55 to 74 |
| C | 35 to 54 |
| D | below 35 |

## 5. Weekly learning (persistent edition only)

For each signal type seen on 5+ accounts with outcomes in the last 120 days:

```
lift = P(positive | had signal) / P(positive)       (smoothed, +1 / +2)
target = base_weight x sqrt(lift)
new = 0.7 x current + 0.3 x target, bounded to [0.25x, 3x] base_weight
```

Positive outcomes: reply_positive, meeting, opportunity, closed_won.

## Judged ICP blend

```
coverage = answered question weight / total question weight
b        = blend x coverage            (blend from config, default 0.5)
icp      = (1 - b) x rule_fit + b x judged_score
signal   = signal_heat x relevance     (relevance from floor 0.85 to ceiling 1.15)
```

Question scores: yes = 1, no = 0; a choice uses its option value; a 1 to 5 score maps to (n - 1) / 4. Weekly, each question's weight multiplier moves toward the square root of its engagement lift (human open 0.4, reply 0.6), bounded to 0.5x through 2x, and only with 20 emailed accounts on each side.
