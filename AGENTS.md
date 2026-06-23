# AGENTS.md — AgentCore Web Search setup & teardown guide

This file guides an agent (or a human) through **provisioning and removing** the AWS
infrastructure for AgentCore Web Search, run **from the project root**. Once setup is
done, day-to-day searching is handled by the skill in
[`skills/agentcore-websearch/`](skills/agentcore-websearch/SKILL.md) — that skill
does **not** create or delete anything.

Scope of this guide:

- **`setup.sh`** — deploy the CloudFormation stack
  (`cfn/agentcore-websearch.yaml`: IAM role + AgentCore Gateway + web-search target),
  then write the gateway URL into the search skill's `.env`.
- **`teardown.sh`** — delete the CloudFormation stack (and the local `.env`).

Everything is provisioned as **one AWS CloudFormation stack** (`agentcore-websearch`),
so creation/deletion is atomic and auditable.

> [!WARNING]
> **Not for production.** This is a sample. `setup.sh` creates billable resources
> (AgentCore Web Search is ~$7 per 1,000 queries) and omits production concerns
> (least-privilege scoping, monitoring, HA, etc.). Review before real-world use.

## Prerequisites

- **AWS credentials** with permission to create IAM roles and AgentCore gateways
  (`aws configure`, an `AWS_PROFILE`, or the default chain).
- **AWS CLI v2 ≥ 2.35.0** — older versions lack the gateway `connector` target shape
  (`setup.sh` checks and tells you to upgrade).
- **`bash`**, and access to Amazon Bedrock AgentCore in **`us-east-1`** (the only
  region where Web Search is available).

## 0. Check current status (read-only, always safe)

```bash
# from the project root
aws bedrock-agentcore-control list-gateways --region us-east-1 \
  --query "items[?name=='WebSearchGateway'].{id:gatewayId,status:status}" --output table
```

- A gateway listed as `READY` → setup already done; skip to **Search** below.
- Nothing listed → run **§1 Setup**.

## 1. Setup — creates billable AWS resources ⚠️ confirm first

> [!IMPORTANT]
> **Get the user's explicit agreement before running `setup.sh`.** It creates real,
> billable AWS resources. State what will be created and the ~$7/1,000-query cost,
> then wait for a clear "yes".

It deploys the CloudFormation stack `agentcore-websearch`, which creates, all in
`us-east-1`:

1. An IAM service role — the gateway assumes it at query time to call the connector
   (`bedrock-agentcore:InvokeGateway` + `InvokeWebSearch`).
2. AgentCore Gateway `WebSearchGateway` (`AWS::BedrockAgentCore::Gateway`) with
   **`AWS_IAM`** inbound auth (callers use their own IAM/SigV4 credentials — no tokens).
3. A `web-search` connector target (`AWS::BedrockAgentCore::GatewayTarget`) exposing
   the `WebSearch` tool.

Run it from the project root:

```bash
# uses your current AWS credentials / AWS_PROFILE
AWS_PROFILE=your-profile ./setup.sh
```

Optional overrides (defaults shown): `REGION=us-east-1`, `STACK_NAME=agentcore-websearch`,
`GATEWAY_NAME=WebSearchGateway`, `TARGET_NAME=web-search-tool`. If you change
`STACK_NAME`, pass the same one to `teardown.sh`.

`setup.sh` is **idempotent** — CloudFormation updates the existing stack in place if
it's already deployed. On success it:

- prints the gateway URL (the stack's `GatewayUrl` output), and
- writes it into `skills/agentcore-websearch/.env` so the search skill works
  immediately.

## 2. Search (handled by the skill — no AWS resource changes)

After setup, search from the skill bundle:

```bash
cd skills/agentcore-websearch
python3 -m venv .venv && . .venv/bin/activate && pip install .   # once
agentcore-websearch "latest AWS news"
agentcore-websearch "newest python version" --max-results 5 --json
```

See [`skills/agentcore-websearch/SKILL.md`](skills/agentcore-websearch/SKILL.md) for
the full search reference. That skill is what you'd copy into `~/.claude/skills/` to
use from Claude Code.

## 3. Teardown — deletes AWS resources ⚠️ confirm first

> [!IMPORTANT]
> **Get the user's explicit agreement before running `teardown.sh`.** It permanently
> deletes the web-search target, the gateway, and the IAM role. After teardown,
> searching fails until you run `setup.sh` again.

```bash
# from the project root; pass the same names if you customized them at setup
AWS_PROFILE=your-profile ./teardown.sh
```

Then optionally remove local artifacts:

```bash
rm -rf skills/agentcore-websearch/.venv
```
(`teardown.sh` already removes `skills/agentcore-websearch/.env`.)

Verify nothing remains:

```bash
aws cloudformation describe-stacks --stack-name agentcore-websearch --region us-east-1
# (an error "Stack ... does not exist" = fully torn down)
```

## Confirmation policy (for agents)

- **Read-only** (status checks, `list-gateways`): run without asking.
- **`setup.sh`**: ask first — creates billable resources.
- **`teardown.sh`**: ask first — deletes resources irreversibly.
- When unsure, describe the action and its cost/impact, then wait for a clear "yes".

## How auth works (why the role exists)

- **Inbound** (caller → gateway): the search client SigV4-signs each MCP request as
  service `bedrock-agentcore`. The caller's IAM principal needs
  `bedrock-agentcore:InvokeGateway` on the gateway. This is what `AWS_IAM` inbound
  auth enforces.
- **Outbound** (gateway → connector): per request, the gateway **assumes the service
  role** created by `setup.sh` and calls the managed web-search connector with
  `bedrock-agentcore:InvokeWebSearch`, entirely within AWS. The caller's credentials
  never reach the connector — which is why a dedicated role is required.

> Note: the AWS docs show the InvokeWebSearch resource ARN with an empty region
> (`arn:aws:bedrock-agentcore::aws:tool/web-search.v1`), which is **rejected**. The
> working ARN includes the region: `arn:aws:bedrock-agentcore:us-east-1:aws:tool/web-search.v1`.
> `setup.sh` and the IAM templates in `iam/` use the correct form.
