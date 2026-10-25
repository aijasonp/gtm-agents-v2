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
