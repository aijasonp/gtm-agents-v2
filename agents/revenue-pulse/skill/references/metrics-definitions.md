# Metric definitions

All dates are UTC. "Period" is the last `period_days` (default 7) ending now. "Quarter" is the calendar quarter containing now. Amounts are the deal amount field; deals with no amount count as 0.

| Metric | Formula |
| --- | --- |
| Open pipeline | Sum of amount over open deals (status open and stage not closed). |
| Weighted pipeline | Sum over open deals of amount x stage probability (`stage-probabilities.yaml`). Unknown stage = 0.10. |
| Won QTD | Sum of amount over won deals with close date in the quarter. |
| Remaining quota | max(quarter quota from `company.yaml` minus won QTD, 0). |
| Quarter pipeline | Sum of amount over open deals with close date before the quarter ends (past-due open deals included). |
| Coverage | Quarter pipeline / remaining quota, two decimals. Shown as "quota met" when remaining is 0. |
| Created | Count and amount of deals with created date in the period. |
| Won / lost | Count and amount of won or lost deals with close date in the period. |
| Win rate | Won count / (won + lost count) in the period. Blank when both are 0. |
| Slipped | Open deals whose close date is later now than it was at the start of the period (last snapshot before the period, else the first snapshot in it). Days moved = new minus old close date. |
| Stage moves | Stage changes between consecutive snapshots taken in the period. Forward or backward by stage order. |
| Stale | Open deals with no activity for more than `stale_days` (default 14). Uses last activity, else stage entry, else created date. |
| Closing this month | Open deals with close date in the current month, summed by forecast category (blank = uncategorized). |
| Overdue tasks | Open tasks with a due date before now, by owner. |
| Top risks | Latest Deal Inspection result per open deal, highest risk first. If Deal Inspection has not run, a rule-based score: stale 30, slipped this period 30, close date passed 25, no next step 15. |
| Week over week | Difference from the last stored pulse for open pipeline, weighted pipeline, coverage, won QTD and stale count. |
| Rep action | One approval decision by a named person (`approvals.decided_by`), or one row in `rep_activity` (Slack question or command, push-button run, browser extension or other front end via `POST /v1/activity`). Decisions by `autonomy:*`, `operator` or unmatched actors never count. Actors match a rep by Slack id, email or name from `team.owners`. |
| Active rep | A rep with `min_actions` (default 3) or more actions in the last `window_days` (default 30). |
| Adoption | Active reps / reps in `team.owners`. |
| Retention | Reps active in both the previous and the current window / reps active in the previous window. Blank when nobody was active before. |
| Win-rate cohorts | Every won or lost deal with close date in the last `lookback_days` (default 90) and an owner on the team. It counts for `users` when its owner had `min_actions` or more actions in the `window_days` before the close date, else for `non_users`. Win rate = won / (won + lost) in each cohort. |
| Win-rate lift | Users win rate minus non-users win rate, in points, one decimal. Blank when either cohort has no closed deals. Flagged as a small sample when either cohort has fewer than `min_cohort` (default 5) deals. |
| Closers using the agents | Owners with a won deal in the lookback, and how many of them were active before at least one of those wins. |
