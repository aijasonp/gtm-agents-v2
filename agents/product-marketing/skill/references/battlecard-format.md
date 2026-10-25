# Battlecard format

One card per competitor. Every line traces to evidence (a call quote, a closed deal) or to
`company.yaml`. Anything else goes under "To verify".

```
Battlecard: <competitor>   (built <date> from <N> mentions, <W> wins, <L> losses in <days> days)

Snapshot
  Their positioning (from company.yaml): <text or "to verify">
  Seen on: <accounts>  | Mentions: <this period> (prev <previous>, <trend>)
  Record vs them: <W>-<L> (win rate <pct>)

Where they win
  - <loss reason or objection seen on lost deals, with count>

Where we win
  - <reason seen on won deals, with count>

Landmines and questions to ask
  - <question tied to the top objection category on their deals>

Objection handling
  - <category> (<count>): <prepared response, first sentence>

Proof
  - <approved proof point from company.yaml>  (or "No approved proof: add one")

Evidence log
  - <date> <account>: "<quote>"

To verify
  - <claims nobody has evidence for yet>
```

Rules:
- Never state a competitor feature, price or weakness that is not in evidence or company.yaml.
- Quotes are verbatim and capped at five.
- Win rate needs at least one closed deal; otherwise write "no closed deals yet".
