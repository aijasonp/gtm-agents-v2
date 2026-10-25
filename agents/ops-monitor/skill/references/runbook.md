# Runbook

Run these on the VM, inside the agents container: `docker compose exec agents <command>`.

| Problem | First step | Then |
| --- | --- | --- |
| Job never ran or missed | `gtm agents` to confirm the job is listed, and check the scheduler is up: `docker compose ps` | Run it by hand: `gtm run <agent> <job>`. If it errors, read the error and fix config or credentials. |
| Job keeps failing | `gtm run <agent> <job>` to see the error | Typical causes: expired CRM token, model key missing, a bad input file in an inbox folder. `gtm selftest` checks keys and the database. |
| Run stuck in progress | `docker compose logs agents --tail 200` | Restart the scheduler: `docker compose restart agents`. The next run starts fresh. |
| Approval stuck executing | `gtm approvals <agent> list --all` | Check the target system (CRM, sequencer) by hand to see if the action went out. Never re-approve blindly: it could send twice. |
| Approved but not run | `gtm approvals <agent> execute --dry-run` | `gtm approvals <agent> execute`. |
| Approval backlog | `gtm approvals <agent> list --all-agents` | Approve or reject: `gtm approvals <agent> approve <ids>` / `reject <ids>`. Old drafts go stale; reject what is no longer relevant. |
| Handoff failed | `gtm handoffs --all` (the payload holds `_error`) | Fix the cause, then re-run the receiving agent's job, for example `gtm run seller-follow-up process_recaps`. |
| Handoff waiting | `gtm handoffs` | The receiving agent's job is not running: check job cadence for that agent. |
| Budget pause | `gtm usage <agent>` | Raise the budget in the agent's `agent.yaml` or `.env` if the spend is expected, then `gtm resume <agent>`. |
| High spend | `gtm usage <agent>` | Look for a loop or a large import. Move extraction to the cheap model class. |
| Copy gate failures | `gtm drafts --agent <agent> --full` | Usually a template or model change. Fix the template, or switch the frontier model. |
| Agent failed to load | `gtm selftest` | The error names the missing file. Fix it and restart the scheduler. |
