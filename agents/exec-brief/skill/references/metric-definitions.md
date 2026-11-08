# Exec Brief metric definitions

All dates are UTC. QTD and MTD run from the first day of the quarter or month to the run time. Pace is the full target times the share of the period elapsed. Renewal opportunities (`type: renewal`) are excluded from every sales, marketing and partner metric and counted only in Customer Success.

## Sales

| Key | Definition | Better | Target |
| --- | --- | --- | --- |
| bookings_qtd | Sum of amount, won, close date this quarter | up | `bookings_plan_qtr`, paced |
| forecast_vs_plan | (bookings QTD + open commit closing this quarter) / plan | up | 100% |
| pipeline_coverage | Open amount closing by quarter end / (plan minus bookings QTD) | up | `coverage` |
| pipeline_created_qtd | Sum of amount, created this quarter | up | `pipeline_created_qtr`, paced |
| commit_qtr | Open commit amount closing by quarter end | up | change since last run |
| slipped_out_1d | Deals that closed this quarter at the last run and now close after quarter end or are lost | down | 0 |
| stalled_late_stage | Open commit and best case closing this quarter with no activity for more than `stale_days` | down | 0 |
| win_rate_qtd | Won amount / (won + lost amount), closed this quarter | up | `win_rate` |

## Marketing

| Key | Definition | Better | Target |
| --- | --- | --- | --- |
| mqls_mtd | Leads with an MQL date this month | up | `mqls_month`, paced |
| mql_to_sql_90d | Of MQLs in the last 90 days, the share with an SQL date | up | `mql_to_sql` |
| marketing_pipeline_qtd | Pipeline created this quarter with source marketing | up | `marketing_pipeline_qtr`, paced |
| marketing_share_qtd | Marketing-sourced / all pipeline created this quarter | up | `marketing_share` |
| speed_to_lead | Of MQLs from 7 days ago up to `sla_hours` ago, the share first touched within `sla_hours` | up | `speed_to_lead` |

## Partners

| Key | Definition | Better | Target |
| --- | --- | --- | --- |
| partner_pipeline_qtd | Pipeline created this quarter with source partner | up | `partner_pipeline_qtr`, paced |
| partner_bookings_qtd | Won this quarter with source partner | up | `partner_bookings_qtr`, paced |
| deal_regs_7d | Deal registrations submitted in the last 7 days (partner-sourced opportunities created, when no registration query is set) | up | the 7 days before |
| partner_share_open | Partner-sourced / all open pipeline | up | `partner_share` |
| active_partners_90d | Distinct partners with a partner-sourced opportunity created in the last 90 days | up | `active_partners` |

## Customer Success

| Key | Definition | Better | Target |
| --- | --- | --- | --- |
| grr_qtd | Sum of min(renewed ARR, ARR) / sum of ARR, renewals closed this quarter | up | `grr` |
| nrr_qtd | Sum of renewed ARR / sum of ARR, renewals closed this quarter | up | `nrr` |
| renewal_arr_at_risk | ARR of open renewals due in `renewal_window_days` with red health | down | 0 |
| renewals_due | ARR of open renewals due in `renewal_window_days` (volume; shown, never ranked) | none | none |

## Status and ranking

Score for a higher-is-better metric is value / goal minus 1; for lower-is-better, 1 minus value / goal (a goal of 0 scores 0 at 0 and -1 above it). Goal is pace when the target is paced, else the target. With no target, score is the change against the earlier value divided by that value. Score 0 or more is green, down to -0.10 is yellow, below is red. The company snapshot shows the highest and lowest score per team.

## Week over week

The command center recomputes event-dated metrics (bookings, created pipeline, MQLs, conversion, partners, retention) for the end of each past week from the same rows. Metrics that depend on live deal state (commit, coverage, forecast, slipped, stalled, renewal risk) use the stored daily snapshot for that week and stay blank until runs have stored one.
