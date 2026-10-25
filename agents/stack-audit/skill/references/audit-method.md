# Audit method

All numbers come from the inventory. A missing cost is "unknown" and is left out of every total, with a note.

## Per tool

| Metric | Formula |
| --- | --- |
| Cost per seat | annual cost / seats purchased |
| Cost per active seat | annual cost / seats active in the last 30 days |
| Utilization | seats active 30 days / seats purchased |
| Login trend | logins last 30 days vs the 90-day monthly average (logins 90 days / 3) |
| Notice deadline | renewal date minus notice days: the last day to cancel or change seats |

## Overlap

A capability is overlapping when two or more tools list it. The overlap matrix shows every capability with its tools, utilization and cost.

## Recommendation per tool (first rule that fits)

1. **Cut** when every capability is either fully covered by an agent (`capability-map.yaml`, replace: full) or covered by another tool with higher utilization. Savings = annual cost.
2. **Consolidate** when the same holds but at least one capability is covered only by another tool: fold it into that tool. Savings = annual cost.
3. **Downsize** when seats purchased exceed active seats plus 10% (rounded up). Savings = cost per seat x excess seats.
4. **Keep** otherwise.

Every cut and consolidate carries the condition from `capability-map.yaml` that must be true first, and partial coverage is listed as a gap. Nothing is cut on utilization alone.

## Renewal watch

Alerts at 120, 90, 60 and 30 days before the notice deadline, once per band. A passed deadline is flagged: the contract renews unless notice was already given.

## Side by side

Compare the tool's top-account list with Signal Scout tier A and B accounts over the same period:
- overlap % = accounts on both lists / accounts on the tool's list
- tool-only accounts that converted (meeting, opportunity, closed won) are the cost of cutting
- agent-only accounts are what the agents add
The cut condition is met when the agents surface at least 70% of the tool's converted accounts.
