# Deploy on AWS with Bedrock

The runtime is a Docker image with three long-running services: the scheduler, the intake and approvals API, and the Slack bot. It needs no agent host: nothing here uses OpenClaw or NetClaw.

## Layout

| Need | AWS service |
| --- | --- |
| Compute | ECS on Fargate (template: `deploy/aws/ecs-task-definition.json`) or one EC2 instance running `docker compose` |
| Database | RDS for PostgreSQL 16 with the `vector` extension (for memory search) |
| Models | Amazon Bedrock, through the task role. No model key is stored |
| Secrets | Secrets Manager, injected as environment variables by ECS |
| Private access | No inbound ports. The Slack bot uses Socket Mode; operators reach the API through SSM Session Manager or the VPC |
| Logs | CloudWatch Logs |
| Images | ECR |

## Steps

1. **Image.** `make image`, tag it, and push to ECR. The image already includes Postgres, Slack, MCP and boto3 support, and its build fails if any agent's golden evals fail.
2. **Database.** Create the RDS instance in private subnets. Store the URL as the secret `gtm-agents/database-url` (`postgresql://user:pass@host:5432/gtm`). The first run creates the tables.
3. **IAM.**
   - Task role: `deploy/aws/iam-task-policy.json`. It allows Bedrock invoke, read access to `gtm-agents/*` secrets, and logs. Replace ACCOUNT_ID and REGION.
   - Execution role: the standard ECS execution role, plus read access to the same secrets.
4. **Bedrock.**
   - Enable access to the chosen models in the Bedrock console for the region.
   - Set `GTM_CHEAP_PROVIDER=bedrock` and `GTM_FRONTIER_PROVIDER=bedrock`.
   - Set `GTM_MODEL_CHEAP` and `GTM_MODEL_FRONTIER` to model or inference-profile ids.
   - Set `GTM_BEDROCK_REGION`.
   - Check with `gtm models` from a one-off task.
5. **Slack app.** Ask IT to create one app in the workspace:
   - Socket Mode on, with an app-level token (`xapp-`) scoped `connections:write`.
   - Bot scopes: `chat:write`, `im:history`, `im:read`, `im:write`, `app_mentions:read`, `users:read`, `users:read.email`.
   - Events: `app_mention`, `message.im`.
   - Store the tokens as `gtm-agents/slack-app` and `gtm-agents/slack-bot`.
   - Set `GTM_SLACK_ALLOWED_USERS`, `GTM_SLACK_APPROVERS` and, optionally, `GTM_SLACK_ADMINS` (Slack user ids).
6. **CRM.**
   - Store `SALESFORCE_INSTANCE_URL` and a token from a connected app scoped to the objects the agents read.
   - Writes still go through approvals.
   - Salesforce access tokens expire. Before go-live, use the connected app's client-credentials flow to refresh them.
7. **Shadow first.** Run two weeks with sends held, as in `docs/RUNNING.md`. Turn on autonomy per motion only after the results hold.

## Talking to it

- **Ask in a DM, or mention it in a channel.** For example, "What is stalled in Stage 1 for Sam?"
- **Commands, answered instantly with no model:**
  - `status`
  - `approvals`
  - `approve 12` or `reject 12`
  - `stop` or `stop cold -- reason`
  - `resume`
  - `run <agent> <job>`
  - `help`
- **Pushed to each owner's DM:** each rep's brief and daily book. The DM is found through `slack_id` in `config/company.yaml`, or by email lookup. `GTM_SLACK_DM=0` keeps everything in the team channel.

## Running beside your company's own agent harness

If your company already has an agent harness that schedules work and talks to Slack:
- Run only the API service and the MCP servers (`gtm serve-mcp <agent> --transport streamable-http`).
- Let the harness call the tools.

The approval queue, STOP switch and golden evals stay in this runtime either way.
