# Pricing method

All money in the price book currency. Round half up to the cent after every step.

1. Unit price per line: the volume tier with the highest `min_qty` at or below the quantity. No tier: list price.
2. Line total = unit price x quantity. Line list total = list price x quantity.
3. Recurring subtotal = sum of recurring line totals. One-time lines (`one_time: true`) are added at the end and never discounted.
4. Term discount = recurring subtotal x the term's `discount_pct`. Only terms listed in the price book are allowed.
5. Extra discount = (recurring subtotal - term discount) x the requested discount %.
6. Annual recurring = recurring subtotal - term discount - extra discount.
7. Year one total = annual recurring + one-time lines.
8. Total contract value = annual recurring x term years + one-time lines.
9. Effective discount = 1 - annual recurring / recurring list total.

## Guardrails, in this order

1. Annual recurring below `floor_pct_of_list` of the recurring list total: blocked. No one can approve it.
2. Extra discount above the highest approval level: blocked.
3. Extra discount above the requester's role limit: needs approval from the lowest level whose limit covers it.
4. Otherwise: ok.

Tier and term discounts are policy and need no approval. Only the extra discount is checked against the role limits.
