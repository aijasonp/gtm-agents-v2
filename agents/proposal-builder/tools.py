"""Proposal Builder MCP tools. The model asks; the engine does every number."""
from __future__ import annotations

from gtm_core.agents import load_module


def _eng(ctx):
    return load_module(ctx.manifest, "engine")


def list_products(ctx) -> dict:
    """Products in the price book with list price, unit, volume tiers, terms and discount limits by role."""
    pb = _eng(ctx).pricebook(ctx)
    return {"currency": pb.get("currency", "USD"), "products": pb.get("products", []), "terms": pb.get("terms", []),
            "discount_guardrails": pb.get("discount_guardrails", {}), "floor_pct_of_list": pb.get("floor_pct_of_list"),
            "payment_terms": pb.get("payment_terms")}


def build_quote(ctx, deal: str, lines: list[dict], term_years: int = 1, discount_pct: float = 0, role: str = "ae") -> dict:
    """Price a quote for a deal (id or CRM id) or an account. lines: [{sku, qty}]. Returns every line, the tier
    applied, term and extra discounts, annual recurring, year one total, total contract value and the guardrail
    status. A discount above the role limit is queued for approval; one below the floor is blocked."""
    return _eng(ctx).build_quote(ctx, deal, lines, term_years, discount_pct, role)


def check_discount(ctx, discount_pct: float, role: str = "ae", lines: list[dict] | None = None, term_years: int = 1) -> dict:
    """Is this discount allowed for this role? With lines, also checks the price floor. Saves nothing."""
    eng = _eng(ctx)
    pb = eng.pricebook(ctx)
    if lines:
        try:
            q = eng.compute(pb, lines, term_years, discount_pct, role)
        except ValueError as e:
            return {"error": str(e)}
        return {**q["guardrail"], "annual_recurring": q["annual_recurring"], "effective_discount_pct": q["effective_discount_pct"]}
    from decimal import Decimal
    return eng.guardrail(pb, discount_pct, role, Decimal(1), Decimal(0))


def render_proposal(ctx, quote_id: str) -> dict:
    """Write the branded proposal (HTML and markdown) for a quote from deal evidence, company.yaml claims and the
    quote. Draft quotes are watermarked. Returns file paths and the draft id."""
    return _eng(ctx).render_proposal(ctx, quote_id)


def send_proposal(ctx, quote_id: str, to_email: str, note: str = "") -> dict:
    """Queue the rendered proposal for sending to the customer. A human approves it first; only ready quotes qualify."""
    return _eng(ctx).queue_send(ctx, quote_id, to_email, note)


def get_quote(ctx, quote_id: str) -> dict:
    """A saved quote with its current status (ready, pending_approval, blocked, discount_rejected, sent)."""
    return _eng(ctx).get_quote(ctx, quote_id) or {"error": f"quote {quote_id} not found"}


TOOLS = {f.__name__: f for f in [list_products, build_quote, check_discount, render_proposal, send_proposal, get_quote]}
