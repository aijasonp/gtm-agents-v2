# Inspection method

Each open deal is checked in this order. Every check is a rule from `stage-rules.yaml`.

1. **Stage and age.** Map the CRM stage to a standard stage. Days in stage over `max_days_in_stage` is a stall.
2. **Activity.** Days since the last logged activity over `max_days_without_activity` is a stall. No activity date at all counts from the day the deal entered its stage.
3. **Close date.** A close date in the past on an open deal is a hygiene problem. Each time the close date moved later is a slip.
4. **Next step.** Missing, or dated in the past.
5. **MEDDPICC.** Each element scores 0 (missing), 1 (partial or claimed) or 2 (confirmed with evidence). The stage sets the minimum for each element. A gap is either **missing data** (nobody asked) or **unconfirmed** (claimed, not proven).
6. **Negative evidence.** A quote or field that says the buyer chose someone else, has no budget, or put it on hold. This is different from missing data and weighs more.
7. **Stakeholders.** Fewer than two buyer-side people known (CRM contacts plus call attendees) is single-threaded. From the evaluation stage on, nobody at director level or above is a gap.
8. **Fit.** The account's ICP fit from `icp.yaml`. Below the floor is wrong fit.

## Risk score

Sum the `risk_points` for every driver present, capped at 100. List the drivers in the output, largest first.

## Recommendation

- **Disqualify** when any `disqualify_when` rule matches. This is a recommendation for the owner and manager. The agent never closes a deal.
- **Fix** when risk is at or above `fix_when_risk_at_least`, or the stage has any MEDDPICC gap.
- **Progress** otherwise.

Every fix or disqualify comes with one to three specific actions, tied to the drivers found.

## Evidence from calls

Meeting Intelligence sends quotes for MEDDPICC elements. A missing element with a quote moves to partial (1). Evidence never confirms an element on its own: confirmation needs a person or an explicit CRM value. The CRM field update is queued for approval.
