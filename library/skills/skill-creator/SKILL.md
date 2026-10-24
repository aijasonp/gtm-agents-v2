---
name: skill-creator
description: Meta-skill that generates new SKILL.md files from a task description. Describe what you want the agent to be able to do, and this skill produces a complete, deployment-ready skill file following AgentSkills SKILL.md conventions. Enables recursive skill expansion without manual writing.
---

# Skill Creator (Meta Skill)

## Overview

This is the skill that makes skills. Give it a description of a capability you want the agent to have, and it produces a complete, properly formatted `SKILL.md` file — ready to drop into the workspace and load immediately.

Use this when you notice a repeated task that doesn't have a skill yet, when a new workflow needs to be codified, or when you want to formalize how the agent handles a specific type of request.

---

## Instructions

### Inputs
Provide:
- **What should this skill do?** (plain language description of the capability)
- **Who uses it?** (AE, an agent autonomously, RevOps, etc.)
- **What triggers it?** (what kind of request or input invokes this skill?)
- **What does good output look like?** (describe the ideal output format and quality)
- **Any constraints?** (things it should never do, known edge cases)

Optionally:
- Example input/output pair
- Name preference for the skill

### Step 1 — Design the skill architecture
Before writing the SKILL.md, define:

| Property | Decision |
|----------|----------|
| **Name** | Short, kebab-case, descriptive (e.g., `cold-email`, `deal-brief-writer`) |
| **Description** | One sentence for the skills catalog. Start with a verb. |
| **Core behavior** | What does this skill actually *do*? |
| **Input format** | What does the user/system provide? |
| **Output format** | What does the skill produce? Fixed structure or flexible? |
| **Decision logic** | Are there modes, branches, or conditions? |
| **Constraints** | Hard limits — what should it never do? |
| **Example** | One concrete input → output pair |

### Step 2 — Write the SKILL.md

Follow this exact structure:

```markdown
name: [skill-name]
description: [One sentence. Starts with a verb. Explains what this skill does and who/what it's for.]
---

# [Skill Title]

## Overview
[2-4 sentences. What this skill does, why it exists, what problem it solves.]

## Instructions

### [Input section]
[What the user provides. Be specific.]

### [Core process / steps]
[How the skill processes the input. Numbered steps or clear sections.]

### [Output format]
[Exact structure of the output. Use templates, tables, or labeled sections.]

## Constraints

- [What this skill never does.]
- [Edge cases it handles explicitly.]
- [Quality standards it maintains.]
```

### Step 3 — Validate before delivering
Check the generated skill against these criteria:

- [ ] Name is kebab-case and unique in the skills directory
- [ ] Description fits in one sentence and starts with a verb
- [ ] Instructions are specific enough that a new session could follow them cold
- [ ] Output format is defined — not left to interpretation
- [ ] Constraints are explicit, not implied
- [ ] At least one example is included (or the output format is so clear an example isn't needed)
- [ ] No instructions that conflict with the agent's identity and operating rules

### Step 4 — Provide deployment instructions
After the SKILL.md content, output:

```
---
DEPLOYMENT:
1. Save to: ~/.netclaw/skills/[skill-name]/SKILL.md (or the shared library, then re-run the fleet install)
2. Verify it appears in `netclaw skill list`
3. Test with: [suggested test prompt]
```

---

## Constraints

- Generated skills must follow the AgentSkills SKILL.md conventions exactly — frontmatter with `name:` and `description:`, then `---`, then body.
- Never generate a skill that bypasses the agent's safety or access control policies.
- Skills that interact with external systems (HubSpot, Linear, Slack) must include explicit human approval gates in their instructions.
- If the task description is too vague to produce a useful skill, ask clarifying questions before generating — a vague skill file is worse than no skill file.
- Always suggest a test prompt the user can immediately run to verify the skill works as intended.
