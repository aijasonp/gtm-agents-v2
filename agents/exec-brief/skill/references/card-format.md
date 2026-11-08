# Exec Brief card format

Cards are json-render specs: a flat map of elements with one root. The engine builds them in code; the
model writes only the one sentence at the top.

## Executive brief

```
Card  "<Title> daily brief" / "<Day> | 5 numbers that matter"
  Text (bold)   one sentence: what to act on today, then the strongest number
  Fields        five Field elements, label "<color dot> <metric>", value "<number>, <target or detail>, <change since last run>"
  Divider       only when a number is yellow or red and has deals behind it
  Table         up to 5 rows: Behind | Deal or account | Amount | Why
  Actions       optional LinkButton to the dashboard
```

## Company snapshot

```
Card  "Company daily snapshot" / "<Day> | best and worst number per team"
  Text (bold)   bookings QTD against plan
  Table         Team | Best | Worst
  Divider
  Text (muted)  "Last 6 weeks, oldest to newest"
  Text          one heat strip line per best and worst metric, a colored square per week
  Actions       LinkButton "Open command center"
```

## Limits

One table per card. The Node renderer passes `limits: {tables: 1}` to `toCard`, which rejects a spec that
breaks it instead of letting Slack degrade it. The Python renderer is the fallback when Node is not installed
and produces the same content as plain Block Kit sections.
