# AGENTS.md — AgentCore Web Search setup & teardown guide

This file guides an agent (or a human) through **provisioning and removing** the AWS
infrastructure for AgentCore Web Search, run **from the project root**. Once setup is
done, day-to-day searching is handled by the skill in
[`skills/agentcore-websearch/`](skills/agentcore-websearch/SKILL.md) — that skill
does **not** create or delete anything.

There are **no setup/teardown scripts** — provisioning is a CloudFormation stack you
deploy and delete with a couple of `aws` commands, shown below. Everything is one
stack (`agentcore-websearch`), so creation/deletion is atomic and auditable.

> [!WARNING]
> **Not for production.** This is a sample. Deploying creates billable resources
> (AgentCore Web Search is ~$7 per 1,000 queries) and omits production concerns
> (least-privilege scoping, monitoring, HA, etc.). Review before real-world use.

## Prerequisites

- **AWS credentials** with permission to create IAM roles and AgentCore gateways
  (`aws configure`, an `AWS_PROFILE`, or the default chain).
- **AWS CLI v2 ≥ 2.35.0** — older versions lack the gateway `connector` target shape.
  Check with `aws --version`.
- Access to Amazon Bedrock AgentCore in **`us-east-1`** (the only region where Web
  Search is available).

All commands below assume `us-east-1`; add `--profile <name>` (or export
`AWS_PROFILE`) as needed.

## 0. Check current status (read-only, always safe)

```bash
aws cloudformation describe-stacks --region us-east-1 --stack-name agentcore-websearch \
  --query "Stacks[0].StackStatus" --output text 2>/dev/null || echo "not deployed"
```

- `CREATE_COMPLETE` / `UPDATE_COMPLETE` → already set up; skip to **§2 Search**.
- `not deployed` → run **§1 Setup**.

## 1. Setup — creates billable AWS resources ⚠️ confirm first

> [!IMPORTANT]
> **Get the user's explicit agreement before deploying.** It creates real, billable
> AWS resources. State what will be created and the ~$7/1,000-query cost, then wait
> for a clear "yes".

Deploying [`cfn/agentcore-websearch.yaml`](cfn/agentcore-websearch.yaml) creates, all
in `us-east-1`:

1. An IAM service role — the gateway assumes it at query time to call the connector
   (`bedrock-agentcore:InvokeGateway` + `InvokeWebSearch`).
2. AgentCore Gateway `WebSearchGateway` (`AWS::BedrockAgentCore::Gateway`) with
   **`AWS_IAM`** inbound auth (callers use their own IAM/SigV4 credentials — no tokens).
3. A `web-search` connector target (`AWS::BedrockAgentCore::GatewayTarget`) exposing
   the `WebSearch` tool.

**Deploy the stack:**

```bash
aws cloudformation deploy \
  --region us-east-1 \
  --stack-name agentcore-websearch \
  --template-file cfn/agentcore-websearch.yaml \
  --capabilities CAPABILITY_IAM
```

Re-running this is **idempotent** — CloudFormation updates the stack in place if it
already exists. Optional template parameters via
`--parameter-overrides GatewayName=... TargetName=...` (defaults `WebSearchGateway` /
`web-search-tool`).

**Get the gateway URL and save it for the search CLI:**

```bash
GATEWAY_URL=$(aws cloudformation describe-stacks \
  --region us-east-1 --stack-name agentcore-websearch \
  --query "Stacks[0].Outputs[?OutputKey=='GatewayUrl'].OutputValue" --output text)
echo "$GATEWAY_URL"
printf 'AGENTCORE_GATEWAY_URL=%s\n' "$GATEWAY_URL" > .env
```

(If you use a profile, also append `AWS_PROFILE=<name>` to `.env`.)

## 2. Search (handled by the skill — no AWS resource changes)

```bash
# from the project root — install once into user space (no venv to activate)
uv tool install .            # or: pipx install .  (or a venv + `pip install .`)
agentcore-websearch "latest AWS news"
agentcore-websearch "newest python version" --max-results 5 --json
```

The `agentcore-websearch` package lives at the repo root; the
[`skills/agentcore-websearch/`](skills/agentcore-websearch/SKILL.md) folder is a
search-only Claude Code skill that calls this same CLI (copy it into
`~/.claude/skills/`).

## 3. Teardown — deletes AWS resources ⚠️ confirm first

> [!IMPORTANT]
> **Get the user's explicit agreement before deleting.** It permanently removes the
> web-search target, the gateway, and the IAM role. After teardown, searching fails
> until you deploy again.

```bash
aws cloudformation delete-stack --region us-east-1 --stack-name agentcore-websearch
aws cloudformation wait stack-delete-complete --region us-east-1 --stack-name agentcore-websearch
rm -f .env                                    # remove the stale gateway URL
```

Verify nothing remains:

```bash
aws cloudformation describe-stacks --region us-east-1 --stack-name agentcore-websearch
# (an error "Stack ... does not exist" = fully torn down)
```

## Confirmation policy (for agents)

- **Read-only** (status checks, `describe-stacks`): run without asking.
- **`cloudformation deploy`**: ask first — creates billable resources.
- **`cloudformation delete-stack`**: ask first — deletes resources irreversibly.
- When unsure, describe the action and its cost/impact, then wait for a clear "yes".

## How auth works (why the role exists)

- **Inbound** (caller → gateway): the search client SigV4-signs each MCP request as
  service `bedrock-agentcore`. The caller's IAM principal needs
  `bedrock-agentcore:InvokeGateway` on the gateway. This is what `AWS_IAM` inbound
  auth enforces.
- **Outbound** (gateway → connector): per request, the gateway **assumes the service
  role** defined in the template and calls the managed web-search connector with
  `bedrock-agentcore:InvokeWebSearch`, entirely within AWS. The caller's credentials
  never reach the connector — which is why a dedicated role is required.

> Note: the AWS docs show the InvokeWebSearch resource ARN with an empty region
> (`arn:aws:bedrock-agentcore::aws:tool/web-search.v1`), which is **rejected**. The
> working ARN includes the region: `arn:aws:bedrock-agentcore:us-east-1:aws:tool/web-search.v1`.
> The CloudFormation template (`cfn/agentcore-websearch.yaml`) uses the correct form.
