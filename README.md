# AgentCore Web Search (IAM / SigV4)

A sample that provisions an **Amazon Bedrock AgentCore Gateway** with the managed
**Web Search** tool, then calls it from a small Python CLI using your **local AWS
credentials (SigV4/IAM)** — no API keys or bearer tokens. Web Search is fully managed,
MCP-compliant, served entirely within AWS (zero data egress), and priced at ~$7 per
1,000 queries.

Because the gateway speaks MCP and authenticates callers with IAM, it's a good fit
for grounding IAM-authenticated, Bedrock-hosted agents (e.g. **Claude Code**,
**Codex**, or **Cowork** on Bedrock) in live web results.

> **Region:** Web Search is only available in `us-east-1`.

> [!WARNING]
> **Not for production.** This is a sample for learning/experimentation. It omits
> production concerns (least-privilege scoping, monitoring, rate limiting, HA,
> credential rotation). Review and adapt before any real-world use. Provided "as is"
> (see [LICENSE](LICENSE)).

## How it works

```
you ── agentcore-websearch CLI ──SigV4/MCP over HTTPS──▶ AgentCore Gateway ──▶ web-search connector
       (mcp-proxy-for-aws lib)        (AWS_IAM auth)        assumes IAM role     (managed web index)
```

- **Inbound** (CLI → gateway): each MCP request is SigV4-signed; your IAM principal
  needs `bedrock-agentcore:InvokeGateway` on the gateway.
- **Outbound** (gateway → connector): the gateway assumes a service role granting
  `bedrock-agentcore:InvokeWebSearch`, entirely within AWS.

## Prerequisites

- AWS credentials (`aws configure` / `AWS_PROFILE`) able to create IAM roles and
  AgentCore gateways, with access to Bedrock AgentCore in `us-east-1`.
- **AWS CLI v2 ≥ 2.35.0** (older versions lack the gateway `connector` target shape).
- **Python 3.9+**.

## 1. Deploy the gateway (CloudFormation)

[`cfn/agentcore-websearch.yaml`](cfn/agentcore-websearch.yaml) defines the IAM service
role, the gateway (`AWS_IAM` inbound auth), and the web-search target.

```bash
aws cloudformation deploy \
  --region us-east-1 --stack-name agentcore-websearch \
  --template-file cfn/agentcore-websearch.yaml --capabilities CAPABILITY_IAM

# save the gateway URL where the CLI looks for it
GATEWAY_URL=$(aws cloudformation describe-stacks --region us-east-1 \
  --stack-name agentcore-websearch \
  --query "Stacks[0].Outputs[?OutputKey=='GatewayUrl'].OutputValue" --output text)
printf 'AGENTCORE_GATEWAY_URL=%s\n' "$GATEWAY_URL" > .env
```

## 2. Install the CLI and search

```bash
python -m venv .venv && . .venv/bin/activate
pip install .                       # installs the `agentcore-websearch` command

agentcore-websearch "latest AWS news"
agentcore-websearch "newest python version" --max-results 5 --json
agentcore-websearch --list-tools    # diagnostic
```

The CLI reads `AGENTCORE_GATEWAY_URL` (and optional `AWS_PROFILE`) from `.env` or the
environment. Its only dependency is
[`mcp-proxy-for-aws`](https://pypi.org/project/mcp-proxy-for-aws/), which handles the
SigV4 signing and MCP transport.

## 3. Clean up

```bash
aws cloudformation delete-stack --region us-east-1 --stack-name agentcore-websearch
aws cloudformation wait stack-delete-complete --region us-east-1 --stack-name agentcore-websearch
```

## Use it as a Claude Code skill

[`skills/agentcore-websearch/`](skills/agentcore-websearch/SKILL.md) is a search-only
[Claude Code](https://docs.claude.com/claude-code) skill. Install the CLI (step 2),
copy the skill, then ask Claude Code to "search the web with agentcore":

```bash
cp -r skills/agentcore-websearch ~/.claude/skills/
```

To let a Bedrock-hosted agent search directly, register `mcp-proxy-for-aws` as a
stdio MCP server pointed at your gateway URL (`uvx mcp-proxy-for-aws <gateway-url>
--region us-east-1`).

## More

- **[AGENTS.md](AGENTS.md)** — full setup/teardown guide, confirmation policy, and how
  auth works.
- **Note on the InvokeWebSearch ARN:** the docs' empty-region form
  (`arn:aws:bedrock-agentcore::aws:tool/web-search.v1`) is rejected; the working ARN
  is `arn:aws:bedrock-agentcore:us-east-1:aws:tool/web-search.v1` (used by the
  template).

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for how to report a
security issue. Do not open public issues for security findings.

## License

MIT-0. See [LICENSE](LICENSE).
