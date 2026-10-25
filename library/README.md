# Skill library

716 skills from 11 public sources. Every source is MIT licensed. Each source folder holds the upstream LICENSE, a SOURCE.md with the upstream URL and any local changes, and the skills themselves under `skills/`.

`index.json` lists every skill with its name, description, source, license, path and category.

## By source

| Source | Upstream | Skills |
| --- | --- | --- |
| `sales-skills` | https://github.com/sales-skills/sales | 630 |
| `coreyhaines-marketingskills` | https://github.com/coreyhaines31/marketingskills | 35 |
| `marketingagentskills` | https://github.com/realjaymes/marketingagentskills | 32 |
| `wondelai-skills` | https://github.com/wondelai/skills | 10 |
| `blader-humanizer` | https://github.com/blader/humanizer | 1 |
| `aboudjem-humanizer` | https://github.com/Aboudjem/humanizer-skill | 1 |
| `avoid-ai-writing` | https://github.com/conorbronsdon/avoid-ai-writing | 1 |
| `no-slop` | https://github.com/Byk3y/no-slop | 1 |
| `unslop` | https://github.com/theclaymethod/unslop | 1 |
| `leadgrow-research-process-builder` | https://github.com/LeadGrowGTM/research-process-builder | 1 |
| `hyperfx-marketing-skills` | https://github.com/hyperfx-ai/marketing-skills | 3 |

## By category

| Category | Skills |
| --- | --- |
| Conversation intelligence, notetakers, inbox and contact center | 159 |
| Funnels, Email Marketing & Digital Sales | 124 |
| CRM & Marketing Automation | 78 |
| Media Intelligence & PR | 76 |
| Launch Directories | 45 |
| Influencer Marketing | 31 |
| Outreach & Sequence Platforms | 23 |
| Customer Experience & Feedback | 21 |
| cro-seo-web | 19 |
| marketing-strategy | 17 |
| Data, Intelligence & Enrichment | 17 |
| positioning-frameworks | 13 |
| Email Finder & Verification | 12 |
| research-intel | 9 |
| writing-quality | 8 |
| Cross-Platform & Strategy | 8 |
| outbound-email | 6 |
| automation | 6 |
| product-marketing | 5 |
| Prospecting, Enrichment & Signals | 5 |
| SEO & Visibility | 5 |
| Customer Reviews & UGC | 5 |
| Qwilr & Proposals | 5 |
| revops-enablement | 3 |
| Sales Enablement Platforms | 3 |
| Prospecting & Pipeline | 3 |
| Transactional Email | 3 |
| Router | 2 |
| Uncategorized | 2 |
| Loyalty | 1 |
| Active Deals | 1 |
| CRO & Experimentation | 1 |

## Using a library skill in an agent

An agent pulls library skills into its drop-in package by listing their paths in `agent.yaml`:

```yaml
library:
  - library/coreyhaines-marketingskills/skills/cold-email
  - library/wondelai-skills/skills/predictable-revenue
```

Paths are relative to the repo root. The build step copies each listed skill, plus its source LICENSE, into the agent's package so the notice travels with the files.

## Rules

- Add a skill only from a source with a verified permissive license (MIT, Apache-2.0, BSD, ISC or CC-BY). Copy its LICENSE into the source folder and record the upstream URL in SOURCE.md.
- Do not edit skills in place. If a local change is unavoidable, record it under Local changes in SOURCE.md.
- Keep `index.json` and `THIRD_PARTY_NOTICES.md` in step with the folders.
