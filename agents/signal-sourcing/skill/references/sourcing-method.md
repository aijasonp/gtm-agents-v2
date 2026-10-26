# Sourcing method

## Account gate (before any fetch)

The account is skipped when any of these is true. The reason is returned.

- No corporate domain: a free mail domain, a lead-gen or list site, a parked domain or a placeholder.
- A thin domain (`.dev`, `.ai` and similar) with no headcount and no stock listing.
- An excluded company type, by name or industry: investor, staffing, agency, consultancy, law firm, or any type listed under `exclusions.excluded_types` (put competitors and partners there).
- On the suppression list.
- Fewer employees than `exclusions.min_employees`, unless publicly traded.

## Filings

- **CIK match.** In order: `cik` on the account, then `ticker`, then an exact normalized company name. Legal suffixes such as Inc, Corp and Holdings are ignored. There is no fuzzy matching. If nothing matches, the note says to add the ticker.
- **Which filing.** The newest 10-K or 10-Q filed inside `max_age_days`.
- **Sections.** Risk Factors (Item 1A), MD&A (Item 7 in a 10-K, Item 2 in a 10-Q) and Business (Item 1). Every item also appears in the table of contents, so the longest span for each section wins.
- **Sentences.**
  - A sentence must hit at least one `required` topic.
  - Score = section boost (Risk Factors 5, MD&A 3, Business 2) + the topic weight for each term hit + 1 for each specificity term.
  - Forward-looking-statement boilerplate is skipped.
  - The top sentence becomes the signal. The next two are kept for the rep.
- **Confidence.** High when every topic in `high_needs` appears in the same sentence. Otherwise Medium.

## 8-K item 5.02

- A sentence must contain an appointment or departure verb plus a role from `exec_change.buyer_roles` or `csuite_roles`.
- Appointment in a buyer role: "new executive in the buying function". Appointment in another C-suite role: "new C-suite executive". Departure from a buyer role: "known buyer left".

## News

- **Source.** The account's `newsroom_rss` feed first. With no feed, a news API provider (Context.dev when `CONTEXT_DEV_API_KEY` is set). Provider items count only from the company's own domain or a `trusted_press` domain.
- **Initiative.** A commitment term and a topic term in the same item. A stated dollar figure of $100,000 or more makes it High.
- **Funding.** A raise, round or series announcement. Always High.
- **Appointment.** An appointment verb in the headline plus a buyer or C-suite role.

## Hiring

- **Boards.** Greenhouse, Lever and Ashby public APIs. The board token comes from `ats` on the account, or is guessed from the domain and name. The board that answers is saved to the account.
- **Window.** Titles matching `hiring.buyer_roles`, posted inside the window. Three or more roles make it High.

## Storage and dispatch

- Each signal is stored once per account, type, URL and day, with source `sourcing:<tier>`, strength 1.0 (High) or 0.7 (Medium), and its quote, topic and filing in the payload.
- **Dispatch.** Accounts with at least one sourced signal inside its tier window, that pass the account gate, the ICP floor and Signal Scout (not tier X), with every required field filled.
- **Ranking.** High first, then Signal Scout score, then the newest signal. Capped at `dispatch.max_accounts` and never padded.

## Fetching

- Public endpoints only, with a User-Agent that names the company and a contact email (`GTM_SOURCES_USER_AGENT`).
- Paced per host, with retries on 429 and 5xx.
- No disguising, no stealth browsers, no working around a block. A blocked source is logged as `sourcing.fetch_failed` and skipped.

## Page changes

- A watch's `gtm:<kind>` tag names the page (pricing, careers, trust, leadership, news, tech). Without a tag, the URL path decides, from `page_changes.page_kinds`.
- The account comes from an `account:<domain>` tag, then from the page's domain, subdomains included.
- Only added lines count, except script tags, where a removed tool is also a signal.
- Careers: a buyer role from `hiring.buyer_roles`. Leadership: a buyer or C-suite role. Trust: a certification term, High when the line says certified, achieved or completed. News: a commitment and a topic in one line, a launch, or a partnership. Tech: a domain from `complementary_tools` or `competitor_tools`. Pricing: any change.
- Timing-only types (pricing, competitor scripts, removed tools) are stored for Signal Scout but never qualify an account for the send list.
