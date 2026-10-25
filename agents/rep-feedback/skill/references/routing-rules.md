# Routing rules

Checked in this order. The first match wins.

| Feedback mentions | Target file | How the rule is added |
| --- | --- | --- |
| Targeting: ICP, target, wrong companies, industry, headcount, employees, too small, too big, segment, territory, region, bad fit | `config/icp.yaml` | a review comment at the end, for a person to encode as a field |
| What we sell: value prop, pain, proof, proof point, case study, claim, positioning, competitor, pricing, messaging, outcome | `config/company.yaml` | a review comment at the end |
| Anything else (tone, length, wording, timing, behavior) | `agents/<agent>/skill/SKILL.md` | a bullet at the end of the `## Rules` section (the section is created if missing) |

Never a target: anything under `library/`, any path outside `agents/<id>/skill/SKILL.md`, `config/icp.yaml` and `config/company.yaml`.

## Rule line

The rep's words, cleaned: em and en dashes removed, line breaks and backticks removed, trimmed to 200 characters at a word boundary, first letter capitalized.

## Pull request

After approval: a branch `rep-feedback/<proposal id>` from the default branch, the rule inserted into the file as it is on GitHub at that moment, one commit, one PR with the feedback ids and the diff in the description. Needs `GITHUB_TOKEN` and `GTM_FEEDBACK_REPO`.
