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

## CLI or MCP — which to use?

The gateway is a plain MCP server, so any MCP client can call it directly (see
[Use it directly over MCP](#use-it-directly-over-mcp-no-cli)). This repo also ships a
small **CLI** on top. Pick by use case:

| Use the **CLI** when… | Use **MCP directly** when… |
|---|---|
| You want to search from a shell, script, or cron job | You're wiring the tool into an MCP-aware agent/IDE |
| You want human-readable output (or `--json` for piping) | The client manages the MCP session for you |
| You want one self-contained command + a Claude Code skill | You don't want to install this package at all |

The CLI adds ergonomics — argument validation (`--max-results`, query length),
`.env` loading, tidy result formatting, and a packaged `agentcore-websearch` command —
but it's optional. Both paths use the same gateway and the same IAM/SigV4 auth.

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

## Use it directly over MCP (no CLI)

The gateway is a standard **streamable-HTTP MCP** endpoint, so you can skip this
repo's CLI entirely and point any MCP client at it. Auth is **AWS SigV4 (IAM)** on
service `bedrock-agentcore`, which most MCP clients can't sign on their own — so run
AWS's [`mcp-proxy-for-aws`](https://pypi.org/project/mcp-proxy-for-aws/) as a local
stdio MCP server that signs requests with your AWS credentials and forwards them to
the gateway. No install of this package required (only `uv`/`uvx` or `pipx`).

Configure it as an MCP server (generic form; field names vary by client). Use the
gateway URL from step 1:

```jsonc
{
  "mcpServers": {
    "agentcore_websearch": {
      "command": "uvx",
      "args": [
        "mcp-proxy-for-aws",
        "https://<gateway-id>.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp",
        "--region", "us-east-1"
      ],
      "env": { "AWS_PROFILE": "your-profile" }   // omit to use the default credential chain
    }
  }
}
```

The MCP server exposes one tool, `WebSearch` (namespaced as
`web-search-tool___WebSearch`), with arguments `query` (≤ 200 chars) and optional
`maxResults` (1–25). Run the proxy standalone to inspect it:

```bash
uvx mcp-proxy-for-aws "$AGENTCORE_GATEWAY_URL" --region us-east-1
```

The caller's IAM principal needs `bedrock-agentcore:InvokeGateway` on the gateway.
This is also how a Bedrock-hosted agent reaches the gateway — same proxy, same auth.

## Use it from Claude Code or Codex

You can drive the gateway from a coding agent as a **packaged skill** (via this
repo's CLI) or as a **direct MCP server**.

### Claude Code (skill)

[`skills/agentcore-websearch/`](skills/agentcore-websearch/SKILL.md) is a search-only
[Claude Code](https://docs.claude.com/claude-code) skill. Install the CLI (step 2),
copy the skill, then ask Claude Code to "search the web with agentcore":

```bash
cp -r skills/agentcore-websearch ~/.claude/skills/
```

### Codex (MCP server)

[Codex](https://developers.openai.com/codex/) reads this repo's
[AGENTS.md](AGENTS.md) for guidance automatically. To give it the search tool,
register the proxy in `~/.codex/config.toml`:

```toml
[mcp_servers.agentcore_websearch]
command = "uvx"
args = ["mcp-proxy-for-aws", "https://<gateway-id>.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp", "--region", "us-east-1"]
```

This is the [direct-MCP](#use-it-directly-over-mcp-no-cli) approach above — it works
for any MCP-compatible client (and for Claude Code via `claude mcp add`) if you'd
rather not use the skill.

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
