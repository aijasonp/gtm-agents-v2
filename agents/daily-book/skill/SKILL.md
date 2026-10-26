---
name: daily-book
description: Build each account executive's daily book of 25 to 50 people to work today, warm from the CRM and engagement, cold from owned buying signals, with the reason and next action for each. Use when someone asks who to reach out to today, for my book, to fill an AE's day, why someone is on the list, or why a book came up short.
---

# Daily Book

You make sure every AE starts the day with a full, ranked list of people to work. The book is a quota, not a list: it fills to the AE's slot count or says plainly why it could not.

## How a book is built

1. **Slots.** The AE's `book.slots` in `config/company.yaml`, else the agent default (25 to 50), split by `warm_ratio`.
2. **Warm pool**, in order: engaged contacts (opens or clicks, no reply), quiet deals, past champions who moved, unworked inbound, event attendees with no meeting, social engagement, closed-lost recycle.
3. **Cold pool**: the AE's accounts from today's Signal Sourcing send list first, then by Signal Scout score, with buyers picked by Rep Brief's rules.
4. **Backfill.** A short pool is filled from the other. A real shortfall is reported, never padded.
5. **Cold first touches** are drafted through ICP Outbound and wait for the AE's approval.

Details and every exclusion: `references/book-rules.md`.

## With tools (persistent edition)

| Ask | Tool |
| --- | --- |
| "Who do I work today?" / "My book" | `my_book` |
| "Build the books now" | `build_books` |
| "Is everyone's book full?" | `book_status` |
| "Done with Ana" | `mark_done` |

## Without tools (drop-in edition)

Ask for the AE's accounts with scores and signals, open deals with last activity, recent engagement, inbound and event leads. Apply the pools and exclusions in `references/book-rules.md`, then list the book with the reason and action for each person, warm first.

## Rules

- Opens and clicks only decide timing. Never tell the AE to mention them; the action for engaged people is a call or LinkedIn, or an email with a new reason.
- Nobody already teed up or in a follow-up cadence goes in a book: Follow-Through owns them.
- Never pad a short book with people below the ICP floor or with no reason to reach out.
- At most `max_per_account` people from one account.
