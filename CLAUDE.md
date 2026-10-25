# Working in gtm-agents

- Clean room: write new code. Never copy code, prompts or data from any employer system or from the gtm-engine reference repo; use it only to understand what an agent should do.
- Anything that must be correct every time (scoring, dedup, decay, stacking, copy checks, CRM field mapping) is Python in `core/` or an agent's `engine.py`, exposed as a tool. Prompts handle judgment and writing only.
- Every CRM write or outbound send goes through `ctx.approvals.request`. No exceptions.
- Every agent needs `evals/golden.yaml` and `evals/evaluator.py` (or an evaluator in `evals/runner.py`). Run `make test evals compile` before committing.
- SKILL.md files stay under 500 lines, plain words, no em dashes, no filler words (see the Copy QA Gate banned list).
- Sample data uses fictional companies (`*.example` domains). Never commit customer data, keys, `.env`, `license.json` or private keys.
- Files under `library/` are third-party MIT playbooks: keep their LICENSE and SOURCE.md, never edit them silently, and never add a source without a verified permissive license.
