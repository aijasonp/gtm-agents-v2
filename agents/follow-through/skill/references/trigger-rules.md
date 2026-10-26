# Trigger rules

## Facts (computed in code)

| Fact | Meaning |
| --- | --- |
| `human_opens` | Opens in the window. Opens flagged as machine opens, or within `machine_open_seconds` of the send, are left out |
| `clicks` | Link clicks in the window |
| `replied` | Any reply in the window, from sequencer events or Reply Desk |
| `steps_sent` | Steps sent in the window |
| `days_since_send` | Days since the last step went out |
| `motion` | Which agent sent the last step: outbound, event, inbound, pipeline, push_button, other |
| `tier` | Latest Signal Scout tier of the account |
| `has_open_deal` | The account has an open deal |
| `suppressed` | Opted out, bounced or do-not-contact |
| `teed_up` | Already handed to an AE inside `cooldown_days` |
| `key_page_visits` | Days this person hit pricing, demo, contact-sales or security pages in the window (PostHog; 0 when not connected) |

## Cell syntax

The same as the GoRules decision table editor, so tables can move between the two:

| Cell | Means |
| --- | --- |
| `">= 3"`, `"< 5"`, `"!= lost"` | Comparison |
| `"[1..3]"`, `"(1..3]"` | Range, square bracket inclusive |
| `"A, B"` | Any of |
| `true`, `false`, `3`, `"A"` | Equals |
| `"-"`, empty, or the field left out | Any value |

Numbers compare only with numbers, and text only with text. A missing fact is `null`, so it only matches an empty cell or `null`.

## Engines

With `zen-engine` installed, cells run through the GoRules engine and a table may point at a decision file exported from the GoRules editor (`{jdm: rules/name.json}`). Without it, the built-in evaluator gives the same answers for every cell form above.

## Outputs

| Key | Effect |
| --- | --- |
| `action` | `tee_up`, `notify_owner` or `none` |
| `pause` | For a tee-up, stop the sequence for this person now (default true) |
| `priority` | `high` or `normal`, shown in the brief |
| `sla_hours` | Business hours until the AE should act |
| `reason` | Shown to the AE and kept in the audit log |
