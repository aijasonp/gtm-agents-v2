---
name: hiring
description: >
  Application review, candidate evaluation, and hiring pipeline automation.
  Use when reviewing job applications, producing candidate digests, investigating
  candidate backgrounds, or managing progression through hiring stages.
  Works alongside role-specific rubrics stored in the workspace.
metadata: { "openclaw": { "emoji": "📋" } }
---

# Hiring Skill

General-purpose application review and hiring pipeline management. Role-specific rubrics live in the workspace at `hiring/<role>/rubric.md` — this skill covers the methodology that applies across all roles.

## File Structure

Each role gets its own directory:

```
hiring/<role>/
  job-description.md ← the JD for this role (pull down and store here)
  rubric.md          ← role-specific signals, tiers, red flags
  candidates.md      ← pipeline tracker
  digests/
    <candidate>.md   ← per-candidate digest (kebab-case)
```

## Application Review Process

### 1. Read the rubric and job description first
Load `hiring/<role>/rubric.md` and `hiring/<role>/job-description.md` before reviewing any candidates. The rubric defines signals, tier thresholds, and role-specific criteria. The JD gives context on what the role actually requires.

### 2. Investigate — don't just read
For every candidate, go beyond the application text. What to investigate depends on the role, but examples include:

- **GitHub** (technical roles): Check repos (stars, languages, recency, authorship). Pull up the contribution graph — how many contributions in the past year? What percentage of days? Is it sustained or bursty?
- **LinkedIn**: Career trajectory, tenure, progression, follower count, content history
- **Blog/portfolio**: Real content or placeholder? Depth or fluff?
- **Products/demos**: Actually visit them. Do they work? Are they impressive?
- **Social presence**: Follower counts, content quality, community engagement
- **Published work**: Papers, articles, case studies, talks — whatever's relevant to the role

### 3. Apply the verification hierarchy
Not all evidence is equal. Rank by strength:

1. **Objectively measurable** (strongest): GitHub stars, contribution graphs, product metrics, competition placements
2. **Institutionally verified**: Degrees from selective programs, promotions at companies with rigorous leveling, funding raised
3. **Publicly visible but self-directed**: Blog posts, talks, open source with low adoption
4. **Self-reported** (weakest): Resume bullets, application answers

Self-reported claims are signals to investigate, not evidence. The more impressive a claim and the less verifiable it is, the more skeptical you should be.

### 4. Look for corroboration and contradiction
Signals that reinforce each other are much stronger than isolated signals. Signals that contradict each other are red flags.

### 5. Write the digest
Every review produces a digest at `hiring/<role>/digests/<candidate-name>.md`. Structure:

```markdown
# <Candidate Name>

**Date:** YYYY-MM-DD
**Current Role:** ...
**Source:** Direct Apply | Agency | Referral
**Greenhouse ID:** ...

## Standout Signals
- <signal>: <evidence> — <verified|self-reported|partially verified>

## Positive Signals
- <signal>: <evidence> — <verified|self-reported|partially verified>

## Negative Signals / Red Flags
- ...

## Public Artifacts
<!-- Sections below will vary by role. For technical roles, include GitHub
     analysis. For all roles, include whatever public evidence is relevant. -->
- <artifact type>: <findings>

## Application Answers
<assessment of depth, specificity, originality>

## Verification Summary
<what was independently verified vs. self-reported only>

## Tier Recommendation
**Tier X** — <reasoning tied to evidence above>

## Level Estimate
<Senior | Staff | Principal | etc.> — <reasoning>
```

### 6. Update the tracker
After writing the digest, add a row to `hiring/<role>/candidates.md`.

## Greenhouse Integration

Use the `greenhouse` skill for ATS API access — pulling applications, downloading resumes, adding notes, advancing/rejecting candidates. See that skill's SKILL.md for command reference.

## Safety

- **Read freely**: application data, candidate info, job details
- **Write only when explicitly asked**: advancing, rejecting, adding notes, adding candidates
- **Never auto-reject or auto-advance** without explicit user instruction
- **Store digests locally** — they contain assessment opinions, not just facts
