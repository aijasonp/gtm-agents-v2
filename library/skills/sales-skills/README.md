# Sales Skills

**AI-powered sales copilot — hundreds of skills for prospecting, outbound, deals, proposals, and GTM. One install, one router.**

[![Skills](https://img.shields.io/badge/skills-hundreds-blue)](https://skills.sh/sales-skills/sales)
[![Platforms](https://img.shields.io/badge/platforms-dozens-green)](https://skills.sh/sales-skills/sales)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)
[![Install](https://img.shields.io/badge/install-npx%20skills%20add%20sales--skills%2Fsales%20--skill%20sales--do%20-a%20claude--code-black)](https://skills.sh/sales-skills/sales)

<p align="center">
  <img src="assets/demo.gif" alt="Sales Skills demo — install, route, and run" width="600">
</p>

## Contents

- [Quick Start](#quick-start)
- [Why?](#why)
- [What is sales-do?](#what-is-sales-do)
- [Skills Catalog](#skills-catalog)
- [Usage Examples](#usage-examples)

## Quick Start and Best Practice for 99% of users

```bash
npx skills add sales-skills/sales --skill sales-do -a claude-code
```
Restart the session after install to pick up the new skill.

Not sure which skill you need? Just run `/sales-do` and describe what you're trying to accomplish — it routes you to the right sales, GTM, or marketing skill.

## Installing several skills at once

If you want specific platform skills directly (rather than just the router), pass them all to **one** `--skill` flag — a single command downloads them together:

```bash
npx skills add sales-skills/sales --skill sales-fathom sales-fireflies sales-otter -a claude-code
```

Avoid running `npx skills add` once per skill — each separate run re-downloads the whole repository, so batching into a single command is much faster.

## Use without coding

Download skills as files and use them in any AI chat app — no terminal or `npx` required.

### Claude Desktop / claude.ai

1. Go to [Releases](../../releases/latest) and download the `.zip` for the skill you want (start with `sales-do.zip`)
2. **Settings > Features > Skills > + > Upload** and drag the `.zip` file in

### ChatGPT

1. Go to [Releases](../../releases/latest) and download the `.zip`, then unzip it
2. Create a **Project** (or Custom GPT), click **Add files**, and upload `SKILL.md` plus everything in `references/`

### Google Gemini

1. Go to [Releases](../../releases/latest) and download the `.zip`, then unzip it
2. Create a new **Gem**, upload `SKILL.md` and the `references/` files, and save

### Perplexity

1. Go to [Releases](../../releases/latest) and download the `.zip`, then unzip it
2. Create a **Space**, go to **Files > +**, and upload `SKILL.md` plus the `references/` files

## Why sales-do skill?

- You're copy-pasting the same cold email structure for every campaign
- You can't remember which tool does email validation vs enrichment vs deliverability
- You need to launch on Product Hunt, DevHunt, and 20 other directories but don't know what each one requires
- You want to build a prospect list but don't know whether to use Apollo, Clay, ZoomInfo, or Seamless
- You're spending more time figuring out _which_ tool to use than actually doing the work

One router skill (`/sales-do`) understands all available sales, marketing, ad network, influencer, CRM, and GTM skills and matches you to the right one based on what you're trying to accomplish.

## What is `sales-do`?

`/sales-do` is a router skill — the single entry point for hundreds of skills in this repo. Describe your objective in plain language and it matches you to the right specialized skill with a ready-to-use prompt. You don't need to memorize which skill does what.

```
/sales-do write a cold outbound sequence for CFOs at mid-market fintech companies
```

### How the workflow works

1. **You invoke the router** with a plain-language request (or no arguments at all).

2. **The router asks clarifying questions** — it needs to understand what you're trying to do, who the audience is, where you are in the process, and any constraints. Questions use multiple-choice options to make answering fast.

3. **The router checks strategy skills first** — before looking at individual platforms, it checks whether your problem maps to a **strategy skill**. Strategy skills are cross-platform coordinators that cover an entire problem domain (e.g., `/sales-deliverability` covers email deliverability across Apollo, Mailshake, Salesloft, Smartlead, etc.). If a strategy skill matches, you get routed there — and the strategy skill handles platform-specific routing internally. There are 40+ strategy skills covering problem domains from CRM selection to influencer marketing to help desk comparison.

4. **The router matches and recommends** — it picks the best skill and generates a detailed, ready-to-use `/sales-*` prompt packed with all the context you provided. You can copy-paste-run it directly and get a great result without re-explaining anything. For multi-step objectives, it recommends a sequence of skills.

### What it does NOT do

- It does **not** solve the problem itself — it never writes copy, audits SEO, or designs pricing. It only routes.
- It does **not** auto-invoke the target skill — you run the generated prompts yourself, so you stay in control.

### Example: strategy skill routing

```
> /sales-do we need a help desk — we're a 15-person SaaS team using HubSpot,
  budget is under $50/agent

Router responds:
  This is a help desk selection question — run:

  /sales-helpdesk-selection We're a 15-person SaaS team using HubSpot CRM.
  We need email + chat support with a knowledge base. Budget is under
  $50/agent/month. Compare our options.
```

The strategy skill (`/sales-helpdesk-selection`) then compares Zendesk, Freshdesk, Intercom, Help Scout, Gorgias, and others — factoring in your budget, CRM, and team size.

### Example: multi-skill sequence

```
> /sales-do I want to launch cold outbound — need a prospect list,
  verify emails, warm up a domain, then run a sequence

Router recommends a 4-skill sequence:
  1. /sales-prospect-list <prompt with ICP, filters, volume>
  2. /sales-enrich <prompt to verify/enrich the list>
  3. /sales-deliverability <prompt for domain warmup and DNS setup>
  4. /sales-cadence <prompt to design the outbound sequence>
```

## Skills Catalog

### Prospecting & Pipeline

| Skill | What it does |
|---|---|
| `/sales-prospect` | ICP definition, target lists, lead identification |
| `/sales-prospect-list` | Account/contact research, competitive intel, org charts |
| `/sales-cadence` | Cold emails, LinkedIn messages, multi-touch sequences |
| `/sales-forecast` | Pipeline review, forecasting, deal prioritization |

### Active Deals

| Skill | What it does |
|---|---|
| `/sales-demo` | Demo prep, pitch decks, presentation customization |
| `/sales-proposal-page` | Proposals, pricing, SOWs, business cases, ROI |
| `/sales-cadence` | Nurture, re-engagement, going-dark recovery |

### Router

| Skill | What it does |
|---|---|
| `/sales-do` | Routes your objective to the right skill |
| `/sales-request-skill` | Build or request a skill that doesn't exist yet |


<details>
<summary><strong>Qwilr & Proposals</strong></summary>

| Skill | What it does |
|---|---|
| `/sales-proposal-page` | Write and structure a Qwilr proposal page with interactive quote blocks |
| `/sales-proposal-analytics` | Interpret Qwilr engagement signals and decide follow-up actions |
| `/sales-deal-room` | Design multi-stakeholder Qwilr deal rooms for complex B2B deals |
| `/sales-qwilr-automation` | Build automations connecting Qwilr to CRM via API, Zapier, or native integrations |
| `/sales-proposal-template` | Design reusable Qwilr proposal templates for your whole sales team |
| `/sales-getaccept` | GetAccept — AI-powered digital sales room with proposals, e-signatures, contract management, CPQ, mutual action plans, buyer engagement tracking, REST API (Enterprise) |

</details>

<details>
<summary><strong>Salesloft</strong></summary>

| Skill | What it does |
|---|---|
| `/sales-salesloft` | Salesloft platform help — config, Rhythm, Conversations, Drift, integrations |
| `/sales-cadence` | Design multi-channel outbound cadences with timing, A/B testing, and content |
| `/sales-field-sales` | Hyperlocal field sales — door-to-door / territory / route-based outbound to cash-heavy local SMBs (restaurants, gas stations, salons, contractors, HVAC). Corridor target lists from Google Maps / Yelp / Outscraper (NOT Apollo), route planning, 60-second clerk pitch, SMS/handwritten/phone follow-up, platform picks across SalesRabbit / Spotio / Map My Customers / Badger Maps / Outfield / Repsly / Skynamo / Geopointe |
| `/sales-two-sided-marketplace` | Two-sided marketplace GTM — cold-start chicken-and-egg, supply-vs-demand sequencing (anchor-demand-first playbook for local services), supply recruiting for 1099 gig workers, the "every demand call is a recruiting call" clerk-flip, single-corridor pilot framework, integrated one-page GTM plan template for on-demand and recurring service marketplaces (cleaning, courier, lawn, home services, pet care) |
| `/sales-marketplace-payouts` | Marketplace payouts (supply-side disbursement) — Stripe Connect (Standard/Express/Custom), PayPal Hyperwallet, Adyen for Platforms, Trolley, Tipalti, Routable, dots.dev, Branch (on-demand pay), Nium, Wise Business, Tremendous selection by stage + vertical, KYC and onboarding burden, multi-currency, 1099-K/1099-NEC tax forms, the 1099 worker-classification risk that payout design carries |
| `/sales-call-review` | Review sales calls, extract coaching insights, score against MEDDPICC/SPIN |
| `/sales-note-taker` | AI meeting note-taker / conversation-intelligence selection & API integration (Fathom, Fireflies, Avoma, Gong, Otter, Fellow, Grain, Sembly, Read.ai, MeetGeek, Jamie, Jamy, Wave, tl;dv, Claap, Sybill, Sonnet, Shadow) |
| `/sales-fathom` | Fathom platform help — REST API, webhooks, OAuth, SDKs, MCP, transcript/summary export, CRM sync, pricing tiers |
| `/sales-fireflies` | Fireflies.ai platform help — GraphQL API, Webhooks V1 + V2, HMAC verification, AskFred AI, Real-time API, MCP, rate limits per tier, bot auto-join control |
| `/sales-avoma` | Avoma platform help — REST API, webhooks, MEDDIC/BANT/SPICED scorecards, Conversation + Revenue Intelligence, Lead Router, CRM sync, pricing tiers |
| `/sales-gong` | Gong platform help — Revenue AI OS, call recording, Smart Trackers, coaching scorecards, REST API, webhook automation, Forecast, Engage, MCP |
| `/sales-otter` | Otter.ai platform help — OtterPilot, live transcription, AI Chat, Zapier automation, CRM sync, pricing tiers |
| `/sales-fellow` | Fellow platform help — AI meeting assistant, REST API, bot-based/bot-free recording, CRM sync, templates, pricing tiers |
| `/sales-grain` | Grain platform help — AI meeting recorder, REST API, MCP Server for Claude/Cursor, video clips, Zapier automation, CRM sync, pricing tiers |
| `/sales-sembly` | Sembly platform help — agentic meeting intelligence, AI-generated deliverables, webhook automations, 10 native CRM connectors, Zapier/n8n, MCP, pricing tiers |
| `/sales-read-ai` | Read.ai platform help — meeting intelligence with engagement/sentiment analytics, Search Copilot, REST API + MCP Server, webhook automations, CRM sync, pricing tiers |
| `/sales-meetgeek` | MeetGeek platform help — bot + no-bot recording, customizable AI summary templates, REST API with regional endpoints, MCP Server, 7 CRM connectors, conversation analytics, pricing tiers |
| `/sales-jamie` | Jamie platform help — bot-free AI note-taker, REST API with personal/workspace keys, webhook automations, CRM sync to HubSpot/Salesforce/Attio, MCP server, EU privacy-first, pricing tiers |
| `/sales-krisp` | Krisp platform help — noise cancellation + AI meeting notes, accent conversion, Voice AI SDK, webhook integrations, Call Center AI, CRM sync, pricing tiers |
| `/sales-colibri` | Colibri.ai platform help — real-time transcription, AI summaries, Sales Copilot with live guidance, conversation analytics, legal transcription, pricing tiers |
| `/sales-cluely` | Cluely platform help — real-time AI coaching overlay, pre-call briefs, knowledge base RAG, CRM sync via Merge.dev, coaching analytics, pricing tiers |
| `/sales-jamy` | Jamy.ai platform help — AI meeting assistant with real-time translation (100+ languages), cross-language search, HubSpot CRM sync, API/webhooks, pricing tiers |
| `/sales-tldv` | tl;dv platform help — AI meeting note-taker with unlimited free recordings, REST API v1alpha1, sales coaching (MEDDIC/BANT/SPIN), CRM sync, MCP server, pricing tiers |
| `/sales-wave` | Wave platform help — mobile-first AI note-taker, REST API with semantic search and webhooks, MCP server, Voice ID, 76-language transcription, pricing tiers |
| `/sales-claap` | Claap platform help — AI sales call assistant with no-bot recording, REST API + OAuth, CRM auto-enrichment, deal scoring (SPICED/MEDDIC/BANT), MCP connector, pricing tiers |
| `/sales-tactiq` | Tactiq platform help — Chrome extension bot-free AI note-taker, live transcription (60+ languages), AI Workflows, Zapier automation, native HubSpot/Salesforce/Pipedrive CRM sync, pricing tiers |
| `/sales-hedy` | Hedy AI platform help — real-time AI meeting coach, REST API, webhooks, MCP server, Zapier/n8n automation, pricing tiers |
| `/sales-granola` | Granola platform help — bot-free AI notepad for meetings, REST API, MCP integration (beta), HubSpot/Attio/Affinity CRM sync, Zapier automation, pricing tiers |
| `/sales-omi` | Omi AI platform help — open-source AI wearable necklace ($89), Developer API, app marketplace with webhook integrations, in-person + online capture, pricing tiers |
| `/sales-bluedot` | Bluedot platform help — bot-free AI note-taker with video recording, Chrome extension + desktop/mobile apps, Svix webhooks, HubSpot/Salesforce CRM sync, screen recording, pricing tiers |
| `/sales-notta` | Notta platform help — AI meeting transcription in 58 languages, Notta Bot, Notta Brain cross-meeting AI, Zapier automation, CRM sync to Salesforce/HubSpot/Zoho/Freshsales/Salesflare, pricing tiers |
| `/sales-sonix` | Sonix platform help — AI transcription, translation, and subtitling for uploaded audio/video (53+ languages), REST API, SRT/VTT subtitles, video burn-in, Zapier, SOC 2/HIPAA, pricing tiers |
| `/sales-happyscribe` | HappyScribe platform help — batch AI + human transcription in 120+ languages, subtitle generation, translation, REST API, 15+ export formats (SRT/VTT/Premiere XML/FCP XML), SOC 2/GDPR, pricing tiers |
| `/sales-circleback` | Circleback platform help — AI meeting notes with cross-meeting search, webhook automations (HMAC-SHA256), MCP server for Claude/Cursor/Raycast, bot + botless recording, Slack huddles, HubSpot/Salesforce/Attio CRM sync, pricing tiers |
| `/sales-monday-notetaker` | monday.com AI Notetaker platform help — native meeting recording and transcription inside monday.com boards, action items → board items, GraphQL API (2026-04+), Zoom/Meet/Teams, Pro/Enterprise add-on |
| `/sales-transcribeme` | TranscribeMe platform help — human+AI hybrid transcription (99% accuracy on human tiers), HIPAA compliance, REST API, Machine Express/First Draft/Standard/Verbatim tiers, translation, .NET/Node.js SDKs |
| `/sales-temi` | Temi platform help — budget AI transcription at $0.25/min (Rev's engine), English-only batch upload, REST API, Zapier/Make automation, mobile app |
| `/sales-transkriptor` | Transkriptor platform help — AI transcription in 100+ languages, meeting bot (Zoom/Meet/Teams), subtitles, sentiment analysis, REST API (Enterprise only), Zapier/Make, pricing tiers |
| `/sales-verbit` | Verbit platform help — enterprise AI+human transcription, live captioning, accessibility compliance (ADA/WCAG/CVAA), Gen.V AI insights, REST API (5 modules), education/legal/media/government verticals, pricing tiers |
| `/sales-lindy` | Lindy platform help — no-code AI agent builder for email triage, meeting notes, calendar management, custom workflow automation, chatbots, AI phone agents, 4,000+ integrations, credit-based pricing tiers |
| `/sales-alfred` | alfred_ platform help — AI executive assistant for autonomous email triage, reply drafting, task extraction, calendar management, $24.99/month single tier |
| `/sales-fastmail` | Fastmail platform help — independent privacy-respecting email with full JMAP API, custom domains, Masked Email aliases, calendar/contacts/files, OAuth 2.0, community MCP server, Individual ~$5/mo or Business ~$5/user/mo |
| `/sales-fyxer` | Fyxer AI platform help — AI email assistant for inbox organization, voice-trained reply drafting, meeting notes, $22.50-50/user/mo |
| `/sales-hey` | Hey platform help — opinionated privacy-first email service by 37signals, Screener sender approval, Imbox/Feed/Paper Trail, spy pixel blocking, no AI by design, $99/yr personal or $12/user/mo domains |
| `/sales-proton-mail` | Proton Mail platform help — privacy-first encrypted email, end-to-end encryption, zero-access architecture, Bridge for IMAP/SMTP, Hide-my-Email aliases, bundled Calendar/Drive/VPN/Pass, Free 1GB or Mail Plus ~$4/mo or Unlimited ~$10/mo |
| `/sales-airmail` | Airmail platform help — Apple-exclusive email client, customizable actions, AppleScript automation, Smart Inbox, Privacy Mode, Free/$49yr |
| `/sales-superhuman` | Superhuman platform help — fastest AI email client, keyboard workflow, Split Inbox, AI Write, MCP server for Claude Code, $25-40/user/mo |
| `/sales-shortwave` | Shortwave platform help — AI-native Gmail client with natural language search, plain-English AI filters, Ghostwriter voice-learning drafts, MCP consumer, Tasklet automation, $24-100/mo |
| `/sales-mailman` | Mailman platform help — Gmail plugin for email batching, Do Not Disturb, unknown sender blocking, VIP whitelist, $8-10/mo |
| `/sales-newmail` | NewMail AI platform help — AI email assistant with voice-trained drafting, priority sorting, task extraction, daily briefings, scheduling links, Free preview or Solo $15/mo or Pro $30/mo |
| `/sales-spark-mail` | Spark Mail platform help — cross-platform AI email client by Readdle, Smart Inbox categorization, Gatekeeper sender screening, AI writing/summarization, team collaboration, Free or Premium $5/mo or Teams $6.99/user/mo |
| `/sales-bluemail` | BlueMail platform help — free cross-platform email and calendar app with unified inbox, GemAI AI writing, email clustering, Later Board, Free or Plus ~$5/mo or Team ~$12/mo or Enterprise custom |
| `/sales-mimestream` | Mimestream platform help — native macOS email client for Gmail, Gmail API-powered, tracking prevention, email templates, Markdown compose, multi-account, $50/yr |
| `/sales-em-client` | eM Client platform help — cross-platform desktop email client with calendar, tasks, contacts, PGP/S/MIME encryption, AI writing, mass mail, Free or Personal ~€30/yr or Business ~€40/device/yr |
| `/sales-hi-ai` | hi ai platform help — AI customer service email reply generator, multi-model (ChatGPT/Claude/Gemini/DeepSeek), brand voice training, Google Sheets data lookup, Free 3/day or Pro $25/mo |
| `/sales-unboxd` | Unboxd platform help — AI email secretary that extracts action items with deadlines into daily briefings, Gmail/Outlook/IMAP, $7.50-41.67/mo |
| `/sales-sanebox` | SaneBox platform help — server-side AI email filtering with smart folders, works with any email provider, $7-36/mo |
| `/sales-inbox-zero` | Inbox Zero platform help — open-source AI email assistant, auto-labeling, REST API + CLI, self-hostable, $18-42/mo or free |
| `/sales-clean-email` | Clean Email platform help — cross-platform inbox cleanup with bulk actions, Auto Clean rules, True Unsubscriber, Smart Folders, any email provider, $29.99/yr |
| `/sales-unrollme` | Unroll.me platform help — free newsletter unsubscribe and daily digest, data-funded by NielsenIQ, Gmail/Outlook/Yahoo/AOL/iCloud, not available in EU |
| `/sales-rilla` | Rilla platform help — AI coaching for in-person/field sales, virtual ridealongs, mobile recording, CRM sync via Merge, ServiceTitan/SPOTIO integrations, pricing tiers |
| `/sales-siro` | Siro platform help — AI field sales coaching, Halftime real-time mid-call coaching, mobile recording with offline mode, REST API + Svix webhooks, CRM sync via Merge, ServiceTitan/SalesRabbit/SPOTIO/FieldRoutes integrations, pricing tiers |
| `/sales-salesask` | Sales Ask (Coach Dean) platform help — AI coaching for in-home/field + call center sales in home services, active text feedback to reps, Process Adherence Scoring, virtual ridealongs, AI roleplay, ServiceTitan/Jobber/Housecall Pro/Salesforce integrations, white-label program |
| `/sales-sonnet` | Sonnet AI platform help — bot-free meeting recording with auto-CRM update (HubSpot/Salesforce), domain templates (sales/legal/medical/recruiting), concept maps, relationship tracker, macOS-only |
| `/sales-supernormal` | Supernormal platform help — AI agent for agencies, bot-free meeting capture, AI-generated deliverables (pitch decks, briefs, emails) from meetings, HubSpot/Salesforce CRM sync, credit-based pricing |
| `/sales-voicetonotes` | VoiceToNotes platform help — ultra-cheap AI voice-to-text ($1/mo unlimited), HIPAA/SOC 2 compliance, real-time transcription, AI summaries, grammar correction, OCR, web + iOS + Android, no integrations |
| `/sales-speakwise` | Speakwise platform help — iOS-native AI meeting assistant for in-person recording, on-device transcription (50+ languages), native Notion integration, AirPods hands-free, $59.99/yr |
| `/sales-noota` | Noota platform help — AI meeting assistant + recruitment automation with transcription, voice agents, email automation, 7 CRMs, 15 ATS integrations, EU compliant |
| `/sales-modjo` | Modjo platform help — EU-native AI revenue intelligence with call scoring, CRM auto-fill, deal intelligence, Ask Modjo AI, customizable AI agents, MCP server, GDPR-compliant EU hosting |
| `/sales-meetily` | Meetily platform help — open-source (MIT), privacy-first AI meeting assistant with 100% local Whisper/Parakeet transcription, Ollama summarization, bot-free recording, self-hosted deployment, HIPAA/GDPR by architecture |
| `/sales-char` | Char (formerly Hyprnote) platform help — open-source (GPL-3.0) bot-free local-first AI meeting notepad with system audio capture, markdown output, 10 cloud STT providers + local Cactus engine, plugin SDK, automation hooks, macOS |
| `/sales-amical` | Amical platform help — open-source (MIT) local-first AI dictation with Whisper STT, context-aware formatting, Ollama/OpenRouter LLM, push-to-talk voice-to-text, 100+ languages, Mac + Windows |
| `/sales-handy` | Handy platform help — open-source cross-platform speech-to-text with Whisper + Parakeet dual-engine, push-to-talk, GPU acceleration, Voice Activity Detection, CLI automation, 20k+ GitHub stars, Mac + Windows + Linux |
| `/sales-plaud` | Plaud platform help — hardware AI voice recorder (NotePin/Note/Note Pro), Vibration Conduction Sensor phone call recording, 112-language transcription, Developer API (private beta), SOC 2/HIPAA/GDPR |
| `/sales-reason8` | reason8 platform help — in-person meeting note-taker with multi-smartphone audio capture, AI transcription with speaker ID, patent-pending multi-device fusion, $19.99/mo Pro |
| `/sales-notewave` | NoteWave platform help — iOS AI note-taker with flashcard/quiz generation, 100+ language transcription, YouTube/PDF import, privacy-first (audio deleted immediately), Apple ecosystem only, no API/CRM, $12.99/mo |
| `/sales-mbox-meet` | MBox AI Meet platform help — free Chrome extension for Google Meet real-time transcription and AI summaries via Gemini Pro, speaker ID, E2E encryption (Pro $4.99/mo), no API/CRM/webhooks |
| `/sales-bliro` | Bliro platform help — bot-free AI sales assistant with CRM field-level sync (Salesforce/HubSpot/SAP/Dynamics 365), anonymous coaching, REST API + webhooks (Unlimited+), GDPR/ISO 27001/SOC 2, German-hosted |
| `/sales-noty` | Noty.ai platform help — Chrome extension AI meeting assistant for Google Meet and Zoom, Gemini-powered transcription, AI summaries, action items with deadlines, Gmail follow-ups, Zapier triggers, $10/user/mo |
| `/sales-sybill` | Sybill platform help — AI sales assistant with Magic Summaries, CRM Autofill (MEDDPICC/BANT/SPICED), Deal Workspace, Ask Sybill, follow-up automation, Buyer EQ behavioral insights |
| `/sales-attention` | Attention platform help — AI-native conversation intelligence with CRM auto-update, coaching scorecards (MEDDIC/BANT/custom), real-time battlecards, follow-up automation, Ask Attention AI, Workflow Builder, 200+ integrations, MCP server |
| `/sales-rafiki` | Rafiki platform help — AI conversation intelligence with Smart Call Scoring (MEDDIC/BANT/SPIN/GAP), CRM auto-sync, deal intelligence, Gen AI Reports, AI Role Play, 55+ languages, $19-49/user/mo Gong alternative |
| `/sales-maxiq` | MaxIQ platform help — AI-native revenue intelligence with EchoIQ CI (9 AI agents), InspectIQ pipeline visibility, ForecastIQ forecasting, usage-based pricing (not per-seat), Salesforce/HubSpot CRM sync, Startup Program (free 1 year) |
| `/sales-winn` | Winn.ai platform help — real-time AI sales assistant with playbook adherence tracking (MEDDIC/BANT/SPICED), automated CRM updates (Salesforce/HubSpot), live coaching (Enterprise), AI battle cards, meeting prep briefs, $69/seat/mo Pro |
| `/sales-outdoo` | Outdoo (formerly MeetRecord) platform help — AI roleplay coaching, conversation intelligence, revenue intelligence, CRM automation with MEDDIC/SPIN/BANT, 120+ integrations, Open API (Enterprise), mid-market Gong alternative |
| `/sales-jiminny` | Jiminny platform help — conversation intelligence, revenue intelligence, AI notetaker, sales coaching, automatic CRM logging, 8 native CRM integrations, partial REST API, mid-market Gong alternative |
| `/sales-enthu` | Enthu.AI platform help — contact center conversation intelligence with auto QA scorecards on 100% of calls, agent coaching, compliance monitoring, sentiment analysis, Aircall/RingCentral/HubSpot/Pipedrive integrations, affordable Gong/CallMiner alternative |
| `/sales-demodesk` | Demodesk platform help — AI-powered sales meeting platform with conversation intelligence, coaching scorecards, CRM auto-update, autonomous AI Crew agents, REST API V2, 98-language transcription, GDPR-native EU data centers |
| `/sales-clari-copilot` | Clari Copilot (formerly Wingman) platform help — real-time battlecards, live coaching, AI call summaries, coaching scorecards, gametapes, deal intelligence, Clari Core API, ~$60-110/user/mo |
| `/sales-cirrus-insight` | Cirrus Insight platform help — Salesforce-native sales productivity with email/calendar sync, Meeting AI, Conversation Intelligence, Live Coaching, Smart Scheduler, Buyer Signals, modular per-feature pricing ($5-$20/user/mo per module) |
| `/sales-iris-clarity` | IRIS Clarity platform help — bidirectional AI noise cancellation for calls, Web SDK + Server SDK for embedding voice isolation in VoIP apps, Talkdesk AppConnect, enterprise contact center audio quality, £6.50/seat/mo |
| `/sales-sozai` | Soz AI platform help — mobile-first AI transcription and note-taking, 100+ languages, YouTube URL paste, speaker diarization, subtitle generation (SRT/VTT), $9.99/mo unlimited, GDPR/HIPAA |
| `/sales-memoro` | Memoro platform help — German GDPR-first AI meeting assistant with bot-free local recording, customizable Blueprints, searchable Memories, 50+ language transcription, offline mode, €0-42/mo |
| `/sales-minuteslink` | MinutesLink platform help — budget AI meeting note-taker with bot + Chrome extension recording, shareable summary links (no recipient sign-up), Google Meet/Zoom, 50+ languages, $0-24/mo |
| `/sales-voicenotes` | Voicenotes platform help — AI voice notes and meeting transcription with Ask AI search, Zapier automation (9 triggers), Obsidian/Notion/Readwise sync, Claude MCP, Apple Watch/WearOS, 100+ languages, $0-14.99/mo |
| `/sales-audiopen` | AudioPen platform help — voice-to-polished-text with custom writing styles, SuperSummaries, 58/64 input/output languages, Zapier automation, one-time payment $0-159 |
| `/sales-talknotes` | TalkNotes platform help — AI voice note app with 100+ pre-made templates (blog, email, to-do, meeting notes), Zapier automation, AI Chat, 50+ languages, ~$10-49/mo |
| `/sales-letterly` | Letterly platform help — AI speech-to-content with 25+ rewrite formats (social posts, emails, journals, to-do lists), 90+ languages, offline recording, Zapier/webhooks, LTD $69+ |
| `/sales-cleftnotes` | Cleft Notes platform help — Apple-native AI voice-to-notes with on-device transcription, ADHD-friendly auto-organization, Obsidian/Notion sync, Apple Watch/CarPlay, $0-29/yr |
| `/sales-coconote` | Coconote platform help — Quizlet's AI lecture note-taker with auto-generated study guides, flashcards, quizzes, AI podcasts, AI chat, 100+ languages, iOS/Android/web/Mac, $0-19.99/mo |
| `/sales-hynote` | HyNote AI platform help — full-stack AI note-taker for audio, meetings, PDFs, YouTube, web pages with flashcards, quizzes, mind maps, presentations, podcasts, HIPAA/GDPR, $0-24.99/mo |
| `/sales-superpowered` | Superpowered platform help — bot-free AI meeting note-taker with device-audio capture, AI Templates, auto-join from calendar, SOC-2/GDPR, 50+ languages, $0-50/mo |
| `/sales-noted` | Noted platform help — Apple-ecosystem voice recorder + rich-text note-taker with timestamped audio linking, AI Transcribe, Intelligent Playback, Apple Pencil/Time Stroke, Apple Watch, $0-9.99/mo or $89.99 lifetime |
| `/sales-scribbl` | Scribbl platform help — bot-free AI meeting notes Chrome extension for Google Meet with AI Copilot chat, instant summaries/action items, 40+ languages, meeting library, $0-20/user/mo |
| `/sales-audionotes` | Audionotes platform help — multi-format AI note-taker (voice/text/image/video/YouTube), 100+ output templates, WhatsApp Bot, webhook + Zapier + Notion sync, 80+ languages, $0-10.83/mo |
| `/sales-bubbles` | Bubbles platform help — async video messaging + AI meeting note-taker, screen recording, auto-join Zoom/Meet/Teams, AI summaries + action items, Zapier automation, SOC 2 Type II, $0-18/mo |
| `/sales-jotme` | JotMe platform help — real-time AI translation + meeting intelligence, simultaneous interpretation in 107 languages, bot-free system audio capture, multilingual transcription, $0-30/mo |
| `/sales-kudo` | KUDO platform help — enterprise real-time AI speech translation + human interpreter marketplace (12,000+ interpreters, 200+ languages), embeddable widget, Teams/Zoom native, SOC 2/ISO 27001, custom pricing |
| `/sales-interprefy` | Interprefy platform help — enterprise RSI + AI speech translation + live captions, 80+ platform integrations (Inject/Widget/Agent/Virtual Cable), 6,000+ interpreters, REST API, ISO 27001, custom pricing |
| `/sales-langfinity` | Langfinity platform help — real-time voice-to-voice AI meeting translation in 50+ languages, domain-specific terminology accuracy, AI voice avatars, Teams/Zoom/Meet, pay-as-you-go and subscription pricing |
| `/sales-transync-ai` | Transync AI platform help — real-time AI meeting translation with near-zero latency (<0.5s), dual-screen bilingual display, AI voice broadcast, 60+ languages, bot-free system audio capture, $0-24.99/seat/mo |
| `/sales-talo` | Talo platform help — real-time AI meeting translation via single bot for Zoom/Meet/Teams, 60+ languages, SOC 2/ISO 27001, Palabra API (REST + WebSocket/WebRTC) with Python/JS/Java SDKs, $33-100/mo |
| `/sales-rimo` | Rimo Voice platform help — Japanese-optimized AI meeting transcription with ISO 27001/27017 compliance, Japan-hosted data, bot recording, custom dictionary, no API/CRM, $9-15/mo launch |
| `/sales-wudpecker` | Wudpecker platform help — AI meeting notes with custom instructions for personalized note structure, Ask Wudpecker AI Q&A, 39+ language transcription, Zoom/Meet/Teams bot + in-person recording, HubSpot/Notion/Slack (Plus+), EU/GDPR, $0-32/mo |
| `/sales-sally` | Sally AI platform help — German-hosted GDPR-first AI meeting transcription with tiered AI accuracy (90-98%), 99+ languages, MCP server for Claude/ChatGPT/Cursor, action items, meeting analytics, 7 CRM native integrations, $10-79/mo |
| `/sales-proshort` | Proshort platform help — enablement-first conversation intelligence with AI Roleplay, contextual in-call coaching cues, Deal Agents, CRM auto-sync (Salesforce/HubSpot/Zoho), SOC 2/ISO 27001/GDPR/HIPAA, $75/user/mo |
| `/sales-liznr` | Liznr platform help — AI meeting assistant with real-time contextual intelligence, Chrome/Edge/Teams, Jira/Slack/Notion task sync, multilingual transcription, privacy-first, $9/mo starting, no API/CRM |
| `/sales-aviso` | Aviso AI platform help — end-to-end AI revenue operating system with 98%+ forecast accuracy, conversation intelligence with 6-emotion analysis, MIKI AI Chief of Staff, relationship intelligence, 9 CRM integrations, enterprise-only ~$1,000/user/yr |
| `/sales-salesroom` | Salesroom platform help — AI video conferencing for sales with real-time coaching, battle cards, buyer engagement scoring, highlight clips, HubSpot/Salesforce CRM sync, own meeting platform (replaces Zoom), $0-49/mo |
| `/sales-laxis` | Laxis platform help — AI meeting intelligence with bot-free recording, universal voice keyboard with verbal cleanup, 50+ report templates, LaxisChat AI, CRM automation to HubSpot/Salesforce (Business+), OSO AI Earbuds and Panocore360 hardware, Enterprise-only API/SSO, $0-29.99/mo |
| `/sales-karax` | KaraX.ai platform help — agentic AI workspace combining multi-LLM chat, real-time meeting transcription, and AI workflow automation across 800+ integrations from OneChat interface, SOC 2/HIPAA/GDPR, no public API, $0-39.99/mo |
| `/sales-dicte` | Dicte platform help — EU privacy-first AI meeting assistant with post-quantum encryption, open-source/EU AI models only, AI SKILLs (SWOT, project reports, mind maps), DicteBOX on-premises, 5-language transcription, €0-19.99/mo |
| `/sales-meeting-ai` | Meeting.ai platform help — visual-first AI note-taker with mind map output, 30+ language transcription with Southeast Asian accent optimization, speaker identification, Ask AI Q&A, no API/CRM/webhooks |
| `/sales-backtrack` | Backtrack platform help — Mac menu bar retroactive recorder with rolling buffer (1-5 hrs), captures meetings you forgot to record, bot-free, AI transcription via cloud, $0-9.99/mo |
| `/sales-shadow` | Shadow platform help — bot-free AI meeting assistant with audio + screen capture, macOS-only, on-device transcription, Autopilot detection, AI summaries/action items/follow-up emails, $8/mo |
| `/sales-revenue-io` | Revenue.io platform help — Salesforce-native revenue orchestration with RingDNA dialer, Guided Selling cadences, Moments real-time coaching, conversation intelligence, Revenue Intelligence dashboards, custom pricing ~$59K/yr |
| `/sales-salesken` | Salesken platform help — real-time in-call coaching, QA automation on 100% of calls, revenue intelligence, field sales analytics, multilingual, Salesforce/HubSpot/Zoho native CRM, ~$99/mo |
| `/sales-balto` | Balto platform help — real-time AI guidance for contact centers, automated QA on 100% of calls, compliance monitoring (PCI/HIPAA), coaching, call summarization, 50+ CCaaS/softphone integrations, ~$100-150/agent/mo |
| `/sales-genesys` | Genesys Cloud CX platform help — enterprise CCaaS with AI experience orchestration, omnichannel routing, Architect IVR, WFM, QM, predictive routing, AppFoundry marketplace (450+ apps), REST Platform API with 15 regional endpoints, deep Salesforce integration (CX Cloud), $75-$240/user/mo |
| `/sales-talkdesk` | Talkdesk platform help — cloud CCaaS with AI virtual agents (Autopilot), agent assist (CoPilot), omnichannel routing, WFM, QM, Studio IVR, 23 REST API specs, deep Salesforce integration (CTI + Service Cloud Voice), $85-$225/agent/mo |
| `/sales-nice-cxone` | NICE CXone (Mpower) platform help — full CCaaS with omnichannel routing, WFM, quality management, AI analytics, Interaction Analytics, AI Copilot, virtual agents, 16 REST API groups, deep Salesforce integration, $71-$209/agent/mo |
| `/sales-zendesk` | Zendesk platform help — ticketing, Help Center, AI agents, live chat, Talk voice, Sell CRM, omnichannel messaging, Explore analytics, 1300+ Marketplace apps, REST API (15+ API families), $19-$169/agent/mo + add-ons |
| `/sales-hiver` | Hiver platform help — Gmail-native help desk with shared inboxes, AI copilot, SLA tracking, workflow automations, live chat, WhatsApp, voice, REST API (Pro plan), 10 Zapier triggers, Free-$49/user/mo |
| `/sales-gmelius` | Gmelius — Gmail-native AI email collaboration with Meli AI assistant, shared inboxes, Kanban boards, automation rules, sequences, REST API (Growth+), webhooks (Pro), $19-$40/user/mo |
| `/sales-front` | Front — AI-powered customer operations platform with shared inbox, omnichannel (email + SMS + chat + social + WhatsApp), Autopilot AI resolution, Copilot agent assist, Smart QA/CSAT, 160+ integrations, full REST API + webhooks, $25-$105/seat/mo |
| `/sales-missive` | Missive — collaborative team inbox (email + SMS + WhatsApp + Instagram + live chat) with internal threads, collaborative drafting, task management, REST API (Productive+), webhooks, Zapier/Make, $14-$36/user/mo |
| `/sales-helpdesk-selection` | Help desk platform comparison and selection — Zendesk vs Freshdesk vs Intercom vs Help Scout vs Zoho Desk vs Front vs Hiver vs Missive vs Jira Service Management vs Gorgias vs Tidio |
| `/sales-ccaas-selection` | CCaaS platform comparison and selection — Genesys vs NICE CXone vs Talkdesk vs Five9 vs 8x8 vs Nextiva vs Amazon Connect vs Twilio Flex vs Aircall vs Dialpad |
| `/sales-verint` | Verint Open Platform help — enterprise CX automation with Da Vinci AI bots (Quality Bot 100% QA, Coaching Bot real-time guidance, Wrap Up Bot, Exact Transcription 80+ languages), WFM, knowledge automation, IVA, speech/text analytics, 500+ adaptors, BYOT any-ACD, acquired Calabrio Feb 2026, custom enterprise pricing |
| `/sales-calabrio` | Calabrio ONE platform help — standalone WEM (WFM forecasting/scheduling, QM scorecards, interaction analytics, bot analytics, call recording) layered on top of any CCaaS (Amazon Connect, Genesys, NICE, Five9, Cisco, Avaya), WFM/Historical Data/HR APIs, ~$50-120/agent/mo (now part of Verint) |
| `/sales-playvox` | Playvox (by NICE) platform help — modular WEM with QA scorecards, WFM forecasting/scheduling, Performance Management, Coaching & eLearning, Agent Motivation gamification (leaderboards/badges/rewards), Zendesk/Salesforce/Five9/Genesys integrations, OAuth2 REST API, $30-90/agent/mo modular |
| `/sales-callminer` | CallMiner Eureka platform help — enterprise omnichannel conversation analytics with 100% automated QA, agent coaching, compliance monitoring (PCI/HIPAA/TCPA), real-time alerts, OVTS swappable ASR engines, 35+ integrations (Salesforce/Genesys/Five9/Twilio/Amazon Connect), Data + Ingestion APIs, enterprise-only pricing (~$102K/yr avg) |
| `/sales-execvision` | ExecVision (Mediafly Coach360) platform help — coaching-first conversation intelligence with call recording from 59+ sources, AI-powered coaching plans, smart alerts, performance dashboards, conversation library, QA scoring. Acquired by Mediafly 2022, now Coach360 in Revenue360 suite. Salesforce/HubSpot/Pipedrive/Dynamics/SAP CRM, 38 dialers, 9 conferencing. API enterprise-gated, ~$100-185/user/mo historical |
| `/sales-convin` | Convin platform help — AI-powered contact center QA with 100% automated scoring, Real-Time Assist agent coaching, AI Phone Call outbound voicebot, integrated LMS, proprietary LLM (70+ languages), 30+ integrations (8x8/Amazon Connect/Avaya/Aircall), custom pricing |
| `/sales-level-ai` | Level AI platform help — contact center intelligence with Naviant semantic AI, InstaScore 100% auto QA, AgentGPT real-time assist, iCSAT VoC analytics, AI Virtual Agent, Zendesk/Five9/Talkdesk/Genesys/Amazon Connect integrations, GraphQL API (enterprise-gated), ~$185/agent/mo |
| `/sales-observe-ai` | Observe.AI platform help — enterprise contact center intelligence with 100% Auto QA, Agent Copilot real-time guidance, Coaching Copilot, VoiceAI/ChatAI virtual agents, Five9/Amazon Connect/Talkdesk/Avaya integrations, REST API, ~$100-500/user/mo |
| `/sales-qeval` | QEval platform help — AI-powered contact center QA with 100% automated scoring (94% accuracy), speech analytics, compliance monitoring, agent coaching, VOC analytics, CRM/telephony/WFM integrations via API/SFTP, Manual $40/user/mo, AI $100/user/mo |
| `/sales-uniphore` | Uniphore platform help — enterprise Business AI Cloud with conversation intelligence (U-Analyze), real-time agent assist (U-Assist), automated QA, CSATai predictive CSAT, Emotion AI, self-service IVA, ActionIQ CDP, Cisco/Avaya/Genesys/Amazon Connect/Five9/Twilio integrations, Zero Data AI sovereign deployment, custom enterprise pricing |
| `/sales-cresta` | Cresta platform help — enterprise contact center AI with real-time agent assist, AI virtual agents, conversation intelligence, automated QA, Knowledge Agent, Agent Operations Center, Five9/Amazon Connect/Genesys/NICE integrations, $60K-$150K/yr |
| `/sales-maestroqa` | MaestroQA platform help — conversation data QA with customizable scorecards, AI-powered coaching workflows, AskAI conversation analytics, reverse-ETL, chatbot QA, 60+ integrations (Zendesk/Freshdesk/Salesforce/Five9/Talkdesk/Snowflake), Rippit API, ~$19/user/mo starting |
| `/sales-craft` | Craft platform help — AI growth engine for home services with real-time in-appointment field coaching, 24/7 AI call center, revenue recovery agents, ServiceTitan/Salesforce/HubSpot/Jobber/AccuLynx/Housecall Pro integrations |
| `/sales-momentum` | Momentum platform help — AI revenue orchestration with automated CRM updates, Slack Deal Rooms, MEDDIC Autopilot, AI coaching, churn signals, executive briefs, $69-99/user/mo, acquired by Salesforce Feb 2026 |
| `/sales-oliv` | Oliv.ai platform help — AI-native revenue intelligence with modular agents (Notetaker, Meeting Insights, Deal Insights, CRM Manager, Forecaster), 8 CRM integrations, 42+ total integrations, $19-77/user/mo modular pricing |
| `/sales-people-ai` | People.ai (now Backstory) platform help — automatic activity capture, deal intelligence, pipeline health, revenue forecasting, MCP integration, multi-CRM (Salesforce/Dynamics/Oracle), enterprise pricing |
| `/sales-scratchpad` | Scratchpad platform help — Salesforce-native AI workspace with call recording, AI field updates, pipeline sheets, Hygiene Monitor, Deal Agent, Gong integration, $0-49/user/mo |
| `/sales-laserfocus` | Laserfocus platform help — Salesforce overlay with Stacks, table views, bulk editing, precache technology, Field Groups, task management, $0-30/user/mo (YC W20, Inactive) |
| `/sales-veloxy` | Veloxy platform help — Salesforce-native field sales enablement with predictive intelligence, geolocation route planning, email tracking, mobile CRM, $25-35/user/mo |
| `/sales-weflow` | Weflow platform help — Salesforce-native Revenue AI with activity capture, conversation intelligence (96+ languages), deal intelligence & forecasting, Ask Weflow AI, Chrome Extension, Mobile Copilot, $19-79/user/mo |
| `/sales-dialpad` | Dialpad platform help — AI-native UCaaS + CCaaS with DialpadGPT, AI Recaps, AI Coaching Hub, contact center, voice, video, SMS, 70+ integrations, $15-25/user/mo |
| `/sales-deal-inspect` | Inspect deal health, map stakeholders, identify risks, recommend next actions |
| `/sales-forecast` | Build and validate revenue forecasts with pipeline coverage and gap analysis |

</details>

<details>
<summary><strong>Outreach & Sequence Platforms</strong></summary>

| Skill | What it does |
|---|---|




| `/sales-apollo` | Apollo.io — config, CRM sync, API, analytics, dialer, credits, admin |
| `/sales-apollo-sequences` | Apollo sequences — deliverability, A/B testing, mailbox config |
| `/sales-mailshake` | Mailshake — campaigns, Lead Catcher, recipients, senders, API, webhooks |
| `/sales-lemlist` | Lemlist — multichannel sequences, Lemwarm, People Database, enrichment, LinkedIn automation, WhatsApp, API |
| `/sales-lagrowthmachine` | La Growth Machine — LinkedIn-first multichannel outbound automation (LinkedIn + email + X sequences, per-identity safety limits, waterfall enrichment, lookalike + LinkedIn intent signals, shared inbox, AI copy/voice). REST API (`apiv2.lagrowthmachine.com/flow`, `apikey` query param) — enroll leads into audiences (`POST /flow/leads`), list campaigns/audiences/identities, inbox webhooks (reply events) + MCP; native HubSpot/Clay/Make/Slack + Zapier/n8n; per-identity pricing (Basic €50 → Ultimate €150 with API/webhooks) |
| `/sales-waalaxy` | Waalaxy — LinkedIn + email outreach automation (Chrome extension) for solopreneurs/small teams: prospect lists from LinkedIn Search/Sales Navigator, 99+ ready-made campaign sequences, Email Finder, enrichment, LinkedIn Inbox. REST API (`developers.waalaxy.com`, `Bearer` key from CRM Sync settings) — read prospect lists + campaigns, import/enroll prospects (`POST /prospects/addProspectFromIntegration`, needs LinkedIn URL + `origin`); native HubSpot/Pipedrive + Make/Zapier/n8n; API on Advanced/Business, cold email on Business; Free €0 / Pro €19 / Advanced €49 / Business €69 |
| `/sales-linkedhelper` | Linked Helper — cheap power-user LinkedIn automation as a standalone **desktop** app (its own browser, not a Chrome extension, not cloud): auto connect/message/InMail drip funnels, profile scraping, email finder, built-in mini-CRM. **No inbound API** — automation is outbound webhooks (Send person/replied/organization to webhook → flat ~100-column profile JSON) + native CRM sync (HubSpot/Salesforce/Pipedrive/Zoho/Close/Capsule/HighLevel/Streak/ActiveCampaign/Instantly) + Zapier/Make/Pabbly; webhooks unsigned/no-retry, dedupe on `member_id`. Desktop-only so campaigns stop when the computer's off (run on a VPS); account-restriction risk is the top gotcha. Standard $15/mo (20 actions + 20 webhook profiles/day) / Pro $45/mo (unlimited); one license = one LinkedIn account |
| `/sales-instantly` | Instantly — high-volume cold email (campaigns/subsequences across unlimited inboxes, free warmup + SISR IP rotation, inbox-placement tests, Unibox); REST API v2 (`api.instantly.ai/api/v2`, Bearer, cursor pagination, v2≠v1) + webhooks; Lead Finder (Credits) + CRM are separate paid products |
| `/sales-smartlead` | Smartlead — campaigns, SmartSenders, SmartInfra, SmartAgents, SmartDialer, API, agency/white-label |
| `/sales-yesware` | Yesware — email tracking, campaigns, templates, Prospector, Meeting Scheduler, Salesforce integration |
| `/sales-mixmax` | Mixmax — sequences, email tracking, one-click meetings, rules engine, dialer, AI Compose |
| `/sales-reply` | Reply.io — multichannel sequences, Jason AI SDR, B2B database, email warmup, unified inbox |
| `/sales-woodpecker` | Woodpecker — cold email campaigns, condition-based sequences, email warmup, Bounce Shield, LinkedIn automation |
| `/sales-snov` | Snov.io — AI-powered sales automation, email finder, multichannel campaigns, LinkedIn automation, Sales CRM |
| `/sales-aisdr` | AiSDR — AI-powered SDR, autonomous cold email + LinkedIn outreach, 700M+ contacts, email warmup, HubSpot integration |
| `/sales-11x` | 11x.ai — AI digital workers Alice (outbound SDR) and Mike/Julian (phone agent), 400M+ contacts, multi-channel, ~$5K/mo |
| `/sales-qualified` | Qualified — Piper AI SDR Agent, agentic marketing, real-time website chat, Signals buyer intent, Salesforce-native routing |
| `/sales-nooks` | Nooks — AI-native parallel dialer workspace, multi-channel sequencing, AI coaching (scorecards, roleplay, battlecards, virtual salesfloor), waterfall enrichment (9 providers), ~$5K/user/yr |
| `/sales-outreach-io` | Outreach — sales engagement sequences, Kaia conversation intelligence, deal management, forecasting, coaching, REST API, Salesforce/HubSpot sync, ~$100-160/user/mo |
| `/sales-amplemarket` | Amplemarket — AI-native all-in-one (Duo AI copilot, 300M+ contacts, multichannel sequences, intent signals, deliverability suite), REST API, Salesforce/HubSpot sync, Starter $600/mo |
| `/sales-orum` | Orum — AI parallel dialer (up to 10 lines), AI Coaching Suite (scorecards, roleplay, coaching portals), virtual salesfloor, spam detection/number rotation, Salesforce/HubSpot/Outreach/Salesloft/Gong/Apollo integrations, Launch $250/user/mo / Ascend $400-500+/user/mo |
| `/sales-trellus` | Trellus — AI parallel dialer (up to 5 lines) with real-time coaching, Chrome extension embedded in Salesloft/Outreach/HubSpot/Apollo/Salesforce, voice agents for practice roleplay, virtual salesfloor, Superhuman for LinkedIn, number health/spam remediation, Free/$34.99/mo/custom, SOC 2 Type II, YC W22 |
| `/sales-sendr` | Sendr — AI-powered personalized outreach with lipsync video, dynamic landing pages, Lead Finder (479M+ contacts), Data Studio enrichment, campaign sequencing, API/webhooks, $97-249/mo |

</details>

<details>
<summary><strong>Email Finder & Verification</strong></summary>

| Skill | What it does |
|---|---|
| `/sales-mailmo` | Mailmo — Email Finder, Email Verifier, catch-all detection, LinkedIn Chrome extension, bulk verification |
| `/sales-hunter` | Hunter.io — Domain Search, Email Finder, Email Verifier, Campaigns, Signals, TechLookup, MCP server, API |
| `/sales-prospeo` | Prospeo — person/company enrichment, LinkedIn Sales Navigator extraction, 5-step email verification, API |
| `/sales-tomba` | Tomba.io — domain search, email finder, email verifier, enrichment, author/LinkedIn/phone finder, API |
| `/sales-getprospect` | GetProspect — B2B email finder (200M+ contacts), LinkedIn extension, enrichment, cold email software, CRM |
| `/sales-skrapp` | Skrapp — B2B email finder (200M+ contacts), data enrichment, AI Fields, email verifier, LinkedIn extension |
| `/sales-anymailfinder` | Anymail Finder — email finder with 97%+ delivery guarantee, bulk search, GeoLead Finder, Chrome extension |
| `/sales-zerobounce` | ZeroBounce — email validation (99.6% accuracy), AI email scoring, inbox placement testing, blacklist monitoring |
| `/sales-minelead` | Minelead — B2B email finder (500M+ emails), lead finder, email verifier, disposable detector, campaigns, CRM |
| `/sales-safetymails` | SafetyMails — bulk email verification (19-step algorithm), real-time API, spamtrap/disposable detection |
| `/sales-openwebninja` | OpenWeb Ninja — 30+ real-time public data APIs, website contacts scraper, email search, local business data |
| `/sales-enrichso` | Enrich.so — LinkedIn enrichment, reverse email lookup, email/phone finder, company data, bulk enrichment |

</details>

<details>
<summary><strong>Data, Intelligence & Enrichment</strong></summary>

| Skill | What it does |
|---|---|
| `/sales-seamless` | Seamless.AI — Prospector, Buyer Intent, Job Changes, CRM Enrich, Pitch Intelligence, AI Agents, API |
| `/sales-clearbit` | Clearbit (HubSpot) — Person/Company Enrichment, Reveal (IP-to-company), Prospector, Breeze Intelligence, API |
| `/sales-rb2b` | RB2B — Person-Level Website Visitor ID (US), Company-Level ID (global), Hot Pages, Identity Resolution API |
| `/sales-retention` | Retention.com — ecommerce identity resolution, anonymous visitor → email/SMS, abandonment recovery |
| `/sales-customersai` | Customers.ai — X-Ray identity resolution for Shopify + Klaviyo, Alfred AI intent scoring, Inboxer deliverability, ad retargeting recovery |
| `/sales-6sense` | 6sense — Signalverse Intent Data (1T+ signals), Predictive Analytics, Sales Intelligence, AI Email Agents |
| `/sales-clay` | Clay — Waterfall Enrichment (150+ providers), Claygent AI agents, Sculptor, Signals, CRM Sync |
| `/sales-swan` | Swan — AI GTM Engineer, prompt-to-pipeline workflows, lead research, enrichment, qualification, LinkedIn + email outreach, pipeline monitoring, API |
| `/sales-leadmagic` | LeadMagic — Email Finder, Mobile Finder, Company Search, Job Change Detector, MCP Server, CLI |
| `/sales-outscraper` | Outscraper — Google Maps/Reviews scraping, email/contact extraction, multi-platform review scraping, API |
| `/sales-phantombuster` | PhantomBuster — code-free web/LinkedIn automation + scraping + lead-gen: pre-built Phantoms, Flows, AI Agents, LinkedIn Leads DB (cloud-run). REST API (`phantombuster.com/api/v2`, `X-Phantombuster-Key-1`) — launch agent→container→result (`/agent/{id}/launch`, `/containers/fetch-result-object`), JSend; per-agent webhooks (secret query param, 11s timeout); billed by execution time + Phantom slots (API on all paid plans); session-cookie account-safety caveats |
| `/sales-texau` | TexAu — GTM automation + data platform: Cloud/Desktop LinkedIn/web automations (recipes, automation hours) + V3 waterfall enrichment (32+ providers), people/lead search, async email finding/verification, web scraping. REST API (`v3-api.texau.com/api/v1`, `x-api-key`) + MCP server (`mcp.texau.com/mcp`) + n8n nodes; pay-on-match credits |
| `/sales-surfe` | Surfe (formerly Leadjet) — LinkedIn-to-CRM Chrome extension + waterfall enrichment API (15+ providers) syncing LinkedIn/Sales Navigator contacts into HubSpot/Salesforce/Pipedrive/Copper. REST API (`api.surfe.com/v2`, Bearer): async `people/enrich` + `companies/enrich` (enrichmentID), people/company search, `GET v1/credits`; webhooks with `x-surfe-signature` HMAC; annual credits across email/mobile/search pools |
| `/sales-lobstr` | Lobstr.io — 50+ no-code scrapers (Google Maps, LinkedIn, Twitter, YouTube), MCP Server, Python SDK |
| `/sales-cognism` | Cognism — Diamond Data phone-verified mobiles, Bombora intent signals, CRM enrichment, Sales Companion AI, GDPR/DNC compliance, API (Search, Redeem) |
| `/sales-leadiq` | LeadIQ — Chrome extension LinkedIn prospecting, Scribe AI outreach, champion tracking (job change alerts), CRM enrichment (Salesforce native + HubSpot/Workato), GraphQL API |
| `/sales-zoominfo` | ZoomInfo — SalesOS, MarketingOS, OperationsOS, Copilot AI, API (search, enrich, lookup, bulk, webhooks) |

</details>

<details>
<summary><strong>CRM & Marketing Automation</strong></summary>

| Skill | What it does |
|---|---|
| `/sales-crm-selection` | CRM comparison and selection — Attio vs HubSpot vs Salesforce vs Folk vs Pipedrive vs Close vs Zoho vs spreadsheets |
| `/sales-hubspot` | HubSpot — Smart CRM, Marketing/Sales/Service/Content/Data Hubs, Breeze AI, workflows, sequences, 2,000+ integrations, API |
| `/sales-salesforce` | Salesforce — Sales/Service/Marketing/Commerce Cloud, Data Cloud, Agentforce AI, Flows, Apex, AppExchange, REST API |
| `/sales-attio` | Attio — AI-native CRM with custom objects, deal pipelines, email sequences, automations, AI agents, API |
| `/sales-gohighlevel` | GoHighLevel (HighLevel) — all-in-one agency/SMB business OS: CRM + funnels + email/SMS/WhatsApp + workflows + reputation + payments + white-label SaaS resale; v2 REST API (`services.leadconnectorhq.com`, OAuth/Private Integration Tokens, `Version` header), Ed25519-signed webhooks, sub-accounts/snapshots; Starter $97 / Unlimited $297 / SaaS Pro $497 |
| `/sales-keap` | Keap (formerly Infusionsoft) — all-in-one small-business CRM + marketing automation: drag-and-drop Campaign Builder, email/SMS, sales pipeline, invoicing/payments, REST API (v1/v2, OAuth 2.0 + Personal Access Tokens), REST Hooks webhooks; per-contact pricing from ~$249-299/mo |
| `/sales-ontraport` | Ontraport — all-in-one CRM + marketing automation + payments + dynamic CMS: contacts, Campaign Builder, email/SMS, order forms/subscriptions, membership pages; object-based REST API (`api.ontraport.com/1`, `Api-Key`+`Api-Appid`, objectID model, 180 req/min) + webhooks; per-contact pricing ~$79-497/mo |
| `/sales-engagebay` | EngageBay — affordable all-in-one CRM + marketing + sales + service suite for startups/SMBs (Marketing Bay, Sales & CRM Bay, Service Bay) on one contact database; REST API (`app.engagebay.com`, raw API-key `Authorization` header, **XML-default — `Accept: application/json` for JSON**, cursor pagination, `subscribers`/deals/tickets) + **outbound-only, unsigned webhooks** (no incoming); plan-gated API quota; free tier 250 contacts → Pro ~$119.99/user/mo; "HubSpot at a fraction of the cost" |
| `/sales-pipedrive` | Pipedrive — pipeline-first sales CRM (deals, leads, persons/orgs, activities, automation, forecasting); REST API v1+v2 (`{company}.pipedrive.com/api/v2`, `x-api-token`/OAuth, cursor pagination, v1 shutdown 2026-07-31) + free webhooks; token-based daily rate limit (30k × plan multiplier × seats); 40-char custom-field hash keys; API on all plans (Lite/Growth/Premium/Ultimate) |
| `/sales-bitrix24` | Bitrix24 — free-forever all-in-one business suite (CRM: leads/deals/pipelines/SPA, + tasks, omnichannel contact center, sites/store, marketing, collaboration), cloud or self-hosted on-prem. Method-based REST API (`/rest/{user_id}/{webhook_code}/{method}`, e.g. `crm.deal.add`) with inbound + outbound webhooks, OAuth 2.0, `batch` (50/req), 740+ app Market, MCP server; unlimited-user free plan (Keap/Ontraport/Zoho alternative) |
| `/sales-salesmate` | Salesmate — AI-powered sales CRM for SMB/mid-market (contacts/companies, deal pipelines, activities, **built-in calling + SMS**, email sequences, marketing automation, Smart Flow workflows, ticketing, **Sandy AI** copilot); v4 REST API (`{link_name}.salesmate.io/apis/`, **header auth `accessToken` + `x-linkname`** — not Bearer, offset pagination via `rows`+`from`, **1500 calls/hour per link**, v1/v3 deprecated) + Zapier/Make; **no inbound webhooks** (push out via Smart Flow API/Webhook action); sequences + Sandy AI Pro+, Basic $23 / Pro $39 / Business $63 / Enterprise; Pipedrive/Close/Freshsales alternative |
| `/sales-insightly` | Insightly — unified **CRM + project management + marketing + service** for SMB/mid-market (a won **Opportunity converts into a delivery Project**; strong for agencies/consultancies/professional services); REST API v3.1 (`api.{pod}.insightly.com/v3.1`, **pod-specific base URL**, **HTTP Basic auth with the API key Base64-encoded as username + blank password** — un-encoded → 401, `top`/`skip`/`count_total` pagination, **plan-gated daily request quota** ~1k–100k + 10 req/s → 429, ETag/`If-Match` concurrency, `CUSTOMFIELDS` array); **webhooks are a Workflow Automation action (Professional+) that retries only twice**; **no email sequencing on any plan**, custom objects Enterprise-only; AppConnect built-in iPaaS; CRM Plus $29 / Professional $49 / Enterprise $99 per user/mo; Pipedrive/Zoho/Copper alternative |
| `/sales-maximizer` | Maximizer — long-standing Canadian sales + **financial-services** CRM, **cloud or on-premise** (Financial Advisor edition: households, investment/insurance views, family connections, compliance). Two APIs: the **Octopus API** (Maximizer.Web.Data, `api.maximizer.com/octopus`) is a **POST-RPC** JSON service (`/Read` `/Create` `/Update` `/Delete` `/Authenticate`…) with **Scope/Criteria/GroupBy/OrderBy** query bodies, a mandatory **`Configuration.Drivers`** searcher (wrong driver → empty result, not an error), opaque **base64 record `Key`s**, a `Code:0` success envelope, **`Udf/$TYPEID`** custom fields, PAT/OAuth2 auth, and **per-edition rate limits** (Core ~30/10s, Business/Financial ~90/30s); plus a separate **Webhooks API** (`/v1/targets` + `/v1/subscriptions`, **2-second 200 ACK, 3-attempt drop, no HMAC**); no free tier (30-day trial), Base ~$65 / Sales Leader ~$79 / Financial Advisor ~$79–100 per user/mo; Pipedrive/Salesforce alternative for regulated/advisory teams |
| `/sales-tableau` | Tableau — visual analytics, dashboards, Tableau Cloud/Server/Desktop, Prep, Pulse AI, Embedding API, REST API v3.28, MCP server |
| `/sales-mulesoft` | MuleSoft — Anypoint Platform, API-led connectivity, DataWeave, CloudHub, 450+ connectors, Composer, RPA, API Manager, Flex Gateway |
| `/sales-boomi` | Boomi — enterprise iPaaS, 1000+ connectors, API Management, Data Hub MDM, Flow low-code, Event Streams, B2B/EDI, AgentStudio AI agents |
| `/sales-workato` | Workato — enterprise iPaaS, 1200+ connectors, recipe automation, API Management, MCP Gateway, Agent Studio (Genies), Data Tables, Event Streams, Embedded iPaaS |
| `/sales-celigo` | Celigo — mid-market iPaaS, 1000+ connectors, AI error management, endpoint+flow pricing, NetSuite depth, API Management, B2B/EDI, Embedded iPaaS, Celigo Ora AI |
| `/sales-snaplogic` | SnapLogic — enterprise iPaaS, 1000+ Snap connectors, AgentCreator AI agents, SnapGPT pipeline copilot, API Management 3.0, ETL/ELT, Ultra Pipelines |
| `/sales-jitterbit` | Jitterbit — AI-infused Harmony iPaaS, 400+ connectors, Integration Studio + Design Studio, API Manager, App Builder, EDI/B2B, cloud/private/hybrid agents |
| `/sales-tray` | Tray.ai — enterprise iPaaS, 700+ connectors, Intelligent iPaaS, Merlin Agent Builder (OpenAI/Claude/Gemini/Llama, MCP), Tray Embedded (white-label for SaaS), Enterprise Core governance, GraphQL API, Connector Development Kit |
| `/sales-informatica` | Informatica IDMC — enterprise iPaaS + data management, Cloud Data Integration (CDI), Cloud Application Integration (CAI), API Center, Data Catalog, Data Quality, MDM, B2B Gateway, CLAIRE AI, IPU consumption pricing, REST API v2/v3 |
| `/sales-tibco` | TIBCO Cloud Integration — enterprise iPaaS with four pillars: Connect (TIBCO Scribe no-code), Develop (TIBCO Flogo event-driven), Integrate (TIBCO BusinessWorks hybrid), Automate (Cloud Live Apps citizen developer), plus TIBCO Cloud API Management, app-instance subscription tiers, regional APIs (AWS US/EU/AU, Azure US) |
| `/sales-activecampaign` | ActiveCampaign — marketing automation (900+ recipes), email marketing, CRM, multi-channel, 900+ integrations |
| `/sales-mailchimp` | Mailchimp — email campaigns, Customer Journey Builder, SMS, audience management, Mandrill, 300+ integrations |
| `/sales-closum` | Closum — omnichannel marketing automation: email, SMS, WhatsApp, Telegram, Web Push, AI assistant |
| `/sales-ghost` | Ghost — open-source publishing, native newsletters, paid memberships via Stripe, Content API, Admin API, themes, migration |
| `/sales-beehiiv` | Beehiiv — newsletter publishing, Boosts, Ad Network, referral programs, paid subscriptions, digital products, API |
| `/sales-buttondown` | Buttondown — simple newsletter publishing, paid subscriptions via Stripe, Markdown editor, automations, REST API, CLI, custom domains |
| `/sales-mailerlite` | MailerLite — email campaigns, automation, landing pages, signup forms, e-commerce, digital products, paid newsletters, API |
| `/sales-unbounce` | Unbounce — landing page builder, Smart Traffic AI, Smart Copy AI, A/B testing, DTR, popups, sticky bars, AMP pages, REST API |
| `/sales-leadpages` | Leadpages — landing page builder, pop-ups, alert bars, A/B testing, Leadmeter, lead enrichment, Stripe payments |
| `/sales-landingi` | Landingi — AI landing page builder ("landing page operation system"): Lunar AI page generator, drag-and-drop Visual Builder, 400+ templates, form/lead capture, A/B testing, EventTracker, Smart Sections, Dynamic Text Replacement (DTR), multi-language, programmatic landing pages, Solis AI insights, Orbit MCP server; REST API (`api.landingi.com`, `X-Api-Key` or OAuth 2.0) for landing pages/leads/form submissions, per-form webhooks, WordPress plugin, 170+ integrations; lower-cost Unbounce/Leadpages alternative |
| `/sales-instapage` | Instapage — premium AI landing page + post-click conversion platform: drag-and-drop builder, AI Content Generator, AdMap ad-to-page mapping, A/B testing + AI Experiments, Personalization/Dynamic Text Replacement (DTR), heatmaps, AMP + Thor Render Engine, Global Blocks, Collections, form lead capture; REST API (`api.instapage.com/v1`, Bearer personal token) for workspaces/pages/collections/submissions/analytics, per-form submit webhook, 120+ integrations; the high-end Unbounce/Landingi alternative |
| `/sales-convertri` | Convertri — speed-focused sales funnel + landing-page builder ("world's fastest"): free-form drag-anywhere editor, CDN/SSL sub-3s pages, page importer, split testing, DTR, interactive video, integrated cart with one-click upsells/bump sells, membership delivery. No public REST API — automation is the Zapier API key (8 triggers) + custom webhooks (Sale/Rebill/Refund/Lead Capture) signed with `cverify` (SHA-1, first 8 chars); amounts in pennies. Impression-metered pricing (Convert $99 / Scale ~$199 / Maximize $299, $30 per extra 250k); ClickFunnels/Landingi alternative |
| `/sales-seedprod` | SeedProd — self-hosted WordPress drag-and-drop website + landing-page builder plugin (by Awesome Motive): Theme Builder (headers/footers/templates/WooCommerce), 300+ templates, Smart Sections, built-in coming-soon/maintenance/404/login pages, opt-in/sales pages, subscriber capture to 13 ESPs + reCAPTCHA, Dynamic Text, AI Theme Builder. No public REST API or webhook — automation is the WordPress Abilities API (WP 6.9 + SeedProd 6.20+, 8 named actions: toggle-coming-soon/maintenance, save-page, import-theme…), permission filters, shortcodes, Zapier (Pro+). Annual intro pricing Basic $79 / Plus $199 / Pro $399 / Elite $599 (WooCommerce + Domain Mapping Elite-only); WordPress-native Leadpages/Unbounce/Instapage alternative |
| `/sales-beaver-builder` | Beaver Builder — stable, developer-friendly standalone WordPress drag-and-drop page builder (by FastLine Media): a live front-end editor that builds pages as Rows → Columns → Modules over any theme with clean, semantic markup (not a Gutenberg block plugin), reusable Templates + Saved Rows/Modules, the Beaver Builder Theme, and Beaver Themer (theme builder — dynamic headers/footers/archives/singular templates via Field Connections to WordPress/ACF/EDD/WooCommerce data + a Loop Builder), plus Assistant Pro cloud asset library; white labeling on Unlimited. No hosted REST API or webhook — the real surface is a PHP developer API (custom modules extending `FLBuilderModule` + `FLBuilder::register_module()`, a large `fl_builder_*` hooks/filters surface, searchable at hooks.wpbeaverbuilder.com) plus the WordPress REST API/WP-CLI (layout in `post_content` + serialized `_fl_builder_data` meta). Flat per-plan licensing Starter $89 (1) / Plus $179 (3) / Professional $299 (50, +multisite) / Unlimited $546 (∞, +white label); Themer + Loop Builder + WooCommerce on all paid tiers; free Lite on WordPress.org; low lock-in (text survives deactivation), no native A/B testing; Elementor/Divi/Bricks/SeedProd alternative |
| `/sales-breakdance` | Breakdance — standalone visual website/page builder for WordPress (by Soflyy, the Oxygen makers): a themeless front-end editor (NOT a Gutenberg block plugin, closer to Elementor/Beaver Builder/Oxygen — Oxygen 6 runs on the Breakdance engine) with Elements/Templates/Design Library, a WooCommerce Builder, a built-in Form Builder + Popup Builder, Dynamic Data, Element Studio (custom-element IDE), and Breakdance AI; markets clean markup, conditional asset loading (~45 KB blank page), and jQuery-independence. No hosted REST API or platform outbound webhook — the real surface is a PHP developer API (Form Actions API extending `Breakdance\Forms\Actions\Action`, Dynamic Data Field API, Conditions API, `breakdance_*` hooks/filters, AI endpoint filters `breakdance_ai_api_endpoint`/`breakdance_ai_model` to route AI to OpenRouter/Claude) plus the WordPress REST API (page layout is opaque post meta); the form Webhook action POSTs to Zapier/Make. Free / Pro ~$199.99/yr (unlimited sites + unlimited domains) / +AI bundle ~$249.99 — no lifetime plan, price-lock guarantee; key gotcha: spam plugins can't intercept the form Email action (spam still emails); Bricks/Elementor/Oxygen/Beaver Builder/SeedProd alternative |
| `/sales-spectra` | Spectra — Gutenberg-native WordPress website/page builder plugin (by Brainstorm Force, Astra makers; formerly Ultimate Addons for Gutenberg, 1M+ installs): extends the native block editor with 30+ blocks (flexbox Container, Post Grid/Carousel, Forms, FAQ/Schema), Starter Templates, Popup Builder, Coming Soon mode, animations, local Google Fonts, Global Styles, Spectra AI; Pro adds Loop Builder, Dynamic Content, display conditions, role permissions, white label. No hosted REST API or webhook — extend via the WordPress REST API + public hooks/filters (`render_block`, `uagb_post_query_args_*`, `spectra_pro_rest_api_get_controllers` for a custom REST controller); design-library role gating via `ast_block_template_capability_additional_roles`. Free / Spectra Pro ~$49–69/yr / Essential & Business Toolkits (lifetime deals); no native A/B testing; Kadence Blocks/GenerateBlocks/Elementor/SeedProd alternative |
| `/sales-kadence` | Kadence Blocks — Gutenberg page-builder block plugin for WordPress (by StellarWP / Liquid Web; 600k+ installs, GPLv2): extends the native block editor with 20+ free blocks (Row Layout/Section flexbox containers, Advanced Form, Gallery, Tabs, Posts, Testimonials) plus the Design Library; Pro adds Advanced Query Loop, Dynamic Content (ACF/MetaBox/WooCommerce), Advanced Slider, Modal, Custom Fonts, Kadence AI, and Advanced Form webhooks. No hosted REST API — extend via the WordPress REST API (`kadence/` block markup) + public hooks/filters (`kadence_blocks_posts_query_args`, `kadence_blocks_pro_query_loop_query_vars`, `kadence_element_display`) and the Pro Advanced Form webhook (Actions After Submit → WebHook → Map Fields). Free / Kadence Blocks Pro (~$89/yr) / Kadence bundles Essentials ~$99·Pro ~$299·Elite ~$499; dynamic-CSS TTFB tuning; no native A/B testing; the closest Spectra/GenerateBlocks rival |
| `/sales-generateblocks` | GenerateBlocks — minimalist, high-performance Gutenberg block plugin for WordPress (by EDGE22 Studios / GeneratePress makers; 200k+ installs): a few composable primitives (Container, Grid, Headline, Button, Image, Query Loop) instead of dozens of widget blocks, for the leanest DOM/CSS; Pro adds Dynamic Data (post meta/ACF/featured image), Global Styles, 150+ templates, device visibility, shape dividers, scroll effects. No hosted REST API, webhook, or form block — extend via the WordPress REST API (`generateblocks/` block markup) + public filters (`generateblocks_dynamic_tag_output`, `generateblocks_dynamic_content_output`, `generateblocks_do_content`) and the `GenerateBlocks_Register_Dynamic_Tag` class (2.0+). Free / Pro Personal ~$59/yr (1 site) / Pro Professional ~$99/yr (500 sites) / GeneratePress One ~$149/yr; GenerateBlocks 2.0 rewrite; no native A/B testing; the performance/dev pick vs Kadence/Spectra/Stackable |
| `/sales-stackable` | Stackable — design-focused, Gutenberg-native block plugin for WordPress (by Gambit Technologies / gambitph; GPLv3, 200k+ installs, 4.9★): extends the native block editor with 42 free blocks (Columns, Hero, Card, Carousel, Pricing, Testimonial, Blog Posts, Timeline), a Global Design System (Global Colors/Typography, block defaults), a 375+ Design Library, and theme.json/block-theme support, with a lean footprint; Pro adds Dynamic Content (ACF/Metabox/JetEngine), Motion Effects, Conditional Display, Role Manager, and per-block Custom CSS. No hosted REST API, webhook, form block, popup builder, or WooCommerce blocks — extend via the WordPress REST API (`stackable/` block markup), the `stackable_force_css_load` filter, and WordPress `render_block`; GPLv3 source on GitHub. Free / Premium ~$49/yr / All Access Pass ~$89/yr (1/10/Unlimited + Lifetime toggles); the v2→v3 migration is the key gotcha; no native A/B testing; Spectra/Kadence/GenerateBlocks alternative |
| `/sales-greenshift` | Greenshift — performance-focused, animation-rich Gutenberg page-builder block plugin for WordPress (by Wpsoul; slug `greenshift-animation-and-page-builder-blocks`, ~4.8★): 50+ blocks, a GSAP animation framework (scroll/hover/parallax, pin/smooth scroll), Interaction Layers, 3D/AR-VR/Lottie/Rive, ~2 KB base styles + conditional asset loading + no jQuery; paid packs add dynamic fields + the Query addon (Dynamic Chart/FAQ/Filter/Search, ACF/ACPT/external repeaters), WooCommerce blocks, AI Helpers (bring-your-own key), Figma/HTML/webpage→blocks converters, a VS Code extension, and SEO/schema blocks. The standout is an **API Connector** that binds external REST APIs, Google Sheets/CSV, and LLM APIs (OpenAI chat/streaming) into blocks — server-side (Application-Password auth, `{{INCREMENT}}`/`{{USER_META}}` placeholders) or client-side (browser fetch, `{{VALUE}}`/`{{COOKIE}}` placeholders; **client-side keys are public — proxy secrets server-side**), firing a `GSPB_API_RESPONSE` JS event. No hosted REST API, webhook, or core form block — extend via the WordPress REST API (`greenshift-blocks/` markup) + the API Connector. Free / Design ~$39.99/yr · Woo ~$49.99/yr · GreenLight PRO ~$51.99/yr · All-in-One ~$59.99/yr (1/5/Unlimited + lifetime, crypto accepted); no native A/B testing; Spectra/Kadence/GenerateBlocks/Stackable/Nexter alternative |
| `/sales-gutenverse` | Gutenverse — free, Gutenberg-native FSE block plugin + ecosystem for WordPress (by Jegstudio/Jegtheme; 20k–34k+ installs, 4.9★): extends the native block editor with 57 free blocks (Layout/Container/Popup Builder, Content, Interactive — Tabs/Accordion/Testimonials/Countdown/Chart, Post/Query, Social, Google Maps), a 600+ starter-template library, global colors/fonts, and a companion FSE theme (Unibiz); Pro adds dynamic data, display conditions, custom fonts, premium templates/blocks, mega menu, and Lottie/sticky/cursor effects. Lead capture is a **separate free Gutenverse Form plugin** (entries stored in WordPress + CSV export, admin/user email notifications, reCAPTCHA — no webhook/Zapier/CRM, conditional logic, multi-step, or payment fields in free). No hosted REST API or webhook — automate via the WordPress REST API (`gutenverse/` block markup, Application-Password auth) + the `gutenverse-core` framework hooks (`gutenverse_after_init_framework`, `gutenverse_include_block`, `gutenverse_block_config`); Pro licensing via LemonSqueezy. Free / Pro ~$55–99/yr (single → Professional ~10 sites) / Agency ~$199/yr (~100 sites); no native cart or A/B testing; key gotcha: the editor page failing to load after a customization change; Spectra/Kadence/GenerateBlocks/Stackable/Greenshift/Nexter alternative |
| `/sales-gutenkit` | GutenKit — feature-rich Gutenberg-native block plugin + page builder for WordPress (by Wpmet, the ElementsKit makers; slug `gutenkit-blocks-addon`, 70k+ installs, Block API v3, zero jQuery, FSE-compatible): extends the native block editor with 65+ blocks on a flexbox Container (Nav/Mega Menu, Query Loop Builder, Advanced Accordion/Tab, Post Grid, Pricing Table, Countdown, Image Comparison, Offcanvas, Timeline, Testimonial), a 900+ template library, global colors/fonts, local Google Fonts, and inline SVG icons; Pro adds the Mega Menu, Query Loop Builder, Dynamic Content (post meta/ACF/user/site fields), Display Conditions, One Page Scroll, Sticky Content, Glass Morphism, Advanced Tooltip, Google Map, and advanced Parallax. Lead capture is a **Mailchimp opt-in block only** — no full form builder, stored entries, webhooks, or Zapier. No hosted REST API or webhook — automate via the WordPress REST API (`gutenkit/` block markup, Application-Password auth) + WordPress `render_block`; no published action/filter SDK. Free / Personal ~$39/yr (~$89 lifetime, 1 site) / Professional ~$79/yr (~$189 lifetime, 5 sites) / Agency ~$149/yr (~$389 lifetime, unlimited); no native cart or A/B testing; key gotchas: a block "encountered an error and cannot be previewed" / editor won't load after a change, and the Template Library erroring inside ElementsKit Lite; Spectra/Kadence/GenerateBlocks/Stackable/Gutenverse/Greenshift/Nexter alternative |
| `/sales-superb-addons` | Superb Addons — Gutenberg-native block-addon plugin for WordPress (by SuperbThemes/Suplugins; slug `superb-blocks`, 80k+ installs, 4.9★): extends the native block editor with 20 blocks (Carousel, Countdown, Progress Bar, Google Maps, Add to Cart, Multi-Step Form), 200+ patterns, 50+ pre-built pages, 20+ header/footer templates, a Theme Designer, 70+ animations, and responsive visibility controls. Its edge over form-less block plugins is a real **form builder** — multi-step forms, calculated fields, conditional logic, anti-spam (honeypot/hCaptcha/reCAPTCHA/Turnstile), submission storage + GDPR auto-deletion, and **outbound integrations: webhook + Mailchimp + Brevo + Google Sheets + Slack**. No public hosted REST API or MCP — automate via the form webhook + native integrations + the WordPress core REST API (namespaced block markup, Application-Password auth). Free / Premium ~$29–$49/yr or ~$59–$99 lifetime (1/3/50 sites); plan-gating is ambiguous (the WordPress.org readme markets a free form builder while the pricing page lists Forms/Popups/animations/Theme Designer as Premium — verify on the install); no native cart or A/B testing; key gotchas: the Theme Designer not loading/responding (run the built-in Troubleshooter; a documented Gutenverse conflict), and saved form submissions not showing in wp-admin under some permalink configs; Spectra/Kadence/GenerateBlocks/Stackable/Gutenverse/GutenKit/Nexter alternative |
| `/sales-groove` | Groove.cm — GroovePages, GrooveFunnels, GrooveSell, GrooveMail, GrooveAffiliate, GrooveMember, GrooveWebinar |
| `/sales-kartra` | Kartra — all-in-one for coaches/course creators: funnels, email/SMS, Kartra Checkouts, memberships, video, webinars, affiliates; inbound API (`app.kartra.com/api`, `actions[]`, 20 calls/sec) + IPN webhooks |
| `/sales-systemeio` | Systeme.io — budget all-in-one for bootstrappers: funnels, email, courses, community, affiliates, automated webinars, free plan; REST API (`api.systeme.io`, `X-API-Key`, cursor pagination) + webhooks |
| `/sales-clickfunnels` | ClickFunnels — the category-defining all-in-one funnel builder (ClickFunnels 2.0): funnels, e-commerce, email/Workflows, CRM, courses, checkout/upsells, Backpack affiliates; V2 REST API (`{workspace}.myclickfunnels.com/api/v2`, Bearer + `User-Agent`, cursor/offset pagination) + signed webhooks |
| `/sales-wpfunnels` | WPFunnels — WordPress sales-funnel builder plugin for WooCommerce (CartFlows/FunnelKit competitor): funnel canvas, order bumps, one-click upsells/downsells, A/B testing, abandoned-cart recovery, conditional steps, bundled Mail Mint email. WordPress-only (no REST API); per-funnel webhooks (All/Select Fields body, undocumented payload/events, no HMAC), Mail Mint triggers, WooCommerce order hooks/REST (revenue lives in WooCommerce), WP hooks; designed in Elementor/Gutenberg/Divi/Bricks/Oxygen; free Lite + Pro |
| `/sales-funnelkit` | FunnelKit — WordPress/WooCommerce sales-funnel builder + built-in CRM/marketing-automation suite (formerly WooFunnels/Autonami): checkout, order bumps, one-click upsells/downsells, A/B testing, sliding cart + email/SMS automations, segments, cart-abandonment recovery. FunnelKit Automations REST API (`/wp-json/funnelkit-automations/`, api_key query param) with Tags/Lists/Fields/Contacts CRUD + incoming/outgoing webhooks; funnel revenue read via WooCommerce orders; free + Plus/Professional/Elite bundles |
| `/sales-cartflows` | CartFlows — lean checkout-first WordPress/WooCommerce sales-funnel builder (by Brainstorm Force, 200k+ installs): modern checkout layouts, custom checkout fields, dynamic order bumps, one-click upsells/downsells, A/B split testing; no built-in CRM/email. Self-hosted WordPress only — no hosted REST API/MCP; WP-CLI (`wp cartflows license activate`), personalization + offer-JS shortcodes, WordPress hooks, OttoKit/Zapier, Cart Abandonment Recovery webhooks; funnel revenue read via WooCommerce orders; designed in Elementor/Divi/Bricks/Gutenberg; free + Pro/Suite/lifetime |
| `/sales-builderall` | Builderall — budget all-in-one suite: website/funnel builders, MailingBoss email, SuperCheckout, CRM, courses, webinars, chatbot; MailingBoss-only API (`member.mailingboss.com`, token-in-URL, subscriber endpoints) + per-list inbound webhooks; funnel builder gated to a higher tier |
| `/sales-brevo` | Brevo — email/SMS/WhatsApp campaigns, marketing automation, Sales CRM, Conversations, Loyalty, Aura AI |
| `/sales-iterable` | Iterable — cross-channel engagement, Studio journeys, Iterable AI, Smart Ingest, Snowflake sharing, API |
| `/sales-getresponse` | GetResponse — email marketing, visual automation, conversion funnels, landing pages, webinars, course creator |
| `/sales-braze` | Braze — Canvas Flow, multi-channel messaging, BrazeAI, Braze Data Platform, Catalogs, Feature Flags, API |
| `/sales-customerio` | Customer.io — Journeys, multi-channel (email, SMS, push, in-app, WhatsApp), Data Pipelines, Custom Objects |
| `/sales-klaviyo` | Klaviyo — AI-first B2C CRM for e-commerce, Flows, Predictive Analytics, multi-channel, CDP, AI Agents |
| `/sales-omnisend` | Omnisend — email campaigns, SMS, web push, automation workflows, Shopify/WooCommerce/BigCommerce |
| `/sales-sendpulse` | SendPulse — email marketing, Automation 360, chatbots, CRM, course builder, web push, SMS, MCP Server |
| `/sales-kit` | Kit (ConvertKit) — Visual Automations, Sequences, Broadcasts, landing pages, Commerce, API |
| `/sales-swai` | SWAI.ai — Autonomous Revenue OS, AI-driven campaigns, landing page builder, CRM, AI assistants |
| `/sales-adroll` | AdRoll — retargeting, display/social/CTV campaigns, dynamic retargeting, RollWorks ABM, attribution |
| `/sales-remerge` | Remerge — in-app retargeting DSP, audience segmentation, incrementality measurement, MMP integrations, Reporting API |
| `/sales-adwake` | Adwake — managed mobile app UA, branding, in-app retargeting, Playback Rewards loyalty, Entravision |
| `/sales-zoomd` | Zoomd — mobile UA across 600+ sources, mobile DSP, CGC creator content, Albert.ai AI optimization |
| `/sales-reddit-ads` | Reddit Ads — subreddit targeting, 12 ad formats, Reddit Pixel, CAPI, Lead Gen Ads, Business Manager |
| `/sales-jotform` | Jotform — form builder, payment forms, e-signatures, approval workflows, tables, PDF editor, app builder, REST API, MCP server |
| `/sales-typeform` | Typeform — conversational forms, surveys, quizzes, video forms, Workflow Builder, Embed SDK, Create/Responses/Webhooks API |
| `/sales-blueconic` | BlueConic — Customer Data Platform (CDP), profile unification, segmentation, audience activation, Jebbit Experiences, MCP server, REST API v2 |
| `/sales-treasuredata` | Treasure Data — enterprise AI-native CDP, profile unification, identity resolution, 400+ connectors, AI Marketing Cloud, Audience Studio, TD API |
| `/sales-tealium` | Tealium — enterprise CDP, Real-Time/Composable/Hybrid CDP, iQ Tag Management, EventStream, AudienceStream, 1300+ connectors, V3 API |
| `/sales-contentstack` | Contentstack — enterprise headless CMS, Content Management/Delivery APIs, GraphQL, Launch hosting, Automate workflows, Personalize, Brand Kit AI, Marketplace |
| `/sales-rudderstack` | RudderStack — warehouse-native CDP, Event Streams, Reverse ETL, Transformations, Profiles, 200+ destinations, open-source, HTTP API |
| `/sales-mparticle` | mParticle — hybrid CDP, real-time event streaming, identity resolution (IDSync), audience activation, 300+ integrations, Composable Audiences, AI/Cortex, Data Plans, 7 APIs |
| `/sales-cdp` | CDP comparison and selection strategy — Tealium, BlueConic, Segment, Treasure Data, mParticle, composable vs bundled |

</details>

<details>
<summary><strong>Transactional Email</strong></summary>

| Skill | What it does |
|---|---|
| `/sales-sendgrid` | SendGrid (Twilio) — Email API, Marketing Campaigns, transactional email, dynamic templates, 7 SDKs |
| `/sales-postmark` | Postmark (ActiveCampaign) — transactional email API, SMTP relay, Message Streams, DMARC Monitoring |
| `/sales-mailgun` | Mailgun (Sinch) — transactional email API, SMTP relay, inbound routing, Mailgun Optimize, dedicated IPs |

</details>

<details>
<summary><strong>CRO & Experimentation</strong></summary>

| Skill | What it does |
|---|---|
| `/sales-vwo` | VWO — A/B testing, multivariate tests, heatmaps, session recordings, personalization, feature flags, SDKs, REST API |

</details>

<details>
<summary><strong>Sales Enablement Platforms</strong></summary>

| Skill | What it does |
|---|---|
| `/sales-seismic` | Seismic — Enablement Cloud, content management, Learning & Coaching, Aura AI, Digital Sales Rooms |
| `/sales-allego` | Allego — AI-powered revenue enablement, Modern Learning, Modern Content, Digital Sales Rooms |
| `/sales-altern` | Altern — curated AI tools directory (10,000+ tools, 100+ categories), listing optimization, dofollow backlinks |

</details>

<details>
<summary><strong>Media Intelligence & PR</strong></summary>

| Skill | What it does |
|---|---|
| `/sales-meltwater` | Meltwater — media intelligence, social listening, media relations, influencer marketing, Mira AI, API |
| `/sales-mention` | Mention — real-time media monitoring, brand tracking, sentiment analysis, competitor benchmarking, review monitoring, REST API |
| `/sales-awario` | Awario — budget social listening, Boolean search, Awario Leads social selling, Reddit monitoring, REST API (Enterprise) |
| `/sales-brand24` | Brand24 — AI social listening, brand monitoring, sentiment analysis, Share of Voice, Storm Alerts, MCP server |
| `/sales-threadlytics` | Threadlytics — Reddit-specific monitoring, 500M+ indexed conversations, keyword tracking, sentiment, Share of Voice, opportunity scoring |
| `/sales-mentionlytics` | Mentionlytics — mid-market social listening, SIA AI advisor, sentiment analysis, Share of Voice, REST API (Pro+) |
| `/sales-brandmentions` | BrandMentions — social listening, emotion AI sentiment, competitor intelligence, Share of Voice, white-label reports, REST API (Enterprise) |
| `/sales-youscan` | YouScan — AI visual analytics (logo/scene/object detection in images), social listening, Insights Copilot AI agent, webhooks, REST API (Unlimited) |
| `/sales-talkwalker` | Talkwalker — enterprise social listening, media monitoring, image/logo recognition, Blue Silk AI, Streaming API, Hootsuite integration |
| `/sales-octolens` | Octolens — developer-first social listening (Reddit, GitHub, HN, X, LinkedIn, Bluesky, Stack Overflow, DEV.to), AI relevance scoring, MCP server, REST API, webhooks |
| `/sales-konnectinsights` | Konnect Insights — omnichannel CXM with social listening, unified inbox (30+ channels), analytics, publishing, crisis management, Zapier (7 triggers), REST API, native CRM connectors |
| `/sales-socialhose` | Socialhose — social listening with transparent pricing, no annual contracts, flexible monitoring speeds (daily/high-frequency/crisis), webhooks (Pro+) |
| `/sales-xpoz` | Xpoz — social data API and MCP server for AI agents, 1.5B+ indexed posts across Twitter/X, Instagram, TikTok, Reddit, TypeScript/Python SDKs, free tier |
| `/sales-keymentions` | KeyMentions — Reddit keyword monitoring with AI comment generation and auto-publish for lead generation, virality detection |
| `/sales-syften` | Syften — AI-filtered keyword monitoring across Reddit, HN, X, Bluesky, Mastodon, GitHub, YouTube, Stack Exchange, Dev.to, 15+ community platforms, sub-minute alerts, REST API, webhooks |
| `/sales-reddinbox` | Reddinbox — AI audience intelligence across Reddit, X, Bluesky, HN, YouTube, Facebook, natural language queries, purchase intent scoring, market briefs, idea validation |
| `/sales-painonsocial` | PainOnSocial — AI-powered Reddit pain point discovery with frequency/severity scoring, evidence quotes, solution generation, idea validation |
| `/sales-redditmentions` | RedditMentions — cheapest Reddit keyword monitoring (€4.49/mo), email digests + Slack alerts, 30-min scan interval, negative keywords |
| `/sales-redreach` | Redreach — AI-powered Reddit lead generation with keyword auto-discovery, Google-ranking post detection, AI reply suggestions, Chrome extension DM automation, webhook alerts, ~$19/mo |
| `/sales-redship` | RedShip — AI-powered Reddit monitoring with relevance scoring (0-100), SEO post discovery, real-time alerts, AI reply drafts, REST API + webhooks, $19/mo |
| `/sales-reddgrow` | ReddGrow — Reddit marketing for AI search visibility (GEO) with AI Visibility Scanning (220+ countries, 4+ AI platforms), AI comment drafting, Chrome extension posting, karma warmup, REST API, CLI, $59-299/mo |
| `/sales-replyagent` | ReplyAgent — Reddit marketing automation with managed account posting, AI comment generation, Google-ranking post detection, UTM tracking, pay-per-post ($3/comment) |
| `/sales-replymer` | Replymer — managed Reddit/X reply marketing with human-written replies, SEO Replies targeting Google-ranking posts, REST API, $99-1,999/mo |
| `/sales-replierai` | ReplierAI — AI-powered Reddit monitoring and reply tool with Chrome extension, brand voice customization, sentiment analysis, $10-50/mo (introductory) |
| `/sales-replyguy` | ReplyGuy — AI reply generation across Twitter, Reddit, LinkedIn with keyword monitoring, auto-reply (Twitter), semi-manual (Reddit/LinkedIn), $49/mo |
| `/sales-leadlee` | Leadlee — cheapest Reddit lead generation with AI replies ($12/mo), quality scoring, Chrome extension, auto-reply beta, free tier (15 leads) |
| `/sales-forumscout` | ForumScout — AI social listening across 10M+ forums, Reddit, X, LinkedIn, YouTube, Instagram, Bluesky, HN, Facebook with natural language AI filtering, sentiment, competitive intel, API/MCP via apidirect.io, $19-129/mo |
| `/sales-f5bot` | F5Bot — free Reddit/HN/Lobsters keyword monitoring (200 free keywords, 50 hits/day), email alerts within minutes, advanced filtering, AI semantic alerts (Ultra), REST API + webhooks (Ultra), RSS/JSON feeds (Power+), $0-58/mo |
| `/sales-kwatch` | KWatch.io — multi-platform keyword monitoring (Reddit, HN, X, LinkedIn, Facebook, YouTube), AI sentiment, real-time email/Slack/webhook alerts, REST API (Business+), conversation tracking, $0-199/mo |
| `/sales-buska` | Buska — AI social listening for lead generation across 30+ platforms, buying intent scoring (0-100), ICP matching, Reply Studio, Prospect Finder enrichment, REST API (Growth+), MCP server (Scale), webhooks, native CRM/outreach connectors, $49-249/mo |
| `/sales-clearcue` | Clearcue — GTM signal engine for real-time buyer intent across LinkedIn, X, Reddit, news, jobs, podcasts, events with signal stacking, AI qualification, dynamic audiences, MCP server, webhooks (Pro+), CRM (Scale+), €79-439/mo |
| `/sales-commentions` | Commentions — automated brand mention commenting across LinkedIn, X, YouTube, Quora with AI comment generation, post discovery, engagement analytics, $59-149/mo |
| `/sales-crowdreply` | CrowdReply — AI search visibility tracking + managed Reddit/Quora/Facebook engagement via trusted community profiles, citation source intelligence, prompt tracking, $99-499+/mo |
| `/sales-leado` | Leado — AI-powered Reddit lead generation with buying intent scoring (0-100), AI reply drafts, Karma Builder, Viral Template Library, compliance engine, $0-29.99/mo, no API |
| `/sales-subtle` | Subtle AI — Reddit lead generation for SaaS with campaign-based post discovery, AI response generation, browser extension, $20-120/mo, no API |
| `/sales-replydaddy` | ReplyDaddy — Reddit marketing co-pilot with AI post discovery, relevance scoring, response generation, BYOK AI model, $0-799/mo or ~$59 LTD + API costs, no API |
| `/sales-leedlime` | Leedlime — AI-powered Reddit lead generation with intent scoring, lead management dashboard, credit-based pay-per-lead pricing ($0.09-0.20/lead), Slack/Discord alerts, no API |
| `/sales-opportunai` | OpportunAI — AI-powered Reddit lead generation with opportunity scoring, sentiment analysis, business profile analysis, free tier + $29/mo Pro, no API |
| `/sales-reppit` | Reppit AI — Reddit-only lead generation with AI keyword discovery from product URL, 0-100 buying intent scoring, AI reply drafts, manual posting only, ~$25-29/mo, no API |
| `/sales-tydal` | Tydal — AI-powered Reddit lead generation with auto-posting, AI comment drafts, 50+ viral templates, intent scoring, 5-subreddit limit, 48h scan interval, $29/mo, no API |
| `/sales-mentionclick` | mention.click — AI-powered Reddit intelligence with semantic vectorization, 0-10 similarity scoring, auto-keyword extraction from product description, 5-min scan intervals, $99/mo, no confirmed API |
| `/sales-pluggo` | Pluggo — AI-powered multi-platform social listening (Reddit, X, HN, Bluesky, Facebook, LinkedIn) with Slack-delivered opportunities, AI copilot, $0-41.58/mo, no API |
| `/sales-leadmore` | Leadmore AI — safe Reddit marketing via managed high-karma accounts, subreddit discovery with strategy recommendations, lead tracking, pay-per-post ($4/comment, $7/post), no API |
| `/sales-opencordai` | Opencord AI — AI agent-powered social engagement on Twitter/X and Reddit with autonomous reply generation, keyword-based opportunity discovery, credit-based pricing, $0-96/mo |
| `/sales-communitytracker` | CommunityTracker — community intelligence for GTM teams, high-intent buyer signals across Reddit/Slack/Discord/LinkedIn/X/GitHub/HN, intent scoring, share of voice, team workflows, REST API (Pro+), webhooks, $29-199/mo |
| `/sales-prospy` | Prospy — AI social listening and lead generation across Twitter/X, Reddit, Bluesky, HN with AI lead scoring, brand monitoring, competitor tracking, AI reply suggestions, $24/mo, no API |
| `/sales-buzzabout` | Buzzabout — AI-powered social media intelligence analyzing conversations across Reddit, TikTok, YouTube, Instagram, LinkedIn, X for audience insights, sentiment with motivation analysis, trend/narrative tracking, synthetic audience segmentation, $49/mo |
| `/sales-leadverse` | Leadverse — AI-powered lead discovery across Reddit, X, LinkedIn with keyword tracking, lead scoring, AI reply suggestions, Slack/email alerts, $19-39/mo |
| `/sales-bazzly` | Bazzly — AI-powered Reddit lead generation with intent scoring, contextual DM/reply drafting, Chrome extension sending, Reply Boost, credit-based model, $19-99/mo |
| `/sales-devta` | Devta — AI Networking Agent for proactive community engagement on Reddit, LinkedIn, Upwork with Persona-based commenting, DM nurturing, Draft Posts, credit-based pay-as-you-go |
| `/sales-reddily` | Reddily — AI-powered Reddit thread analysis for market research with sentiment, pain points, feature requests, competitor mentions, batch processing, Chrome extension, pay-per-analysis ~$0.27/thread |
| `/sales-trendseeker` | Trend Seeker — Reddit-based business idea discovery and validation with evidence scoring, demand signals, public REST API |
| `/sales-catchintent` | CatchIntent — AI-powered intent detection across Reddit, X, HN, Bluesky with relevance scoring (0-100), lead enrichment, CRM integrations, MCP server, webhooks, $49-69/mo |
| `/sales-subredditsignals` | Subreddit Signals — Reddit lead generation with 7-dimension buyer intent classification, AI Comment Builder with voice training, Engagement Queue, $29-59/mo |
| `/sales-devi` | Devi AI — Chrome extension for social media lead monitoring across Facebook groups, LinkedIn, X, Reddit, WhatsApp, Telegram with AI buying intent detection, ChatGPT outreach drafts, $49/mo |
| `/sales-parsestream` | ParseStream — multi-platform keyword monitoring (Reddit, X, LinkedIn, Quora, HN) with AI reply drafts and Reddit auto-reply, ~$29-79/mo |
| `/sales-soclistener` | SocListener — Reddit lead gen with AI context matching (not just keywords), personalized comment/DM drafting, credit-based pricing |
| `/sales-prems` | Prems AI — multi-platform lead generation across 15 platforms (Reddit, X, LinkedIn, HN, Quora, Facebook, Indie Hackers, Dev.to, Stack Overflow, YouTube, Product Hunt, Bluesky, Medium, GitHub, Substack) with AI intent scoring (0-100), AI Pitcher reply drafts, auto-pilot, webhooks, $49/mo |
| `/sales-threadradar` | ThreadRadar — Reddit + Quora keyword monitoring with AI-drafted replies for lead generation, brand engagement, competitor tracking |
| `/sales-sparktoro` | SparkToro — audience intelligence revealing where audiences spend attention (websites, podcasts, YouTube channels, subreddits, social accounts), persona development, channel discovery |
| `/sales-buzzsumo` | BuzzSumo — content intelligence, trending topics, content performance research, journalist database (700K+), influencer identification, REST APIs |
| `/sales-brandwatch` | Brandwatch — Consumer Intelligence (100M+ sources), Social Media Management, Influence, 6 REST APIs |
| `/sales-brandjet` | BrandJet AI — multi-channel outreach, brand monitoring, AI visibility monitoring, Artemis MCP, unified inbox |
| `/sales-buffer` | Buffer — simple per-channel social media publishing/scheduling across 11 networks (queue, drafts, analytics, Start Page link-in-bio); GraphQL developer API (Bearer key, plan-based rate limits) + deprecating legacy REST v1, **no webhooks**; no social listening; per-channel pricing |
| `/sales-later` | Later — social media scheduling, visual planner, Linkin.bio, analytics, Later Influence (influencer campaigns, Reporting API) |
| `/sales-vistasocial` | Vista Social — all-in-one social media management (15+ networks), unified inbox, analytics, social listening add-on, review management, DM automations, Zapier/Make |
| `/sales-sproutsocial` | Sprout Social — Publishing, Smart Inbox, Analytics, Social Listening, Influencer Marketing, Employee Advocacy, API |
| `/sales-social-media-management` | Social media management strategy — publishing, scheduling, engagement, analytics, tool comparison |
| `/sales-employee-advocacy` | Employee advocacy strategy — content curation, gamification, compliance, tool comparison |
| `/sales-social-listening` | Social listening strategy — brand monitoring, sentiment analysis, competitive intelligence, crisis detection |
| `/sales-snitchfeed` | SnitchFeed — intent-based social listening across Reddit, X, LinkedIn, Bluesky with AI relevance scoring, intent tagging, webhooks |
| `/sales-trigify` | Trigify — AI agent-powered LinkedIn signal intelligence with AI workflows, competitor engagement tracking, CRM integrations, outreach sequencing |
| `/sales-syncgtm` | SyncGTM — AI-native GTM data engine: buying signals (job changes/funding/hiring/LinkedIn/web traffic/custom AI), waterfall enrichment (verified emails/mobiles, 40+ providers), AI lead scoring (0–100 vs ICP), AI research agents, no-code Workflow Builder. MCP server (`api.syncgtm.com/mcp`, OAuth, works with Claude Code/Cursor) + REST API (`api.syncgtm.com`, API key) + webhooks + 40+ integrations (HubSpot/Salesforce/Slack/Attio); free tier incl. MCP, ~$99/mo |
| `/sales-mentiondrop` | MentionDrop — web+Reddit monitoring with AI summaries, sentiment, relevance scoring, read-only REST API, webhooks |
| `/sales-ai-visibility` | AI visibility monitoring — track brand mentions in ChatGPT, Claude, Perplexity, Gemini, AI Overviews |
| `/sales-media-relations` | Media relations strategy — journalist databases, PR pitching, press outreach, coverage tracking |

</details>

<details>
<summary><strong>Influencer Marketing</strong></summary>

| Skill | What it does |
|---|---|
| `/sales-infludata` | influData — creator discovery (20M+ profiles), audience analysis, campaign management, social listening |
| `/sales-creatorco` | Creator.co — AI-powered influencer marketing, London AI agent (400M+ profiles), UGC, affiliate tracking |
| `/sales-modash` | Modash — influencer marketing for Shopify, creator discovery (350M+ profiles), audience analysis, API |
| `/sales-influencity` | Influencity — all-in-one influencer marketing, Discover (200M+ profiles), IRM, Campaigns, Social Hub |
| `/sales-hypefy` | Hypefy — AI-native influencer marketing, zero-subscription/pay-per-campaign, content review, payments |
| `/sales-ltk` | LTK — creator commerce, Brand Platform, LTK Connect, LTK Ads, LTK Boost, LTK AI |
| `/sales-tagshop` | Tagshop.ai — AI UGC video ad generator (1000+ avatars), shoppable UGC galleries |
| `/sales-skeepers` | Skeepers — UGC suite (Verified Reviews, Influencer Marketing, Feedback Management, Brand Communities) |
| `/sales-heepsy` | Heepsy — influencer discovery (11M+ profiles), analytics, campaign marketplace, CRM, Shopify integration |
| `/sales-creatoriq` | CreatorIQ — enterprise influencer OS, Creator Graph (~20M profiles), SafeIQ, BenchmarkIQ, ExchangeIQ API |
| `/sales-afluencer` | Afluencer — micro-influencer marketplace, Collab listings, Shopify/BigCommerce gifting, invitation credits |
| `/sales-collabstr` | Collabstr — influencer and UGC creator marketplace, vetted creators, escrow payments, campaign posting |
| `/sales-cloutboost` | Cloutboost — gaming influencer marketing platform (1.5M+ creators), Portal discovery, campaign management, retargeting, PR |
| `/sales-houseofmarketers` | House of Marketers — TikTok-focused agency (50K+ creators), influencer campaigns, paid ads, content creation, strategy |
| `/sales-neoreach` | NeoReach — enterprise influencer marketing (3M+ creators), AI discovery, fraud detection, IMV analytics, REST API, managed services |
| `/sales-famesters` | Famesters — full-cycle influencer agency (gaming, fintech, iGaming, apps), 1000+ brands, BuzzGuru analytics |
| `/sales-inbeat` | inBeat — creative growth agency (influencer, UGC, paid media, performance creative), free marketing toolkit (calculators, ad mockups) |
| `/sales-hypeauditor` | HypeAuditor — AI-powered influencer analytics (223.6M+ profiles), fraud detection (53 patterns, 95%+ accuracy), Discovery, Campaign Management, Market Analysis, API |
| `/sales-aspire` | Aspire (formerly AspireIQ) — word-of-mouth commerce for influencer marketing, product seeding (Shopify), affiliate tracking, UGC sourcing, paid social (TikTok Spark Ads, Meta), 170M+ profiles |
| `/sales-influencer-hero` | Influencer Hero — all-in-one influencer marketing (200M+ profiles), AI-personalized outreach (email + DMs), CRM, affiliate tracking (code leakage prevention), product gifting, UGC capture, API |
| `/sales-instajet` | InstaJet.io — Instagram Stories influencer marketplace (10K+ vetted creators, 50+ countries), escrow payments, managed service |
| `/sales-openinfluence` | Open Influence — AI-powered influencer agency + SaaS (image recognition search, 20M+ keywords, Mood Board, paid media amplification, Studio OI, 50+ countries) |
| `/sales-viralnation` | Viral Nation — enterprise influencer agency + SaaS (CreatorOS campaign management, Secure AI brand safety, talent representation, 35+ verticals) |
| `/sales-upfluence` | Upfluence — influencer and affiliate marketing for ecommerce (12M+ profiles), Live Capture (find influential customers), Jaice AI, commission-free affiliate tracking, Shopify/WooCommerce/BigCommerce, creator payments |
| `/sales-grin` | GRIN platform help — creator management, discovery, gifting, affiliate hub, social listening, Gia AI |
| `/sales-trendhero` | trendHERO — Instagram influencer analytics (95M+ profiles), Account Quality Score (AQS) fake follower detection, Ads Database (10M+ posts), audience overlap, REST API |
| `/sales-passionfroot` | Passionfroot — AI-powered B2B creator marketing, Zest AI agent, creator discovery, storefronts, FrootWallet payments, cross-platform analytics |
| `/sales-plutoba` | PlutoBa — AI influencer vetting (TikTok, Instagram, YouTube), 7-dimension PlutoBa Score, fake follower detection, brand safety, rate benchmarks, AI outreach |
| `/sales-tiktok-marketing` | TikTok marketing strategy — organic growth, paid ads, content creation, influencer strategy, algorithm, metrics |
| `/sales-gaming-marketing` | Gaming influencer marketing strategy — streamer partnerships, game launch campaigns, budget allocation, ROI |
| `/sales-influencer-marketing` | Influencer marketing strategy — platform comparison, creator discovery, vetting, campaign tracking |

</details>

<details>
<summary><strong>Gaming Marketing</strong></summary>

| Skill | What it does |
|---|---|
| `/sales-cloutboost` | Cloutboost — gaming influencer marketing platform (1.5M+ creators), Portal discovery, campaign management, retargeting, PR |
| `/sales-famesters` | Famesters — full-cycle influencer agency (gaming, fintech, iGaming, apps), 1000+ brands, BuzzGuru analytics |
| `/sales-gaming-marketing` | Gaming influencer marketing strategy — streamer partnerships, game launch campaigns, budget allocation, ROI |

</details>

<details>
<summary><strong>Customer Experience & Feedback</strong></summary>

| Skill | What it does |
|---|---|
| `/sales-qualtrics` | Qualtrics XM — CX/EX surveys, Strategy & Research, Experience Agents AI, dashboards, XM Directory, REST API v3, MCP servers |
| `/sales-medallia` | Medallia — Experience Cloud, NPS/CSAT/CES surveys, DXA, contact center intelligence, employee listening, REST + GraphQL APIs |
| `/sales-frill` | Frill — affordable customer-feedback suite (Canny/Nolt/UserVoice alternative): feedback boards (voting/comments), public roadmap, changelog announcements, surveys, embeddable widget. REST API (api.frill.co/v1, Bearer key, cursor pagination via after/endCursor) for ideas/votes/statuses/topics/announcements; HMAC-SHA256-signed webhooks; Frill-Script (identify users, surveys) + SSO; 15+ integrations. ~$25/mo entry vs Canny ~$400 |
| `/sales-featureos` | FeatureOS (formerly Hellonext) — customer-feedback suite: feedback boards (posts a.k.a. `feature_requests` + voting/comments), roadmap (driven by post status), branded changelog, AI knowledge base, surveys, widget. Canny/Frill/Featurebase/Nolt alternative. REST API v3 (`api.featureos.app/api/v3`, `API-KEY: hn_…` header, `page`/`per_page`, 100 req/min) + OAuth 2.0 apps (`foapp_`/`foot_` tokens, scopes, app/self actor modes) + webhooks (post/changelog events, unsigned, return 200 or auto-disabled after 5m/30m/2h) + `HellonextWidget` embed with SSO. API gated to ~Growth tier; ~$60 Starter / ~$120 Growth / ~$250 Business |
| `/sales-feedbear` | FeedBear — budget customer-feedback suite (Canny/Nolt/Frill alternative): feedback boards (upvoting/comments/duplicate-merge), public roadmap, changelog, private ideas, AI-generated comments/replies, embeddable website widget. **No public pull/REST API** — automation is outbound webhooks (new idea/upvote/comment, JSON POST, no documented HMAC — secure by secret URL; payload schema unpublished, capture live), JWT SSO (`{BOARD}/sso/auth?payload={JWT}`, private key from Project Settings → SSO), Zapier (5,000+ apps), native Intercom/Slack/Trello/Jira. No free tier; $19 Lite / $49 Startup (webhooks+integrations) / $99 Business (SSO+private projects) / $299 Enterprise |
| `/sales-fourfour` | Four/Four — AI customer-research / voice-of-customer copilot (fourfour.ai): unifies conversations (calls/meetings/tickets/emails/chat) from 30+ sources into Insights/Topics with an AI Analyst, Workflows (Slack/Jira/email), competitive intelligence, churn signals. Developer surface: OData REST API (`/odata`, OAuth2 `api:read`, `@odata.nextLink` paging) + CRM Importer API (CSV, async jobs) + HMAC-SHA256-signed webhooks + MCP server (`fourfour.ai/mcp`). Usage-based, no per-seat — AI Analyst £199/mo, AI Researcher £250/mo, Enterprise custom |
| `/sales-noisely` | Noisely — AI feedback-tracking & product-intelligence: aggregates unsolicited feedback from 23+ sources (reviews/app stores/Reddit/HN/GitHub/support), AI categorization + sentiment + urgency/impact, clusters into ranked action items, spike detection; pushes to 10 channels (Slack/Linear/Jira/Notion/Sheets/Email/Webhooks). No public REST API (webhooks + CSV); AI-analysis credit limit (~2,000/mo Pro); Try $29 one-time / Pro $49/mo — affordable alternative to enterprise VoC tools |
| `/sales-sleekplan` | Sleekplan — AI customer-feedback suite (Canny/Frill/Featurebase alternative): feedback boards (voting/comments + AI auto-categorization & duplicate merging), roadmap, changelog, NPS/CSAT + in-app surveys; AI layer (Sleek Intelligence / Sleekmate). Developer surface: REST API (Bearer key from Settings → Developer, no public spec — full reference in-app) for posts/comments/votes/users/changelog/surveys/tags/topics; webhooks (secret GET-param verification, NOT HMAC-signed; `{product_id, action, data, timestamp}`); JWT SSO (HS256); `$sleek` widget SDK; **MCP server** (`mcp.sleekplan.com/mcp`, OAuth 2.1). API/SSO/integrations plan-gated — free Indie / $13 Starter / $38 Business |
| `/sales-userjot` | UserJot — AI-first customer-feedback suite (Canny/Productboard/Sleekplan/Frill alternative, **no per-seat pricing**, unlimited posts/users on every tier): feedback boards (voting/comments + AI duplicate detection + auto-categorization), public roadmap, AI changelog, in-app widget. Developer surface: REST API (`api.userjot.com/v1`, Bearer token) — Boards CRUD (`BoardColor` enum, names unique per org), feedback posts via `/requests`, `Idempotency-Key` on `/requests`+`/changelogs`, `409` = duplicate-or-quota, `429` + `Retry-After`; webhooks (payload/signing JS-rendered — capture live); **MCP server** (Claude Code/Cursor/Codex/ChatGPT/Windsurf); Widget SDK (`identify`) + Swift SDK (`UserJot/userjot-ios`); Slack/Linear/Discord. Integrations plan-gated — Free $0 (none) / $29 Starter (1) / $59 Professional (unlimited) |
| `/sales-rapidr` | Rapidr — product-feedback & feature-request suite for SaaS (Canny/Productboard/Frill/Featurebase alternative): public/private feedback boards (voting, proxy voting, duplicate merging, custom statuses, segmentation), public roadmap, changelog/release notes, embeddable widget, custom-domain portal. **No public REST/pull API** (G2: "Rapidr does not offer an API") — automation is JWT SSO (Secret Key from Company Settings → SSO, mint server-side from name+email, redirect to SSO endpoint, JWT debugger; Business-plan only), Zapier (realtime triggers + create/update actions; trigger names unpublished — confirm in editor), native Slack (`/rapidr` slash command + notifications)/Intercom/Jira/HubSpot, and voter CSV export. No free tier; $49 Startup / $199 Business (SSO + segmentation cliff) / Enterprise |
| `/sales-quickhunt` | Quickhunt — affordable all-in-one customer-feedback suite for SaaS (Canny/Frill/Featurebase/Upvoty alternative): feedback boards (ideas + upvoting/comments), public roadmap, changelog (scheduled), in-app messages (surveys/checklists/banners), knowledge base, AI assistant, live chat. **Genuinely free lifetime tier.** Most API-restrictive of the affordable boards: **REST API is Premium-only ($99/mo) and undocumented** (no `/docs`, no OpenAPI, no MCP server); integrations (Slack/Zapier/viaSocket/ClickUp/GitHub/HubSpot/Jira) are **Growth-tier ($49)** — Free/Starter have none; webhooks exist but have no published schema/HMAC (capture live). A feedback item's status drives its roadmap column. Free / Starter $29 / Growth $49 / Premium $99; +$10/mo per extra seat |
| `/sales-productlane` | Productlane — AI-native customer support + product-feedback suite **built exclusively on Linear** (Canny/Cycle/Productboard alternative for Linear teams): omnichannel inbox (email/live chat/Slack Connect/MS Teams/Discord), AI Agent, self-updating help center, feedback portal, public roadmap (= Linear projects), changelog whose **Release Intelligence** auto-drafts release notes from completed Linear issues. Hard Linear dependency — no standalone mode. Developer surface (unlike Rapidr/Quickhunt): **documented REST API** (`productlane.com/api/v1`, `Authorization: Bearer`, key from `/settings/api`) for **Companies / Customers** (`name`/`email`/`segments[]`) / **Insights** (`text`+`painLevel` `UNKNOWN\|LOW\|MEDIUM\|HIGH`+`customerEmail`) / **Portal** (`getprojects`/`getprojectupvotes`/`listchangelogs`/`upvoteproject`); a **public no-auth `POST /api/v1/feedback`** for widgets (workspaceId+text+painLevel+email — protect it); Zapier "Create Note" action (Scale); **no MCP server**; own webhooks undocumented (use Linear webhooks/polling). Per-user, **no free tier** (7-day trial) — Starter ~$15 (portal/roadmap/changelog) / Pro ~$29 (support inbox + AI changelog) / Scale ~$79 (SSO/JWT, custom domain, white-label, private portals, HubSpot+Zapier) |
| `/sales-userback` | Userback — visual customer-feedback + bug-reporting platform for SaaS/product teams (userback.io): in-app widget capturing annotated screenshots/video + auto-captured console logs/network requests/device metadata + session replay, plus feature-request boards, public roadmap, Feature Portal, and surveys. Differentiator over board-only tools (Canny/Frill) is reproducible visual bug capture; vs QA-focused Marker.io/BugHerd/Usersnap it adds voting/roadmap in one tool. Developer surface: **documented REST API** (`rest.userback.io/1.0`, `authorization: Bearer`, token from Workspace Settings) for Feedback / Comments / Screenshots / Projects / Members / Session Recordings / Workflows (page+limit max 50, OData `filter`/`sort`); webhooks (feedback + comment events, `User-Agent: Userback-Webhook`, **no documented HMAC** — unsigned); a **~12-tool MCP server** (`mcp.userback.io/v1/mcp/`, OAuth); JS `@userback/widget`/React/Vue/Next/Angular SDKs (`identify`/`setData`/`openForm`/`openSurvey`) + iOS/Android. **Integration cliff: REST API + webhooks + mobile SDK are Business Plus; session replay/surveys/SDK are Business; Zapier is Team.** Free $0 (2 projects, 7-day retention) / Team $7 / Business $15 / Business Plus $23 per seat; Roadmap/Feature Portal add-on $31–$39/mo |
| `/sales-surveymonkey` | SurveyMonkey — survey creation, skip logic, email/SMS/web collectors, analytics, cross-tabulation, Audience panel, REST API v3 |
| `/sales-gainsight` | Gainsight — CS health scores, CTAs, playbooks, success plans, Journey Orchestrator, PX in-app engagement, Staircase AI, Skilljar, REST API |
| `/sales-vitally` | Vitally — AI-powered CS platform, Health Scores, Playbooks, Projects, Automation, AI copilot, NPS, REST API |
| `/sales-planhat` | Planhat — Agentic Customer Platform, Health Scores, Revenue Management, CRM Sync, Automation, MCP Server, REST API |
| `/sales-churnzero` | ChurnZero — Health Scores, Plays & Automation, Journeys, Renewal Hub, In-App WalkThroughs, Surveys, AI Agents, OData v4 API |
| `/sales-totango` | Totango — SuccessBLOCs, SuccessPlays, Health Scores, Customer 360, Customer Data Hub, Unison AI, Catalyst, REST API |
| `/sales-customer-success` | Customer success strategy — health scores, churn prevention, onboarding, expansion, CS platform comparison |
| `/sales-customer-feedback` | Customer feedback, NPS, CSAT, VoC strategy — survey design, response rates, closed-loop feedback, tool comparison |

</details>

<details>
<summary><strong>Customer Reviews & UGC</strong></summary>

| Skill | What it does |
|---|---|
| `/sales-g2` | G2 — B2B software review marketplace, review campaigns, Buyer Intent data, badges/reports, profile optimization, API |
| `/sales-trustpilot` | Trustpilot — TrustBox widgets, TrustScore, review invitations, Google Seller Ratings, ecommerce plugins, API |
| `/sales-birdeye` | Birdeye — reviews, listings, social, messaging, surveys, referrals, payments, BirdAI for multi-location |
| `/sales-online-reputation` | Online reputation management strategy — review generation, response, listings, Google Business Profile, crisis response |
| `/sales-customer-reviews` | Product review collection, display, moderation, syndication — Judge.me, Loox, Okendo, Yotpo, Bazaarvoice |

</details>

<details>
<summary><strong>Launch Directories</strong></summary>

| Skill | What it does |
|---|---|
| `/sales-producthunt` | Product Hunt — largest launch platform (DR91 dofollow, 5M+ visits/mo), Pro/Super Pro, GraphQL API |
| `/sales-betalist` | BetaList — pre-launch directory (DR67 dofollow, 30K+ newsletter), free or $129 Priority |
| `/sales-indiehackers` | Indie Hackers — largest founder community (165K+ entrepreneurs), DR75 nofollow |
| `/sales-peerlist` | Peerlist — professional network, weekly Launchpad, portfolio profiles, DR76 nofollow |
| `/sales-fazier` | Fazier — product discovery (DR81 dofollow), free/$19 Lite/$39 Premium/$99 Super |
| `/sales-uneed` | Uneed — social launchpad (DR74 dofollow), skip-the-line $29.99, Pro $89/yr |
| `/sales-tinylaunch` | TinyLaunch — weekly launches (DR60-71 dofollow for Top 3), $39 premium launch |
| `/sales-devhunt` | DevHunt — developer tool launches (DR57-62 dofollow), $49 featured |
| `/sales-openlaunch` | Open Launch — open-source PH alternative (DR65 dofollow), $12 Premium, $59 SEO Growth |
| `/sales-microlaunch` | MicroLaunch — month-long launch cycles, DR59+ dofollow, Pro Launch $39/mo |
| `/sales-tinystartups` | Tiny Startups — curated directory (DR50 dofollow), 17,500+ newsletter subscribers |
| `/sales-superlaunch` | Super Launch — 7 days on front page, DR59 paid dofollow, $49/mo advertising |
| `/sales-sideprojectors` | SideProjectors — project marketplace (DR69 dofollow), 24,600+ listings |
| `/sales-acquire` | Acquire.com — curated SaaS marketplace (formerly MicroAcquire), 500K+ verified buyers, $500M+ closed deals, NDA-gated listings, Escrow.com integration |
| `/sales-flippa` | Flippa — largest open marketplace since 2009 (SaaS, ecom, content, apps, domains), 39,805+ sold, tiered listing packages $29-$699, 3-10% success fees, auto-verification above $50K |
| `/sales-trustmrr` | TrustMRR — verified-revenue startup marketplace by Marc Lou, live Stripe/LemonSqueezy/Polar/Paddle/RevenueCat/Superwall/Creem/DodoPayment API verification (hourly), APA-only single-lump-sum deals via Escrow.com, Starter $29 / Growth $199 / Scale $499 boost tiers, 3% marketplace fee + escrow, public REST API |
| `/sales-ecomswap` | Ecomswap — boutique sell-side M&A advisory for profitable Shopify/FBA/DTC/SaaS/newsletter/content exits, $200K net-profit floor, SDE-based profit multiples, 50K+ pre-qualified buyer network with $2B+ capital, curated private listings, advertised 93% close rate / <2 month time-to-exit |
| `/sales-startupage` | StartuPage — founder-ecosystem platform (founded 2024), Stripe/LemonSqueezy/Polar/RevenueCat/Dodo-verified MRR leaderboard (Top Startups / Top Founders), founder + startup sub-page profiles, 4-track Opportunities marketplace (hiring / fundraising / co-founder / acquisitions), Free / Starter $5/mo / Growth $9/mo / Lifetime $179 |
| `/sales-arrfounder` | Arrfounder — social-proof founder-revenue directory (founded 2024 by @Folyd), 1000+ founders and 1500+ products auto-extracted from Twitter/X bios via AI, sortable leaderboards (ARR / followers / products / recently added), free Airtable submission with 24-48h manual approval, not a marketplace, no payment-provider API verification — complements TrustMRR / StartuPage |
| `/sales-side-project-valuation` | Side project valuation & sale strategy — pricing, revenue multiples, deal structuring, marketplace selection (Acquire.com, Flippa, TrustMRR, Ecomswap, StartuPage, 1Kprojects, Microns, Empire Flippers) |
| `/sales-launchingnext` | LaunchingNext — curated directory (DR51 dofollow, 45K+ startups), $149 Express |
| `/sales-pitchwall` | PitchWall — AI product directory (DR60, 65K+ products), free/$99 Premium |
| `/sales-futurepedia` | Futurepedia — largest AI tools directory (5,700+ tools, ~2M visits/mo), $247/$497 |
| `/sales-theresanaiforthat` | TAAFT — #1 AI tools directory (42,000+ tools, 3-4M visits/mo, DR76 dofollow), $347 listing, $300 first-launch PPC bonus |
| `/sales-topai` | TopAI.tools — curated AI tools directory (2,700+ tools, ~1-1.9M visits/mo), $39 Fast Track, $229 Boosted |
| `/sales-toolify` | Toolify.ai — largest AI tools directory by tool count (26K+ tools, 450+ categories, ~2-5M visits/mo), $49-99 listing, 6+ dofollow backlinks |
| `/sales-startupstash` | Startup Stash — curated tool directory (10K+ tools, DR65 nofollow) |
| `/sales-productburst` | ProductBurst — daily/weekly rankings (DR46 dofollow), no gatekeepers |
| `/sales-solopush` | SoloPush — indie maker launches (DR46-47 dofollow), free instant listing |
| `/sales-ctrlaltcc` | CtrlAlt.cc — startup tool directory (DA30 dofollow), $39 paid launch |
| `/sales-huzzler` | Huzzler — weekly launch competition, dofollow for winners only, Huzzler Black $79 |
| `/sales-firsto` | Firsto — fair launch platform (DR57+ dofollow), $19.90 Premium, $59.90 Pro |
| `/sales-openhunts` | OpenHunts — weekly Monday launches (DR50 dofollow), $9.90 Premium |
| `/sales-awesomeindie` | Awesome Indie — curated directory, free only, editorial review |
| `/sales-launchday` | LaunchDay — curated 24-hour events ($99), podcast interview, influencer promotion |
| `/sales-justgotfound` | JustGotFound — community-curated (DR23 dofollow), paid promotion $50-$500 |
| `/sales-launchcaster` | LaunchCaster — Web3 project discovery on Farcaster, wallet-connected voting |
| `/sales-saashunt` | SaaSHunt — AI-powered SaaS directory (DR49 dofollow), template-based submission |
| `/sales-resourcefyi` | Resource.fyi — curated tools directory (2,519+ resources), free submission |
| `/sales-launchvibe` | LaunchVibe — instant free submission (DR10 dofollow), XP gamification |
| `/sales-startupbase` | StartupBase — community-driven directory (DR39 dofollow), Spark newsletter |
| `/sales-getmorebacklinks` | GetMoreBacklinks — managed directory submission service ($87-$247), 50-200 directories, DR 30+ guarantee |
| `/sales-listingbott` | ListingBott — AI done-for-you directory submission service for launching startups: 100+ curated directories from a 10,000+ database, gradual ~4-5 week paced rollout, approve/decline review, duplicate detection, DR 0→15 guarantee; no API/dashboard (email-driven managed service), ~$299-999 per website |
| `/sales-directory-submission` | Directory submission service comparison — managed vs automated vs DIY, 7 services compared |
| `/sales-launch-directory` | Launch directory strategy — coordinates submissions across 22+ platforms, sequencing, backlink stacking |

</details>

<details>
<summary><strong>SEO & Visibility</strong></summary>

| Skill | What it does |
|---|---|
| `/sales-seo` | SEO strategy — tool selection, keyword research, technical audits, link building, WordPress plugin comparison, local SEO, AI visibility |
| `/sales-semrush` | Semrush — leading SEO platform (27B keywords, 43T backlinks), AI Visibility Toolkit, MCP server, API |
| `/sales-ahrefs` | Ahrefs — industry-leading SEO toolset (Site Explorer/backlinks, Keywords Explorer, Rank Tracker, Site Audit, Brand Radar AI visibility); REST API v3 (`api.ahrefs.com/v3`, Bearer, metered API units, v2 discontinued 2025-11-01) + official MCP server (Lite+); credit/unit model, no free trial, no affiliate program |
| `/sales-yoast` | Yoast SEO — WordPress/Shopify SEO plugin (13M+ installs), content analysis, readability, schema, REST API, AI meta, llms.txt |
| `/sales-serplock` | Serplock — AI search visibility with Prompt Rank, Brand Wiki, Topic Graph, Content Engineering, Reddit Mentions add-on |

</details>

<details>
<summary><strong>Loyalty</strong></summary>

| Skill | What it does |
|---|---|
| `/sales-loyaltylion` | LoyaltyLion — points, tiers, rewards, referrals, AI recommendations, Klaviyo Events, Shopify POS, API |

</details>

<details>
<summary><strong>Funnels, Email Marketing & Digital Sales</strong></summary>

| Skill | What it does |
|---|---|
| `/sales-funnel` | Build and optimize sales funnels — strategy, structure, conversion, A/B testing |
| `/sales-email-marketing` | Opt-in email marketing — broadcasts, nurture sequences, automation, segmentation |
| `/sales-newsletter` | Newsletter monetization — paid subscriptions, sponsorships, ad sales, premium tiers |
| `/sales-paved` | Paved — newsletter sponsorship marketplace, Ad Network, Booker direct-deal management, Radar lead enrichment |
| `/sales-reletter` | Reletter — newsletter search engine, 7M+ publications, subscriber data, creator contacts, keyword monitoring, Python SDK, MCP server |
| `/sales-sponsorgap` | SponsorGap — newsletter sponsorship intelligence, 38K+ brand database, verified contacts, competitor monitoring, spend trends, API |
| `/sales-sponsorleads` | SponsorLeads — curated Airtable database of newsletter sponsors, 4,318+ companies, decision-maker contacts, weekly new leads |
| `/sales-sponsy` | Sponsy — newsletter sponsorship operations, ad inventory calendar, sponsor CRM, customer portals, automated reporting, Zapier |
| `/sales-whosponsorsstuff` | Who Sponsors Stuff — newsletter sponsor intelligence, 8,000+ sponsors across 500+ newsletters, ad creative screenshots, decision-maker contacts, email alerts |
| `/sales-openrates` | Open Rates — newsletter sponsor prospecting database, 10,000+ active sponsors, decision-maker contacts, niche filtering |
| `/sales-adbutler` | AdButler — full-stack ad server, display/video/mobile/native/email ads, self-serve advertiser portal, programmatic SSP, REST API + MCP server |
| `/sales-epom` | Epom — hosted ad server + white-label DSP, direct and programmatic ads, 40+ analytics metrics, REST API included, RTB free for publishers |
| `/sales-broadstreet` | Broadstreet — ad manager for local news and B2B publishers, direct-sold newsletter ad zones, sponsored content tracking, automated PDF reports, WordPress plugin, REST API |
| `/sales-adplugg` | AdPlugg — budget ad server + ad manager, WordPress/Ghost/Drupal plugins, email newsletter ad tags, ad rotation, scheduling, A/B testing |
| `/sales-revive` | Revive Adserver — free open-source self-hosted ad server, email/newsletter zones, geo-targeting, frequency capping, XML-RPC API, multi-advertiser management |
| `/sales-adglare` | AdGlare — cloud-based ad server, display/native/VAST video/CTV/catalog ads, cookieless targeting, 220+ CDN nodes, REST API v2 (Enterprise only) |
| `/sales-adspeed` | AdSpeed — affordable hosted ad server, email newsletter zones, display/video/mobile ad serving, REST API with MD5 auth, sliding-scale pricing from $9.95/mo |
| `/sales-adserver-online` | Adserver.Online — cloud-hosted ad server for ad networks, display/video/native/email/programmatic ad serving, OpenRTB/Prebid, multicurrency bidding, retargeting, white-label, REST API v2, from $49/mo |
| `/sales-advertserve` | AdvertServe — feature-rich hosted ad server since 1998, display/video/mobile/email ad serving, 101-tier zones, header bidding via Prebid.js, weather targeting, white-label, 17-module REST API, from $299/mo |
| `/sales-lettergrowth` | Lettergrowth — free newsletter cross-promotion directory, 1,300+ newsletters, search by category/size/recency, partner discovery for swaps |
| `/sales-collabmatch` | Collab Match — niche newsletter cross-promotion matching directory, ~200 newsletters across Business/Tech/Health/Web3, public per-newsletter profile pages, weekly matching, free |
| `/sales-inboxreads` | InboxReads — premium newsletter directory + growth platform, 5,600+ newsletters across 40+ topics, 1-click cross-promo swaps, Opportunities Board sponsorship marketplace, Live Media Kits, ad pricing suggestions, free/$8-58/mo |
| `/sales-mutualgro` | MutualGro — UK-based creator collaboration platform, AI-powered partner matching, scheduled X/LinkedIn posting, partnership intelligence dashboard, accepts non-newsletter projects (newsletter + indie SaaS + creator collabs), free/£3.99/mo |
| `/sales-referralkit` | ReferralKit — no-code newsletter referral program by Copyhackers (referralkit.co), milestone-based rewards Morning Brew / The Hustle style, merge-tag unique-link insertion into email body, native Mailchimp/Kit/MailerLite/AWeber integrations, 100% free for first 10K leads |
| `/sales-referralhero` | ReferralHero — full-stack referral / affiliate / waitlist / contest / NPS platform, REST API + webhooks (PRO+), Zapier 500+ apps, 6 native ESPs (Mailchimp/Kit/AWeber/Klaviyo/ActiveCampaign/SendLane), multi-level referrals (L1/2/3), coupon groups, anti-fraud + ReCaptcha + SMS Verification, PRO $199/mo (10K) and PREMIUM $399/mo (50K) |
| `/sales-viral-loops` | Viral Loops — referral & viral-marketing campaign builder (templates for referral programs, pre-launch waitlists, giveaways, milestone/Robinhood-style referrals, ambassador leaderboards) + embeddable widget; REST API (`app.viral-loops.com/api/v3`, per-campaign `publicToken`, `POST /campaign/participant` with `referrer` attribution) + webhooks (participant/referral-count/convert/reward, no documented HMAC) + two-way Zapier; scales by participants (Build ~$49/mo, Accelerate ~$229/mo) |
| `/sales-rafflepress` | RafflePress — WordPress giveaway & contest plugin (by Awesome Motive) for viral list growth: drag-and-drop builder, 30+ bonus-entry actions, refer-a-friend (+10 entries), hosted landing pages, winner picker, fraud protection. WordPress-only (no REST API); automation via outbound webhooks (JSON/FORM, fields fullname/email/giveaway_id/sign_up_date, no HMAC, social-action data NOT sent), Zapier "New Contestant Created" trigger, 15+ native ESPs, Uncanny Automator, WP hooks + URL prefill; free Lite + one-time Pro (~$299 single / ~$349 unlimited) |
| `/sales-shortstack` | ShortStack — standalone SaaS campaign platform for contests, giveaways, sweepstakes, quizzes, refer-a-friend, instant-win, landing pages + social promos, with lead capture, auto winner selection, analytics. Entries API (`entries.shortstack.com`, `Authorization: Token token=`, per_page ≤5000, `{data:[...]}`) + SIGNED real-time webhooks (`X-Ss-Signature` HMAC of body+secret) + Webhooks management API + native Mailchimp/HubSpot/Salesforce + Zapier; free-forever plan + paid tiers |
| `/sales-referral-factory` | Referral Factory — no-code referral program builder (100+ branded templates: single/double-sided, invite-only, refer-to-win), reward issuing (cash/gift cards/Stripe/commissions, no direct bank payout); clean REST API (`api.referral-factory.com/api/v2`, Bearer, one token/account) — `POST /users` with `referrer` attribution, `PUT /users/qualification` to make a reward due, `/rewards/issue|cancel`; in/outbound webhooks (no documented HMAC) + native HubSpot/Salesforce/Stripe/Zapier/Make/n8n; scales by users (Basic ~$200/Pro ~$400/Enterprise ~$1,000, white-label/custom domain Pro+) |
| `/sales-kickofflabs` | KickoffLabs — viral marketing for pre-launch waitlists / bonus-entry giveaways / milestone rewards / leaderboard giveaways, REST API v1 + v2, server-side webhooks with `__fraudulent` flags (duplicate_ip / bounced / duplidate_email), AnyForm + KOL.js, native ESPs (Klaviyo/Mailchimp/ActiveCampaign/Brevo), Hobby $13/mo to Enterprise $202/mo annual |
| `/sales-upviral` | UpViral — viral referral marketing / list-building for sweepstakes, giveaways, pre-launch waiting lists, milestone referral programs; REST API (`app.upviral.com/api/v1/`, `uvapikey`+`uvmethod`) + Callback-URL webhooks gated to Business+, IP-based fraud detection, A/B testing, 30+ ESP/CRM integrations; Starter $79/mo (no API) to Premium $319/mo annual |
| `/sales-launchlist` | LaunchList — viral pre-launch waitlist with one-time lifetime pricing (Free 100 / Launch $29 / Grow $79 / Scale custom), gamified referrals + position inflation, form POST endpoint + `new_user`/`email_verify` webhooks + Zapier (Grow+), spam protection with disposable-email blocklist + `_gotcha` honeypot; no public REST API (roadmap-planned) |
| `/sales-waitlister` | Waitlister — pre-launch waitlists with built-in email broadcasts, hosted + AI landing pages, points-based referrals; REST API + 5 HMAC-signed webhook events (Growth $49/mo+), unlimited subscribers from $15/mo, native Klaviyo/Mailchimp/Kit sync, no Zapier |
| `/sales-getwaitlist` | GetWaitlist — developer-friendly pre-launch waitlist + referral widget; embeddable widget + 13 no-code embeds, priority queue, censored leaderboard, REST API from Basic $15/mo (unauthenticated `POST /signup`) + `new_signup`/`offboarded_signup` webhooks; no free tier for new accounts (Basic $15 / Advanced $50 / Pro $250) |
| `/sales-waitlistly` | Waitlistly — validation-first hosted pre-launch waitlist landing pages ("fastest way to validate your idea"), custom domains, on-signup webhooks → Zapier/Make/Slack/your own API; free to start (no public pricing page), no public REST API and capture-only (launch emails go through your ESP) |
| `/sales-referlist` | Referlist — cheap, landing-page-agnostic no-code waitlist with gamified Dropbox/Robinhood-style referrals (place in line + unique link); 5 install methods incl. `referlist` npm SDK (React/Next.js) and REST API on Pro; Mailchimp/Airtable/CSV export, seeding; Free 100 / Growth $29 / Pro $59 / Enterprise usage-based; no confirmed webhooks/Zapier |
| `/sales-tuemilio` | Tuemilio — early-access waitlist + pre-launch validation with a viral referral loop, leaderboards, white-labeled dashboards, and a full developer trio (REST API `tuemilio.com/api/v1` `?api_token=` server-side, JS SDK for the browser, `new-subscriber`/`grant-access`/`confirmed-subscriber` webhooks); Zapier/Mailchimp/Typeform/GA; API+webhooks on all tiers, Founder $29 / Startup $49 / Enterprise |
| `/sales-refind` | Refind — CPA-based newsletter ad network, 488K curated readers, pay only for engaged subscribers, free cross-promotion, publisher earning |
| `/sales-sponsorthis` | Sponsor This Newsletter — curated Airtable database of 530+ newsletters accepting sponsorships, ad pricing, cross-promotion/affiliate indicators, one-time purchase |
| `/sales-adslots` | Ad Slots — calendar-based newsletter ad management, Stripe invoicing, sponsor CRM dashboard, AI ad copy generation, free/$49/mo |
| `/sales-jeeng` | Jeeng (OpenWeb) — AI-powered multi-channel ad monetization for email publishers, AdFill/AdServe/AdMarket, 150M+ opt-in subscribers, GAM integration, push + newsreader |
| `/sales-moosend` | Moosend — budget email marketing, drag-and-drop campaigns, automation workflows, ecommerce AI product recommendations, REST API |
| `/sales-sender` | Sender — budget email marketing with generous free tier, automation workflows, SMS, landing pages, transactional email, REST API |
| `/sales-constantcontact` | Constant Contact — email marketing with event management, drag-and-drop campaigns, automation, social posting, SMS, V3 REST API |
| `/sales-admailr` | Admailr — programmatic email ad server, automated ad insertion, CPM+CPC, campaign management REST API, ESP integrations |
| `/sales-passendo` | Passendo — European email ad server + SSP, programmatic exchange, direct-sold campaigns, 15+ demand partners, CNAME integration |
| `/sales-kevel` | Kevel — API-first ad server infrastructure, build custom ad platforms, Decision API, email ad serving, retail media networks |
| `/sales-adlynews` | adly.news — two-sided newsletter advertising marketplace, verified ESP metrics, bidding/negotiation, campaign recruitment |
| `/sales-hecto` | Hecto — self-serve newsletter advertising marketplace, transparent pricing, direct creator messaging, inventory management |
| `/sales-megahit` | Megahit — B2B newsletter subscriber enrichment, LinkedIn data (job titles, employers, profiles), sponsor decision-maker identification, ESP integrations |
| `/sales-buysellads` | BuySellAds — contextual advertising marketplace for websites, newsletters, and podcasts, Ad Serving API, Advertiser API, Carbon Ads, Zapier |
| `/sales-socialpresence` | Social Presence — AI-powered newsletter advertising marketplace, discovery dashboard, Ad Library competitor monitoring, managed sales, publisher storefronts |
| `/sales-postapex` | PostApex — email newsletter ad network, 500+ publishers, CPC revenue model, native ads, 50+ categories, free for publishers |
| `/sales-ohmynewst` | OhMyNewst — newsletter sponsorship marketplace for Spain & LATAM, 400+ newsletters, 50+ categories, zero advertiser fee |
| `/sales-substack` | Substack — newsletter publishing, paid subscriptions, Notes, discovery network, custom domains, podcast, migration |
| `/sales-listmonk` | Listmonk — open-source self-hosted newsletter, mailing list manager, transactional email, multi-SMTP, REST API |
| `/sales-sparkloop` | SparkLoop — newsletter referral programs, paid recommendations, partner programs, cross-promotion, Upscribe widget, API |
| `/sales-audience-growth` | Grow an email list or newsletter audience — lead magnets, cross-promotion, referral programs |
| `/sales-digital-products` | Sell digital products — ebooks, templates, courses, downloads, pricing strategy |
| `/sales-affiliate-program` | Design and manage affiliate programs — commissions, recruitment, tracking, payouts |
| `/sales-performcb` | Perform[cb] — #1 CPA network, Outcome Engine AI optimization, PerformSHIELD fraud detection, Partner API |
| `/sales-fansrevenue` | FansRevenue — creator monetization through affiliate brand promotion, MyEroLink, Creator Academy, CrakRevenue network |
| `/sales-webinar` | Webinar-based selling — live and evergreen strategy, presentation, follow-up |
| `/sales-podia` | Podia — courses, downloads, memberships, coaching, webinars, email, communities, affiliates |
| `/sales-payhip` | Payhip — digital downloads, courses, memberships, coaching, store builder, affiliates, API |
| `/sales-gumroad` | Gumroad — digital products, subscriptions, license keys, Discover marketplace, email broadcasts, affiliates, API |
| `/sales-sellfy` | Sellfy — creator storefront for digital products, print-on-demand merch, physical goods, and subscriptions; 0% platform fee with **annual sales-volume caps** (~$10k/$50k/$200k) that force upgrades; PDF stamping + download limits; Stripe/PayPal only; upselling/cart-abandonment/affiliates gated to Business+; **no public REST API** — automate via outbound webhooks (New Order/Subscription/Cart Abandoned, JSON POST in cents, **no HMAC**) + a Zapier API token; not a Merchant of Record |
| `/sales-printful` | Printful — print-on-demand (POD) merch fulfillment for creators/brands (apparel, accessories, all-over print, no inventory); store connectors (Shopify/WooCommerce/Etsy/Wix) + headless **REST API v2 beta + v1** (`api.printful.com/v2`, OAuth/Bearer, leaky-bucket 120 req/60s); mockup generator + 19 **signed** webhook events; order by `catalog_variant_id`, async cost calc before confirm; Free vs Growth ($24.99/mo, free above $12K/yr); community MCP server; not a Merchant of Record |
| `/sales-customcat` | CustomCat — **budget US (Detroit) print-on-demand** for creators/sellers (apparel, drinkware, home décor via DIGISOFT DTG/DTF, embroidery, dye sublimation); lowest base prices + **1–3 day production**, but **no private-label branding** and **US-only** fulfillment; store connectors (Shopify/Etsy/WooCommerce/BigCommerce) + headless **REST API v1** (`customcat-beta.mylocker.net/api/v1`, **read-only + read-write keys**, `403` on read-only write); `order_id` idempotency, **6 unsigned webhook topics** (`order-shipped`…) + `/order/status` polling backup; Lite ($0, standard wholesale) vs Pro ($30/mo, 20–40% off) vs Enterprise; not a Merchant of Record |
| `/sales-lemonsqueezy` | Lemon Squeezy — payments, subscriptions, tax compliance (MoR), license keys, checkout, email, affiliates, API |
| `/sales-paddle` | Paddle — Merchant of Record billing for SaaS/apps (checkout, subscriptions, global sales-tax/VAT remittance, B2B invoicing, Retain, ProfitWell); Paddle Billing REST API (`api.paddle.com`, Bearer, sandbox) + HMAC-SHA256 webhooks + Docs MCP; Classic≠Billing; ~5%+$0.50 |
| `/sales-dodo-payments` | Dodo Payments — developer-first Merchant of Record for SaaS/AI/digital products: global tax/VAT/GST across 220+ countries, subscriptions + usage/credit billing, checkout, license keys. Full REST API (`test/live.dodopayments.com`, Bearer) for payments/subscriptions/products/customers/checkout/license-keys/refunds/payouts + Standard-Webhooks-signed events, 9 SDKs, framework adapters, CLI + MCP server; ~4% + $0.40/txn, no monthly fee |
| `/sales-merchant-of-record` | Merchant of Record / payments-provider selection — MoR vs self-managed Stripe, and Paddle vs Lemon Squeezy vs Polar vs Creem vs Gumroad on fees, tax coverage, B2B support, and switching cost |
| `/sales-subscription-billing` | Recurring-billing engine selection & operation — Chargebee vs Recurly vs Maxio vs Zuora vs Stripe Billing vs Orb vs Lago vs Zoho Billing; subscription-first vs usage-first, build-on-Stripe vs dedicated, open-source self-host (Lago), dunning/proration/revenue recognition (ASC 606); stay seller of record, keep tax in-house (NOT a Merchant of Record) |
| `/sales-chargebee` | Chargebee — subscription-billing & revenue-management engine on your own gateway (NOT a Merchant of Record); REST API v2 (`{site}.chargebee.com/api/v2`, HTTP Basic key-as-username/empty password, form-encoded, offset pagination, idempotency header) + webhooks with **no HMAC** (basic-auth/secret-URL/IP-allowlist, dedupe on event id, order by resource_version) + AgentKit MCP server; Product Catalog 1.0↔2.0 split, Smart Retry dunning, proration, RevRec/Retention add-ons; free Starter cumulative $250K cap → 0.75% overage |
| `/sales-membervault` | MemberVault — "binge & buy" course/membership marketplace, gamification (Engagement Points), warm/hot lead tagging, 0% fees; no REST API — Zapier (Hot Lead trigger) + inbound/outbound webhooks; bring your own ESP |
| `/sales-graphy` | Graphy (formerly Spayee) — all-in-one courses, memberships, communities, coaching, webinars + no-code branded mobile apps; REST API on top plan (MID + key) + 9 webhook triggers (auto-disable after 5 failures), Zapier/Pabbly |
| `/sales-memberful` | Memberful — membership + paid-subscription layer (Patreon-owned) for creators/publishers/communities: gated content, private podcasts, newsletters, downloads, OAuth SSO, all on your own Stripe. GraphQL API (`ACCOUNT.memberful.com/api/graphql`, Bearer key, cursor pagination; members/subscriptions/passes/plans/coupons) + 21 HMAC-SHA256-signed webhooks (`X-Memberful-Webhook-Signature`); WordPress/Discord/Mailchimp/Kit. Free 10% / Pro $25 4.9% fees |
| `/sales-memberstack` | Memberstack — no-code membership, auth (login/2FA/social), and Stripe payments + content gating for Webflow/WordPress/custom sites; Admin REST API (`admin.memberstack.com`, X-API-KEY, member CRUD, verify-token, 25 req/s) + 8 webhooks + DOM package |
| `/sales-groupapp` | GroupApp — learning-focused community platform: communities + deep LMS (curriculum builder, branded certificates), events, B2B group subscriptions, 0% fees; API token + webhooks + OAuth + Zapier (11 triggers/10 actions) |
| `/sales-ruzuku` | Ruzuku — simple teaching-first course/membership platform (drag-and-drop builder, drip, live/cohort courses via Zoom, certificates), direct Stripe/PayPal at 0% fees; no public REST API — Zapier only (7 triggers/3 actions; certificates/white-label/storefront gated to Pro) |
| `/sales-xperiencify` | Xperiencify — gamified course platform built to drive completion (Experience Engine: XP/XXP points, badges, leaderboards, variable rewards, countdowns); REST API (`api.xperiencify.io`, `?api_key=`, ~18 endpoints incl. redeem/unredeem points) + Zapier (4 triggers/8 actions) + webhook export; billed by active monthly students; affiliate tracking but no payout dashboard |
| `/sales-zenler` | New Zenler — live-session-first all-in-one course/membership platform (built-in interactive webinars/live classes, funnels, email, 0% fees, multi-instructor); REST API (`api.newzenler.com/api/v1`, `X-API-Key` + `X-Account-Name` headers, ~25 endpoints, 1000/min) + Zapier (7 triggers/7 actions) + Make; no native webhooks; API/memberships/affiliate/white-label are Pro-gated |
| `/sales-freshlearn` | FreshLearn — budget all-in-one LMS/creator platform (unlimited learners, 0% fees, deep AI Studio for course creation/chat-with-content/coaching); REST API (`api.freshlearn.com/v1`, `api-key` header, cursor pagination) + native webhooks + Zapier (6 triggers/9 actions, enroll upserts); API/workflows gated to No Brainer+, Zapier/community to No Brainer |
| `/sales-teachery` | Teachery — minimalist, design-first course builder (flat-rate, 0% fees, unlimited courses/students, custom-CSS Payment Pages); no public REST API — Zapier (3 triggers/4 actions: enroll/revoke Course or Theme) + Make/Pabbly; no native video hosting (embed-only), no quizzes/multi-instructor; built-in course affiliate feature |
| `/sales-membership` | Membership sites and online courses — structure, pricing, retention |
| `/sales-thrivecart` | ThriveCart — lifetime-license checkout/cart for creators (order bumps, 1-click upsells/downsells, A/B testing, dunning, Affiliate Center); event-driven webhooks + Event Subscription API + REST (token/OAuth, 60/min, PHP SDK), secret-validated (no HMAC); Pro+ $295/yr gating; Learn deprecated; no download protection |
| `/sales-shopify` | Shopify — the leading commerce platform for makers/DTC (products, orders, customers, checkout, discounts, headless); GraphQL Admin API (`{store}.myshopify.com/admin/api/2026-04/graphql.json`, `X-Shopify-Access-Token`, calculated-query-cost rate limits, bulk operations) — REST is legacy as of 2024-10-01; HMAC-SHA256-signed webhooks (raw body, mandatory GDPR topics) to HTTPS/Pub-Sub/EventBridge; Checkout Extensibility is Plus-tier; not a Merchant of Record |
| `/sales-bigcommerce` | BigCommerce — open-SaaS commerce backend for makers + DTC/B2B (products, orders, customers, carts, checkout, price lists, headless); REST Management API with a v2/v3 split (`api.bigcommerce.com/stores/{store_hash}/`, classic Orders is `/v2/orders`, `X-Auth-Token`) + GraphQL Storefront/Admin/Account; thin no-HMAC webhooks (id-only payload → follow-up API call, secure with a custom header, no delivery logs, auto-deactivate); ~150 req/30s (Standard/Plus) ~450 (Pro); $0 fee on embedded payments; not a Merchant of Record |
| `/sales-checkout` | Checkout optimization — upsells, order bumps, payment plans, cart abandonment |
| `/sales-medusa` | Medusa — open-source (MIT) headless commerce engine for developers/makers, self-hosted or Medusa Cloud (products, orders, carts, customers, checkout, promotions, multi-region/warehouse); REST Admin API (`/admin`) + Store API (`/store`) with JWT-Bearer / API-key-Basic / cookie-session auth and an `x-publishable-api-key` for storefronts; **no native outbound webhooks** — react to internal events (`order.placed`) in code subscribers (`src/subscribers/`) and use the Redis Event Module in production; `limit`/`offset` pagination; 0% GMV fee; not a Merchant of Record |
| `/sales-saleor` | Saleor — open-source (BSD-3) GraphQL-first headless commerce platform on Python/Django for developers/makers, self-hosted (free, no per-sale fee) or Saleor Cloud (products with variants, channels, checkout, orders, PIM, Apps); a **single GraphQL endpoint** (no REST) with JWT auth — Users via `tokenCreate` (access + refresh), Apps via long-lived tokens, OIDC, verified via JWKS; **native outbound webhooks** (sync + async, 160+ events, GraphQL-`subscription` payloads) whose `Saleor-Signature` is **JWS RS256 by default (HMAC SHA-256 deprecated)** — verify the raw body; checkout flow `checkoutCreate` (variant IDs + channel) → `orderCreateFromCheckout` (app token) → `orderMarkAsPaid`; Relay cursor pagination; self-host needs Postgres + Redis/Celery (the `saleor-platform` repo is dev-only); Cloud Sandbox is non-commercial, commercial starts at Select ~$1,599/mo; not a Merchant of Record |
| `/sales-bagisto` | Bagisto — open-source (MIT) Laravel/PHP commerce framework by Webkul for developers/makers, self-hosted or Bagisto Cloud (products, orders, carts, customers, checkout, plus multi-vendor marketplace/POS/B2B via paid extensions); **two API flavors over one engine**, each split Shop/Admin — REST (`/api/shop`, `/api/admin`) + GraphQL (`/api/graphql`, Lighthouse) with a public **`X-STOREFRONT-KEY`** (`pk_storefront_...`) + **Laravel Sanctum bearer** auth and guest **cart tokens**; a legacy `bagisto/graphql-api` (Mobikul) package uses JWT + `x-app-secret-key` instead; **no native outbound webhooks** — react to Laravel events (`checkout.order.save.after`) in a listener or poll the orders API; REST `?page=&per_page=` (max 50) with `X-Total-*` headers, GraphQL Relay cursors; money is a decimal string (not cents); `APP_URL` mismatch breaks images, bundle-product pricing is a known slow path; no per-sale fee; not a Merchant of Record |
| `/sales-wix` | Wix eCommerce (Wix Stores) — native online store inside the Wix no-code website builder for solopreneurs/small stores (products/variants/inventory, custom checkout via Wix Payments/Stripe, orders, subscriptions, dropshipping, multichannel, Wix Headless); REST APIs at `www.wixapis.com` (Stores Products v3 `/stores/v3/products/query`, eCommerce Orders `/ecom/v1/orders/search`) with API-key (`Authorization` + `wix-site-id`) or OAuth auth and `@wix/sdk`; signed-JWT webhooks (verify with app public key, 200 within 1250 ms, 12 retries, dedupe); eCommerce gated to Core+; JS-heavy SEO/perf + template lock-in caveats; not a Merchant of Record |
| `/sales-square-online` | Square Online — free-to-start online store (Weebly-based) unified with Square POS for retail/food/omnichannel sellers (one shared catalog/inventory/customers/orders, hosted checkout, QR ordering, subscriptions); no site-builder API — automate the commerce layer via Catalog/Orders/Inventory/Payments/Checkout/Customers APIs at `connect.squareup.com/v2` with `Authorization: Bearer` (personal token or OAuth with 30-day expiry) + `Square-Version` header; HMAC-SHA256 webhooks over **notification URL + raw body** (`x-square-hmacsha256-signature`, verify with `WebhooksHelper`); `inventory.count.updated`/`order.created` events; official Square MCP server; Free (3.3%+30¢ online, square.site subdomain) / Plus ~$49 / Premium ~$149; POS↔online sync-lag overselling caveat; tax auto-calc US/Canada only; not a Merchant of Record |
| `/sales-squarespace` | Squarespace — design-first website builder's commerce backend for creative/service businesses (online store, memberships, digital downloads, gift cards, donations, subscriptions, bundled Acuity bookings); site builder is UI-only — automate the commerce layer via Orders/Inventory/Products/Transactions/Contacts Commerce APIs at `api.squarespace.com/{version}/{path}` with `Authorization: Bearer` (API key for your own site or OAuth for multi-site apps) + a custom `User-Agent`; **webhooks require OAuth** (API key can't subscribe), carry a thin payload (`orderId` → follow-up GET), and are signed **HMAC-SHA256 over the raw body** with a hex secret in `Squarespace-Signature`; money is a `{currency,value}` decimal object (not cents); Commerce API + abandoned-cart + subscriptions gated to Advanced (~$99); fees 2%→0% commerce, 7%→0% digital by tier; no multi-currency; Squarespace Payments holds caveat; not a Merchant of Record |
| `/sales-evershop` | EverShop — open-source (GPL-3.0) Node.js/TypeScript/React/GraphQL commerce platform on PostgreSQL for developers/makers, **self-hosted** (no managed cloud yet), shipping **storefront + admin + API in one project** (products/variants/categories, carts, orders, customers, promotions, checkout); **REST for writes** (`/api/products`, `/api/orders`, `/api/carts/...`, address by `uuid`) + **GraphQL for reads**; **JWT** auth (`POST /api/user/tokens` / `/api/customer/tokens` → `accessToken`+`refreshToken`, Bearer header, admin token expires in 15 min via `JWT_ADMIN_TOKEN_EXPIRY`, endpoints private by default); **no outbound webhooks** — react to in-process events (`order_placed`, `inventory_updated`) with code subscribers (`subscribers/{event}/handler.ts`) that `fetch()` out, or poll via GraphQL; needs Node 20+/Postgres 13+ (`npx create-evershop-app`); no per-sale fee; not a Merchant of Record |
| `/sales-swell` | Swell — API-first headless SaaS commerce backend for developers/makers with a **native subscription engine** (pause/resume, dunning, separate billing/fulfillment schedules) + custom data models, **no per-transaction platform fee**; two keys/two scopes — a **secret key** for the Backend REST API (`api.swell.store`, `swell-node`/`swell-php` over **port 8443**, REST/Basic over 443 as fallback) and a **public key** for the Frontend API (`swell-js` + GraphQL at `{store}.swell.store/graphql/v2`); **thin webhooks with no HMAC** (`{model,type,data:{id}}` → follow-up GET; verify via IP allowlist + secret URL; return 2xx within 10s; auto-disable on repeated failure); no MCP server; subscriptions gated to Basic+ ($79), multi-currency to Standard+ ($299), Starter $29; annual sales caps + revenue-ceiling overage; subscription-import footgun (never pass `$migrate:true`); not a Merchant of Record |
| `/sales-multichannel-selling` | Multichannel & marketplace selling strategy — sell one catalog across Amazon/eBay/Etsy/Walmart/TikTok Shop/Google/Meta from one store backend (Shopify/WooCommerce/Wix/BigCommerce); channel selection, listing-rejection causes (GTIN/GTIN-exemption, eBay business policies), oversell prevention (out-of-stock buffer, single source of truth, batched-not-real-time sync), order consolidation, and native-feature vs dedicated-channel-manager selection (LitCommerce/Sellbrite/Codisto/CedCommerce/Channable); plus the resale cross-lister class (Vendoo/List Perfectly) for Poshmark/Mercari/Depop |
| `/sales-litcommerce` | LitCommerce — multichannel listing & inventory-sync tool connecting one Main Store (Shopify/WooCommerce/Wix/BigCommerce/Squarespace) to 20+ marketplaces (Amazon, eBay, Etsy, Walmart, TikTok Shop, Google, Facebook, Temu) with a 15-minute price/inventory/order sync + a separate Product Feed tool (export to 300+ ad/shopping platforms incl. AI-search LLMs.txt/ChatGPT feeds); **no public REST API, webhooks, or MCP** — it consumes the marketplaces' APIs, so integrate orders at the store-backend layer and push data in via CSV/XML/Google-Sheet import (None/Basic/Digest/token/S3 auth); inventory sync is one-directional (Main Store → channels) with a set-out-of-stock-at-N buffer to curb overselling; ~$29–$369/mo by channels × listings (7-day free trial) |
| `/sales-meeting-scheduler` | Schedule sales meetings — booking pages, round-robin, Calendly/Chili Piper |
| `/sales-calendly` | Calendly — market-leading scheduling links, booking pages, round-robin, routing forms, workflows, REST API v2, webhooks |
| `/sales-calcom` | Cal.com — open-source scheduling infrastructure, REST API v2, webhooks, self-hosting, round-robin, routing forms, embeddable atoms |
| `/sales-vimcal` | Vimcal — keyboard-first AI calendar, availability sharing, booking links, time zone management, Vimcal EA |
| `/sales-savvycal` | SavvyCal — personalized scheduling with calendar overlay, ranked availability, REST API, webhooks, embeds |
| `/sales-reclaim` | Reclaim.ai — AI calendar automation, task scheduling, focus time, habits, scheduling links, API/webhooks |
| `/sales-motion` | Motion — AI calendar with task auto-scheduling, project management, meeting notes, docs, booking pages, REST API |
| `/sales-saner` | Saner.AI — ADHD-friendly AI personal assistant, auto-organizes notes, extracts tasks from email/docs, daily AI planner |
| `/sales-simular` | Simular (Sai) — autonomous AI desktop agent, controls apps/browsers via GUI, Simulang scripting, cloud VM, $20-500/mo |
| `/sales-dume` | Dume.ai — chat-first AI exec assistant, 50+ tool integrations, workflow automation, MCP server integration, $0-40/mo |
| `/sales-email-tracking` | Email engagement tracking — open/click/attachment tracking, follow-up timing |
| `/sales-transactional-email` | Transactional/triggered email — provider selection, API/SMTP, templates, deliverability |
| `/sales-live-chat` | Live chat and chatbot for sales — widget setup, chatbot flows, agent routing |
| `/sales-loyalty` | Customer loyalty programs — points, tiers, rewards, VIP programs, member engagement |
| `/sales-sms-marketing` | SMS marketing — opt-in collection, compliance (TCPA/GDPR), automation, two-way messaging |
| `/sales-data-hygiene` | CRM data quality — deduplication, record matching, data decay, enrichment automation |
| `/sales-b2b-advertising` | Account-based B2B advertising — display ads, retargeting, ABM, ad-to-pipeline attribution |
| `/sales-retargeting` | Retargeting — visitor retargeting, cart abandonment, dynamic ads, cross-channel |
| `/sales-push-notification` | Push notifications — opt-in optimization, rich push, segmentation, timing, deep linking |
| `/sales-pendo` | Pendo — product analytics, in-app guides, session replay, NPS/CSAT surveys, feature adoption, API |
| `/sales-chameleon` | Chameleon — AI product adoption platform, product tours, tooltips, microsurveys, launchers, HelpBar, A/B testing, Copilot AI, Ranger AI, REST API |
| `/sales-whatfix` | Whatfix — enterprise Digital Adoption Platform (DAP), in-app Flows, Smart Tips, Product Analytics, Mirror sandbox, Integration Hub |
| `/sales-in-app-messaging` | In-app messages — onboarding, feature announcements, surveys, promotions, triggers, digital adoption |
| `/sales-chatbot` | Chatbot marketing — chatbot flows, multichannel messaging, lead qualification, human handoff |

</details>

<details>
<summary><strong>Prospecting, Enrichment & Signals</strong></summary>

| Skill | What it does |
|---|---|
| `/sales-prospect-list` | Build targeted B2B prospect lists with ICP definition, filters, and segmentation |
| `/sales-enrich` | Enrich contacts with emails/phones, CRM data hygiene, dedup, bulk enrichment |
| `/sales-intent` | Interpret buying signals, intent data, job changes, lead scoring, account prioritization |
| `/sales-compete` | Run competitive displacement campaigns — find competitor customers ready to switch |
| `/sales-account-map` | Map the buying committee at a target account with multi-threading strategy |
| `/sales-lead-score` | Design, weight, and tune a lead scoring model with MQL/SQL thresholds |

</details>

<details>
<summary><strong>Cross-Platform & Strategy</strong></summary>

| Skill | What it does |
|---|---|
| `/sales-deliverability` | Email deliverability — SPF/DKIM/DMARC, warmup, inbox placement, blacklists, sender reputation |
| `/sales-agency-outbound` | Multi-client outbound for agencies — infrastructure, client isolation, white-labeling |
| `/sales-lead-routing` | Design lead routing and assignment rules — round-robin, territory, score-based |
| `/sales-integration` | Connect sales tools with webhooks, Zapier/Make, native integrations, and CRM sync |
| `/sales-content` | Organize, distribute, and measure sales collateral — battle cards, one-pagers, case studies |
| `/sales-coaching` | Sales coaching and training — onboarding, role-play, coaching frameworks, certifications |
| `/sales-solidroad` | Solidroad — AI QA + training closed-loop, 100% automated scoring, AI practice simulations from quality gaps, $10-50/user/mo |
| `/sales-secondbody` | SecondBody — voice-first AI roleplay, Rory AI coach, methodology scoring (SPIN/MEDDIC/Sandler), team heatmaps, gamification, unlimited seats $30/user/mo Pro |

</details>

<details>
<summary><strong>Marketing & GTM</strong> (33 skills from <code>coreyhaines31/marketingskills</code>)</summary>

> Install all: `npx skills add coreyhaines31/marketingskills`
> Install one: `npx skills add coreyhaines31/marketingskills --skill <skill-name>`

**SEO & Content**

| Skill | What it does |
|---|---|
| `/ai-seo` | Optimize content for AI search engines and LLM citations |
| `/content-strategy` | Plan content strategy and identify topics to cover |
| `/copywriting` | Write marketing copy for homepages, landing pages, and sites |
| `/copy-editing` | Edit, review, and improve existing marketing copy |
| `/programmatic-seo` | Generate SEO pages at scale using templates |
| `/schema-markup` | Add and optimize structured data markup |
| `/seo-audit` | Audit and diagnose technical and on-page SEO issues |
| `/site-architecture` | Plan website hierarchy, navigation, and URL structure |
| `/social-content` | Create and schedule social media content |

**Conversion & Growth**

| Skill | What it does |
|---|---|
| `/ab-test-setup` | Plan, design, and implement A/B tests and experiments |
| `/form-cro` | Optimize lead capture and contact forms |
| `/onboarding-cro` | Optimize post-signup activation and time-to-value |
| `/page-cro` | Increase conversions on marketing and landing pages |
| `/paywall-upgrade-cro` | Optimize in-app paywalls and upsell modals |
| `/popup-cro` | Create and optimize popups, modals, and overlays |
| `/signup-flow-cro` | Optimize signup, registration, and trial activation |

**Acquisition & Campaigns**

| Skill | What it does |
|---|---|
| `/ad-creative` | Generate and scale ad headlines, descriptions, and full ads |
| `/cold-email` | Write B2B cold outreach and follow-up sequences |
| `/email-sequence` | Create automated email flows and drip campaigns |
| `/free-tool-strategy` | Plan and build free marketing tools for lead generation |
| `/lead-magnets` | Create and optimize lead magnets for email capture |
| `/paid-ads` | Manage Google, Meta, LinkedIn, and Twitter ad campaigns |

**Strategy & Positioning**

| Skill | What it does |
|---|---|
| `/competitor-alternatives` | Create competitor comparison and alternative pages |
| `/launch-strategy` | Plan product launches and feature announcements |
| `/marketing-ideas` | Generate marketing inspiration and SaaS strategies |
| `/marketing-psychology` | Apply behavioral science and mental models to marketing |
| `/pricing-strategy` | Determine pricing, packaging, and monetization decisions |
| `/product-marketing-context` | Create foundational product marketing documentation |
| `/competitive-landscape` | Analyze competitive dynamics with Porter's Five Forces, Blue Ocean Strategy, and positioning maps |

**Retention & Revenue**

| Skill | What it does |
|---|---|
| `/churn-prevention` | Reduce churn through cancellation flows and save offers |
| `/referral-program` | Build and optimize referral and affiliate programs |
| `/revops` | Manage lead lifecycle and marketing-to-sales handoff |
| `/sales-enablement` | Create pitch decks, one-pagers, and objection handling docs |

**Analytics**

| Skill | What it does |
|---|---|
| `/analytics-tracking` | Set up and audit analytics measurement and event tracking |
| `/marketing-skills-collection` | Generate marketing deliverables across CRO, copywriting, SEO, analytics, and growth |
| `/marketing-automation` | Marketing automation with 23 sub-skills across CRO, copywriting, SEO, analytics, and growth |

</details>

<details>
<summary><strong>Research & Data</strong> (14 skills from <code>resciencelab/opc-skills</code>)</summary>

> Install all: `npx skills add resciencelab/opc-skills`
> Install one: `npx skills add resciencelab/opc-skills --skill <skill-name>`

**Research**

| Skill | What it does |
|---|---|
| `/producthunt` | Search and retrieve Product Hunt posts, topics, and collections |
| `/product-hunt-launch` | Optimize Product Hunt launches with research, gallery strategy, and timing |
| `/reddit` | Search and retrieve Reddit posts, comments, and subreddit info |
| `/requesthunt` | Collect and analyze user feedback from Reddit, X, and GitHub |
| `/apify-lead-generation` | Multi-platform lead scraping from Google Maps, social media, websites, and search engines |
| `/twitter` | Search and retrieve tweets, user profiles, and trends from X |

**Creative & Design**

| Skill | What it does |
|---|---|
| `/banner-creator` | Generate professional banners for GitHub, Twitter, and websites |
| `/logo-creator` | Generate professional logos with AI through iterative design |
| `/nanobanana` | Generate and edit images using AI (Gemini image model) |
| `/baoyu-slide-deck` | Transform content into professional presentation decks with customizable styles |

**SEO & Domains**

| Skill | What it does |
|---|---|
| `/seo-geo` | Optimize for AI search engines (GEO) and traditional search |
| `/backlink-analyzer` | Analyze backlink profiles with toxic link detection and competitor benchmarking |
| `/build-links` | Design link acquisition campaigns with prospect scoring and outreach strategy |
| `/domain-hunter` | Find domain names with availability checks and price comparison |

</details>

## Usage Examples

```
# Route automatically — don't know which skill? Just describe the problem
/sales-do I need to pick a CRM for my 8-person sales team

# Use platform skills directly
/sales-apollo my sequences aren't syncing to Salesforce
/sales-zendesk our SLA timers are counting through weekends

# Use strategy skills for cross-platform guidance
/sales-deliverability my cold emails are landing in spam
/sales-cadence design a 14-day outbound sequence for VP Engineering at fintech
/sales-helpdesk-selection we're on Gmail, 200 tickets/day, need to pick a help desk
```
