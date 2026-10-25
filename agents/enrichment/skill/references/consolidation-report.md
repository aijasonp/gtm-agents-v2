# Consolidation report

Use `waterfall_report` (default last 30 days) to decide which data tools to keep.

| Column | Meaning |
| --- | --- |
| calls | lookups sent to the provider (skipped calls with missing keys are counted apart) |
| hits | lookups where this provider filled the field it was asked for |
| hit_rate | hits divided by calls |
| cost | total spend on the provider in the window |
| cost_per_hit | cost divided by hits: the number to compare across tools |

## Reading it
- **Keep** the provider with the lowest cost per hit for each field, as long as its hit rate holds up.
- **Cut candidate**: a source that filled under 10% of all values found. Most of what it returns another provider already found first.
- **Order**: put the keeper first. Providers late in the order only see the leftovers, so their hit rate looks low; move one up for a week before cutting it.

## Writing the memo
1. Fill rate by field, before and after.
2. Spend by provider and cost per hit.
3. The keep or cut call per tool, with renewal date and contract amount from the stack inventory.
4. What changes for reps (nothing, if coverage holds).
