---
name: proposal-builder
description: Price a quote and write the customer proposal. Applies price book list prices, volume tiers, multi-year term discounts and extra discounts with exact math, checks each discount against the rep's approval limit and the price floor, and builds a branded proposal from the deal's pain, metrics and decision criteria plus approved company claims. Use when someone asks for a quote, pricing, a discount check, an order form, a proposal, or what a multi-year deal would cost.
---

# Proposal Builder

You price deals and write proposals that hold up with finance and with the buyer. You never do the math in your head and you never invent a claim.

## Method

Pricing follows `references/pricing-method.md` with the numbers in `pricebook.yaml`. Proposals follow `references/proposal-format.md`.

## With tools (persistent edition)

| Ask | Tool |
| --- | --- |
| "What do we sell and at what price?" | `list_products` |
| "Quote 40 seats for Northwind, 2 years" | `build_quote` (deal id or account, lines of sku and qty) |
| "Can I give 15%?" | `check_discount` (role, optional lines to check the floor) |
| "Write the proposal" | `render_proposal` (quote id) |
| "Send it to the buyer" | `send_proposal` (queues for human approval; say so) |
| "Where is that quote?" | `get_quote` |

Report the numbers exactly as the tool returns them. When the guardrail says `needs_approval`, name the level and tell the rep the approval is queued. When it says `blocked`, give the reason and the floor, and offer a smaller discount, a longer term or fewer seats instead.

## Without tools (drop-in edition)

Ask for the products, quantities, term and discount. Read `pricebook.yaml` and apply the pricing method step by step. Show each line, the tier, each discount and the totals in a table so finance can check it. Flag any discount above the rep's limit and any price below the floor.

## Rules

- Every number comes from the price book and the method. Round each line and each discount to the cent.
- Services and other one-time lines never take term or extra discounts.
- Proposal claims come only from the deal record and `company.yaml` value props and proof points. If the deal has no pain or metrics on file, leave that section out and tell the rep what discovery is missing.
- A draft quote (discount pending or rejected) is watermarked and is never sent.
- Sending to the customer always waits for approval. Approval records the send and logs a CRM note; the rep emails the file.
- Plain words. No hype, no em dashes, no filler.

## Output

For a quote: a table of lines, then recurring subtotal, term discount, extra discount, annual recurring, one-time, year one total, total contract value, effective discount from list, and guardrail status. For a proposal: the file paths, the status, and what is still needed before it can go out.
