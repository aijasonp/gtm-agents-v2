# Output formats

## One deal

```
Contoso Health - Agents | Proposal | $140,000 | owner Sam Rivera
Risk 78: close date passed (Oct 31 -> moved 1x), no activity 28 days, next step overdue, MEDDPICC 3/16
Gaps: economic buyer (missing), paper process (missing), metrics (missing), champion (unconfirmed)
Negative: "price is too expensive compared to Acme Intel"
Recommendation: FIX
1. Get the economic buyer on a call: ask Jo Patel who signs off at this amount.
2. Confirm procurement and security review steps and dates.
3. Reset the close date with the buyer, not in the CRM alone.
```

## Weekly report (Slack)

One header line with counts per recommendation, then per owner, worst risk first:

```
Deal Inspection: 5 open deals | progress 1, fix 3, disqualify 1
*Sam Rivera*
- Contoso Health - Agents | Proposal | risk 78 | FIX | economic buyer missing; no activity 28d
- Northwind Logistics - Platform | Evaluation | risk 24 | PROGRESS
```

No commentary between lines. Say "missing data" and "negative evidence" plainly; never blur the two.
