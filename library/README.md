# GTM Skill Library

Shared skills, playbooks and scoring code that the GTM agents load. Nothing here is tied to one company: product facts, ICP, recipients and repos are all set per deployment through config.

| Folder | What is in it |
| --- | --- |
| `skills/` | Agent skills in SKILL.md format (sales, research, writing, CRM, documents). Most are third-party open-source packs; see each skill's own license. |
| `outbound-engine/` | Python tools: JEV/CLEF account scoring (`typesafe_client.py` + `product_profile.example.yaml`), forecast change alerts, rep feedback PRs |
| `references/` | Playbooks the agents follow: outbound copy rules, anti-slop voice system, signal sayability matrix, pre-call brief template, feedback loop, Smartlead API notes |

## Configure for a deployment

1. Copy `outbound-engine/product_profile.example.yaml`, fill it in for the product you sell, and set `GTM_PRODUCT_PROFILE` to its path.
2. Copy `outbound-engine/forecast_alerts.config.example.json` to `forecast_alerts.config.json` with your CRM owner IDs and Slack member IDs.
3. Put keys in the env file (`GTM_ENV_FILE`, default `~/.gtm/.env`): `TYPESAFE_API_KEY` or `CLOUDFLARE_ACCOUNT_ID` + `CLOUDFLARE_AUTH_TOKEN`, `HUBSPOT_TOKEN`, `SLACK_BOT_TOKEN`.
4. Fill in Section 0 of `references/anti-slop-voice-system.md` for the seller's brand voice.

The NetClaw fleet in `../netclaw/` decides which agent loads which skills.
