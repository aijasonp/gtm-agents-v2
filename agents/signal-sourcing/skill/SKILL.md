---
name: signal-sourcing
description: Find dated, sourced buying signals for target accounts from SEC filings (10-K, 10-Q, 8-K), company newsrooms, trusted press and public job boards, and build a send-ready batch where every account has a real signal. Use when someone asks what is new at an account, why to reach out now, to scan accounts for signals, to build today's outbound batch, or to find new companies that match.
---

# Signal Sourcing

You find the reason to reach out now, from sources the buyer published themselves. No signal, no send.

## Tiers, in priority order

1. **Filings.** The latest 10-K or 10-Q. A sentence in Risk Factors, MD&A or Business that names a priority or risk from `config/signals.yaml`. Keep the exact sentence, the filing date and the link.
2. **News.** An initiative, funding round or appointment from the company's own newsroom, or from a trusted press domain. It must be a concrete, dated commitment. "Exploring" does not count.
3. **Hiring.** Buyer-team roles posted on the company's public job board in the last 30 days. For companies with no Greenhouse, Lever or Ashby board (most large enterprises), job search sites fill in when `hiring.job_search` is on. A posting counts only when its company matches exactly.
4. **Executive change.** Officer appointments or departures from an 8-K item 5.02, or a newsroom announcement.
5. **Page changes.** changedetection.io watches on careers, leadership, trust, newsroom, pricing and script tags. Only lines the change added count. Careers roles, leadership appointments, certifications, initiatives and launches are mentionable. Pricing changes and competitor scripts are timing only and never qualify an account on their own.

Method details: `references/sourcing-method.md`.

## With tools (persistent edition)

| Ask | Tool |
| --- | --- |
| "What is new at X?" / "Scan X" | `scan_account` |
| "Scan everything that is due" | `scan_due` |
| "Build today's batch" | `dispatch_batch` |
| "Find new companies like this" | `discover_companies`, then `add_company` with the domain |
| "Add this company" | `add_company` (cik or ticker makes the SEC match exact) |
| "How is sourcing doing?" | `sourcing_report` |
| "This page changed" | `page_change` |
| "What pages should we watch?" | `watch_plan` |

When a tier finds nothing, say why, using the tool's own note. Examples: "no CIK match, add the ticker", or "no public job board found".

## Without tools (drop-in edition)

Ask for the account list and any filings, press releases or job posts the user can paste. Apply the tiers by hand. For each signal, show the exact sentence or headline, the date and the link. Drop any account with no dated, sourced signal, and say so.

## Rules

- Never discover companies from search snippets. Use EDGAR full-text search, the CRM, or a list the user gives.
- Every signal needs a date and a source link, or it does not exist.
- Industry must be the real industry, never a placeholder such as "Technology".
- Never source or send to investors, agencies, staffing or lead-gen firms, parked or free-mail domains, competitors, partners, or suppressed domains.
- What may be said in copy is decided by the taxonomy's `say_it` lines, not here. Filings, initiatives, funding and appointments can be named. Hiring is said at the team level only, never as a count, a title or a link. Competitor use, breaches and engagement data are timing only.
- A clean batch of 8 beats a padded batch of 25.
