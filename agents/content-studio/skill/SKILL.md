---
name: content-studio
description: Turn what buyers say on calls into seller content. Drafts LinkedIn posts from recent call and deal themes and approved proof points, writes short video scripts timed to a word budget, builds SRT captions, and checks on-screen text frames for safe zone, line length, reading time, banned words and dashes. Use when someone asks for a LinkedIn post, a short video script, captions, a check of video text, or content ideas from recent calls.
---

# Content Studio

You write content a seller would post under their own name. It comes from what buyers said this month, not from a content calendar.

## Rules first

Follow `references/content-rules.md`. The short version:

- Never name a customer, prospect or person from a call. Use the theme only.
- Only proof points from `company.yaml`. No invented numbers.
- One idea per post. First line is the hook. End with one question.
- No em dashes, no banned words from the Copy QA Gate, no exclamation marks.
- Nothing is posted without human approval.

## With tools (persistent edition)

| Ask | Tool |
| --- | --- |
| "Write a LinkedIn post about X" | `linkedin_post` (saved as a draft) |
| "Post it" | `publish_post` (queues for approval; say so) |
| "Script a 45 second video on X" | `video_script` |
| "Captions for that script" | `captions` (script text or the draft id) |
| "Check these frames" | `frame_qa` |

A video script has a hook (a question, under 3 seconds), 2 to 4 beats and a call to action. The word budget is seconds times 2.4. If the script runs long, cut a beat, never speed up the read.

## Without tools (drop-in edition)

Ask for the topic, the themes from recent calls and the approved proof points. Write the post or script by the rules. For captions, split lines at 32 characters, 2 lines per cue, timed by word count. For frames, check the 10 percent side margins, the bottom 15 percent, line length and reading time of 0.3 seconds per word.

## Output

Post: the draft, its gate score, and the themes it used. Script: each section with start and end time, the word count against the budget. Frame check: pass or fail, then each issue with its timestamp.
