# Engagement export formats

Drop CSV or JSON files into `data/engagement/inbox/`. The ingest job runs every 30 minutes and archives each file to `data/engagement/processed/`.

## Columns

| Column | Also accepted | Example |
| --- | --- | --- |
| platform | network, source | linkedin, youtube |
| post_url | url, video_url, post_link | https://example.com/posts/123 |
| post_title | title, video_title, post_text, topic | Ranking accounts every morning |
| author | creator, page, channel | company, or an influencer's name from `tracked_creators` |
| engager_name | name, full_name, commenter, profile_name | Dana Cole |
| engager_title | engager_headline, headline, job_title | VP of Sales Development |
| engager_company | company, company_name, organization | Northwind Logistics |
| engager_profile_url | profile_url, linkedin_url, channel_url | https://linkedin.com/in/example |
| engager_email | email | optional |
| engagement_type | type, action, reaction_type | like, comment, share, repost, follow, subscribe, view |
| comment_text | comment, text | How does pricing work for 20 reps? |
| engaged_at | timestamp, date, created_at | 2026-10-21T15:04:00Z |

## Where the data comes from

- **LinkedIn company page:** page analytics exports give follower and post totals, not names. Names of people who reacted or commented come from the post itself, so most teams use a scraper or engagement tool that exports one row per person per post. Map its columns to the table above.
- **An influencer's LinkedIn posts:** the same scraper approach, with `author` set to the influencer's name. Add that name to `tracked_creators` in `agent.yaml` with a weight (1.0 for your own page, 0.7 to 1.0 for close partners).
- **YouTube:** YouTube Studio and the YouTube Data API expose comments and commenter channels. Views are not tied to people, so `view` rows usually come from your own video platform or a gated landing page where the viewer is known.
- **Automations:** any tool that can write a CSV or JSON file (Zapier, Make, n8n, a scheduled script) can drop rows into the inbox.

## Privacy

Use only engagement that is public or that the person gave you (a gated video, a form). Do not import data that a platform's terms forbid you to collect.
