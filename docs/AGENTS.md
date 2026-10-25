# Agent guide

How the seventeen agents work together, what each one reads and writes, and which licensed playbooks each bundles.

## The flow

```
                 CRM (read-only sync)        web forms / events / notetakers (HTTP API or inbox folders)
                        |                                   |
                        v                                   v
   +--------------------------- customer database (Postgres) ----------------------------+
   | accounts  contacts  deals(+history)  leads  meetings  tasks  signals  scores        |
   | drafts  insights  handoffs  approvals  audit_log  token_usage                       |
   +--------------------------------------------------------------------------------------+
        |              |                |                   |                  |
   Signal Scout   Lead Triage    Meeting Intelligence   Deal Inspection    Revenue Pulse
   (scores)       (route+draft)   |            |        (risk, gaps)       (weekly summary)
        |              |          | recap      | MEDDPICC     ^                  ^
        v              |          v            v evidence     |                  |
   ICP Outbound        |    Seller Follow-Up   +--------------+   deal_inspection insights
   (list+sequence)     |    (digest, recaps)
        \______________|___________/                Sales Execution (pre-call briefs)
                       v                            Product Marketing (battlecards, win/loss)
              approval queue  ---- human approves ---->  CRM writes / sequencer / notes / tasks
```

Agents share one database and pass work through `handoffs` (deduplicated, consumed once) and `insights` (append-only facts other agents read). Nothing leaves the customer's environment except approved writes to their own CRM and sequencer, and model calls on their own keys.

## Handoffs and shared facts

| From | To | Kind | What it carries |
| --- | --- | --- | --- |
| Meeting Intelligence | Seller Follow-Up | `meeting_recap` handoff | meeting, deal, account, summary, pain, next steps, attendees, owner |
| Meeting Intelligence | Deal Inspection | `meddpicc_evidence` handoff | deal, meeting, quotes per MEDDPICC element (raises missing elements to partial only, never confirms) |
| Meeting Intelligence | Product Marketing, Sales Execution | insights `competitor_mention`, `objection`, `pricing_mention`, `call_flag`, `next_step` | quote, account, deal, meeting |
| Deal Inspection | Revenue Pulse, Sales Execution | insight `deal_inspection` | risk, recommendation, gaps, flags, MEDDPICC %, days in stage |
| Signal Scout | ICP Outbound, Lead Triage, Sales Execution | `scores` table | tier, score, signal heat, reasons, safe opener lines |
| Lead Triage | ICP Outbound | `leads` table | inbound in progress blocks cold outbound to that account |
| Sales Execution | (reps) | insight `precall_brief` | brief per upcoming meeting |
| Reply Desk | Rep Brief | insights `reply` | class, account, evidence; replies needing action show in the brief |
| Reply Desk | Signal Scout | `outcomes` | reply_positive, meeting, reply_negative, bad_fit drive weekly reweighting |
| Reply Desk | Enrichment | `enrich_request` handoff | referred person with a name but no email |
| Social Signals | Signal Scout, Rep Brief | `signals` (category social) | comments, shares, follows, reactions, repeat views |
| Deal Inspection | Forecast Prep | insight `deal_inspection` | risk feeds the suggested commit |
| Stack Audit | (leadership) | draft `tool_cut_memo` | savings by renewal date with cut conditions |
| Product Marketing | (enablement) | insight `battlecard` + draft | card per competitor |

## Conflict rules

- **Open deal on the account.** Lead Triage routes the lead to the deal owner as a task and drafts nothing for the prospect. ICP Outbound skips the account and lists it as an active-pipeline conflict.
- **Inbound lead in progress.** ICP Outbound skips the account. If cold outbound was already queued when the lead arrived, Lead Triage flags it so the approver rejects it.
- **Recently contacted** (any agent's sent draft, or another agent's queued draft, within 45 days) or on `do-not-contact.yaml`: no outbound.
- **Person-specific signals** (a new exec, a champion joining) are only mentioned to the person the signal is about. Timing-only signals (pricing page visits, intent data) are never mentioned to a prospect.

## Opt-outs and bounces

- Reply Desk records every opt-out and bounce in one suppression list (`core/gtm_core/suppression.py`) and flags the contact. Pending sequence and dialer approvals for that person are rejected at once.
- Every agent that picks people (Rep Brief, ICP Outbound, Lead Triage, Social Signals, Enrichment) checks the list before drafting, and the sequence and dialer executors check it again at the moment they run, so a late opt-out still stops the send.
- Stopping a sequence only reduces contact, so `sequence_stop` runs immediately and is logged in the queue as approved by `auto:safety`. Sends are never auto-approved.

## Approval actions

| Action | Queued by | Executes |
| --- | --- | --- |
| `sequence_enroll` | Lead Triage, ICP Outbound | Pushes contact plus approved copy to the sequencer (webhook or Smartlead) |
| `crm_task` | Lead Triage, Seller Follow-Up | Task on the deal or account for the owner |
| `crm_contact` | Lead Triage | Creates the contact on the account |
| `crm_update` | Signal Scout | Score, tier and reasons on the account |
| `deal_note` | Meeting Intelligence, Seller Follow-Up | Call summary or recap note on the deal |
| `deal_update` | Deal Inspection, Seller Follow-Up | MEDDPICC fields, next step |
| `sequence_stop` | Reply Desk | Stops every sequence for a person; runs at once (`auto:safety`). Webhook sequencer; Smartlead flags a manual stop |
| `contact_update` | Reply Desk, Enrichment | Opt-out flag, enriched email or phone |
| `dialer_enqueue` | Rep Brief (push-button), Enrichment (opt-in) | Call task with a short script to the dialer webhook |

## Per agent

| Agent | Reads | Writes (local) | Queues for approval | Tools | Jobs | Bundled playbooks |
| --- | --- | --- | --- | --- | --- | --- |
| Lead Triage | leads, accounts, contacts, deals, scores | lead status, score, tier, owner, SLA; drafts | crm_contact, crm_task, sequence_enroll | triage_lead, list_leads, add_lead, route_lead, draft_follow_up | triage_inbox, sla_check | sales-lead-score, sales-lead-routing, email-sequence, icp-persona, predictable-revenue |
| ICP Outbound | scores, signals, accounts, contacts, deals, leads, drafts | drafts (3 steps, tagged with angle and value prop), contact outbound_queued_at, email events | sequence_enroll | build_target_list, why_now, pick_contacts, draft_sequence, check_conflicts, record_email_event, angle_performance | weekly_list_build, daily_drafts, weekly_angle_report | cold-email, email-sequence, sales-cadence, sales-deliverability, sales-prospect-list, icp-persona, predictable-revenue, influence-psychology |
| Seller Follow-Up | tasks, deals, leads, meetings, drafts, handoffs | drafts (recaps, follow-ups), snoozes | crm_task, deal_note, deal_update | whats_overdue, draft_follow_up, draft_recap, log_next_step, snooze | daily_digest, process_recaps | sales-cadence, email-sequence, humanizer |
| Deal Inspection | deals, deal history, contacts, accounts, insights, handoffs | deal MEDDPICC (proposed), deal_inspection insights | deal_update | inspect_deal, list_at_risk, meddpicc_gaps, update_meddpicc, recommend_action | sync_deals, weekly_inspection, apply_evidence | sales-deal-inspect, sales-forecast, revops |
| Meeting Intelligence | meetings (transcripts), deals, accounts | meeting summary, insights, handoffs | deal_note | analyze_call, meeting_summary, list_meetings, coaching_notes, search_mentions | ingest_inbox, pull_transcripts, process_meetings | sales-call-review, sales-coaching |
| Sales Execution | meetings, deals, contacts, scores, insights, tasks | precall_brief insights | none | precall_brief, meddpicc_questions, objection_help, proposal_outline, next_steps_summary | precall_briefs | sales-proposal-template, sales-enablement, hundred-million-offers, crossing-the-chasm |
| Product Marketing | insights, deals, accounts | battlecard insights and drafts | none | competitor_intel, battlecard, win_loss_report, objection_library, messaging_brief, launch_brief | weekly_field_report, battlecard_refresh | competitor-alternatives, competitor-profiling, product-marketing-context, launch-strategy, pricing-strategy, product-positioning, product-messaging, case-study-builder, sales-compete, obviously-awesome, storybrand-messaging, made-to-stick |
| Revenue Pulse | deals, deal history, insights, tasks | weekly snapshot (state) | none | pipeline_summary, forecast_rollup, slipped_deals, stale_deals, top_risks, owner_scorecard, daily_report | weekly_pulse, daily_gtm_report | sales-forecast, revops |
| Signal Scout | accounts, signals, outcomes, email events | scores, decisions (judged ICP), learned signal and question weights | crm_update | score_account, list_priority_accounts, explain_score, add_signal, record_outcome, push_to_crm, judge_account | sync_accounts, daily_sweep, weekly_reweight | sales-intent, sales-account-map, sales-enrich, clay-gtm-outbound |
| Copy QA Gate | text | none | none | check_copy, check_batch | none | avoid-ai-writing, humanizer, unslop, no-slop, copy-editing |
| Rep Brief | scores, signals, deals, tasks, leads, replies, insights | brief state | sequence_enroll, crm_task, dialer_enqueue | my_brief, push_button, top_accounts, pipeline_gaps, whats_new | daily_briefs | sales-account-map, sales-cadence, cold-email, predictable-revenue |
| Social Signals | engagement exports, contacts, accounts | signals, insights | crm_contact | add_engagement, engagement_for, top_engagers, creator_report, resolve_person | ingest_engagement, weekly_creator_report | sales-intent, sales-social-listening, social-content |
| Reply Desk | replies, contacts, drafts | replies table, contact flags, outcomes, insights | sequence_stop, contact_update, crm_contact, crm_task | classify_reply, add_reply, handle_reply, replies_needing_action, opt_out | process_replies, reply_digest | sales-reply, sales-inbox-zero, sales-deliverability, humanizer |
| Enrichment | contacts, scores, leads, handoffs | contact fields with provenance, cache | contact_update, crm_contact, dialer_enqueue (opt-in) | enrich_contact, enrich_account, waterfall_report, coverage_report, push_to_clay, import_clay | enrich_queue | sales-enrich, sales-data-hygiene, sales-zoominfo, sales-clay |
| Forecast Prep | deals, deal history, insights | weekly snapshot, forecast calls | none | ae_prep, manager_prep, exec_prep, forecast_changes, call_agenda, submit_forecast_call, forecast_call_history, board_forecast | forecast_prep, forecast_change_alerts, board_forecast_post | sales-forecast, sales-deal-inspect, revops |
| Stack Audit | tool inventory, scores, outcomes | memo draft | none | stack_summary, overlap_matrix, renewal_calendar, savings_scenarios, compare_lists, cut_memo | renewal_watch, monthly_utilization | revops, lean-analytics |
| Ops Monitor | runs, approvals, handoffs, token usage, manifests | alert state | none | health_report, job_status, stuck_items, spend_report | health_check, daily_ops_summary | none |

## Selling agents separately

Each agent compiles to its own package (`make compile`), so any one can be sold on its own. Dependencies when sold alone:

- Lead Triage, Signal Scout, Copy QA Gate, Meeting Intelligence, Deal Inspection, Revenue Pulse: standalone.
- ICP Outbound: best with Signal Scout (falls back to ICP fit only).
- Seller Follow-Up: recaps need Meeting Intelligence; the daily digest is standalone.
- Sales Execution: richer with Meeting Intelligence and Deal Inspection; works from CRM data alone.
- Product Marketing: needs field evidence from Meeting Intelligence or imported call notes.
- Rep Brief: needs Signal Scout; richer with Deal Inspection, Reply Desk and Social Signals.
- Reply Desk, Enrichment, Stack Audit, Ops Monitor: standalone. Forecast Prep is richer with Deal Inspection.
