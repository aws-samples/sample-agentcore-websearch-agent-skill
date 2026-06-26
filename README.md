# AgentCore Web Search (IAM / SigV4)

A sample that provisions an **Amazon Bedrock AgentCore Gateway** with the managed
**Web Search** tool, then lets you call it using your **local AWS credentials
(SigV4/IAM)** — no API keys or bearer tokens. Web Search is fully managed,
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
                              your AWS account (us-east-1)
 any MCP client ──SigV4 / MCP over HTTPS──▶ AgentCore Gateway ──▶ web-search connector
 (CLI, agent, …)        (AWS_IAM auth)        assumes IAM role      (managed web index)
```

- **Inbound** (client → gateway): each MCP request is SigV4-signed; the caller's IAM
  principal needs `bedrock-agentcore:InvokeGateway` on the gateway.
- **Outbound** (gateway → connector): the gateway assumes a service role granting
  `bedrock-agentcore:InvokeWebSearch`, entirely within AWS.

The gateway is a plain MCP server, so **any MCP client can call it**. This repo also
ships a small CLI and a Claude Code skill on top — see [Use it](#use-it) for the
options.

## Prerequisites

- AWS credentials (`aws configure` / `AWS_PROFILE`) able to create IAM roles and
  AgentCore gateways, with access to Bedrock AgentCore in `us-east-1`.
- **AWS CLI v2 ≥ 2.35.0** (older versions lack the gateway `connector` target shape).
- [`uv`](https://docs.astral.sh/uv/) (recommended — used to install the CLI and to
  run the direct-MCP proxy) or `pipx`. **Python 3.9+** is also fine via `pip`.

## Setup — deploy the gateway (CloudFormation)

This one-time step is required for every usage option below.
[`cfn/agentcore-websearch.yaml`](cfn/agentcore-websearch.yaml) defines the IAM service
role, the gateway (`AWS_IAM` inbound auth), and the web-search target.

```bash
aws cloudformation deploy \
  --region us-east-1 --stack-name agentcore-websearch \
  --template-file cfn/agentcore-websearch.yaml --capabilities CAPABILITY_IAM

# capture the gateway URL (used by every option below)
GATEWAY_URL=$(aws cloudformation describe-stacks --region us-east-1 \
  --stack-name agentcore-websearch \
  --query "Stacks[0].Outputs[?OutputKey=='GatewayUrl'].OutputValue" --output text)
echo "$GATEWAY_URL"
```

## Use it

Pick the option that fits — all use the same gateway and the same IAM/SigV4 auth:

| Option | Best when… |
|---|---|
| **A. CLI** | Searching from a shell, script, or cron job; want formatted or `--json` output |
| **B. Any MCP client** | Wiring the tool into an MCP-aware app without installing this package |
| **C. Claude Code / Codex** | Letting a coding agent search for you |

### Option A — CLI

The CLI adds ergonomics over raw MCP: argument validation, `.env` loading, tidy
result formatting, and a packaged `agentcore-websearch` command.

Install it to your user space so the `agentcore-websearch` command is available
anywhere — no venv to activate (uses [`uv`](https://docs.astral.sh/uv/), or `pipx`):

```bash
uv tool install .          # or: pipx install .

# save the gateway URL where the CLI looks for it
printf 'AGENTCORE_GATEWAY_URL=%s\n' "$GATEWAY_URL" > .env

agentcore-websearch "latest AWS news"                       # basic search (default 10 results)
agentcore-websearch "newest python version" -n 5            # -n / --max-results (1–25)
agentcore-websearch "aws re:Invent 2026 dates" --json       # raw tool result JSON (pipe to jq)
agentcore-websearch --list-tools                            # list gateway tools and exit
agentcore-websearch --help                                  # full usage

# Override config without a .env / exported vars:
agentcore-websearch "ecs vs eks" \
  --gateway-url "$GATEWAY_URL" \
  --profile my-aws-profile \
  --region us-east-1
```

The CLI reads `AGENTCORE_GATEWAY_URL` (and optional `AWS_PROFILE`) from a `.env` in
the working directory or the environment. With a user-space install you'll usually
want it set globally instead of per-directory — the helper script writes the export
to your shell profile (auto-detecting `~/.zshrc` / `~/.bash_profile`):

```bash
./scripts/export-env.sh                          # reads GatewayUrl from the CFN stack
./scripts/export-env.sh --profile my-aws-profile # also export AWS_PROFILE
source ~/.zshrc                                  # apply to the current shell
```

Its only dependency is
[`mcp-proxy-for-aws`](https://pypi.org/project/mcp-proxy-for-aws/), which handles the
SigV4 signing and MCP transport.

To update after pulling changes: `uv tool install --force .` (or `pipx reinstall
agentcore-websearch`). To remove: `uv tool uninstall agentcore-websearch`. Prefer a
throwaway project venv instead? `python -m venv .venv && . .venv/bin/activate && pip
install .` works too.

### Option B — Any MCP client (no CLI)

The gateway is a standard **streamable-HTTP MCP** endpoint. Auth is **AWS SigV4
(IAM)** on service `bedrock-agentcore`, which most MCP clients can't sign on their
own — so run AWS's [`mcp-proxy-for-aws`](https://pypi.org/project/mcp-proxy-for-aws/)
as a local stdio MCP server that signs requests with your AWS credentials and
forwards them to the gateway. No install of this package required.

Configure it as an MCP server (generic form; field names vary by client):

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

It exposes one tool, `WebSearch` (namespaced as `web-search-tool___WebSearch`), with
arguments `query` (≤ 200 chars) and optional `maxResults` (1–25). Inspect it by
running the proxy standalone:

```bash
uvx mcp-proxy-for-aws "$GATEWAY_URL" --region us-east-1
```

### Option C — Claude Code or Codex

Both agents support **two** ways to add the tool: install this repo's **skill** (a
folder with [`SKILL.md`](skills/agentcore-websearch/SKILL.md) that drives the CLI from
Option A), or register the gateway as an **MCP server** (the proxy from Option B). Use
whichever you prefer — the skill needs the CLI installed; the MCP server doesn't.

> The MCP commands below take the gateway URL from Setup. Substitute it for
> `$GATEWAY_URL` if your client doesn't expand environment variables.

**[Claude Code](https://docs.claude.com/claude-code)**

```bash
# As a skill (requires the CLI from Option A):
cp -r skills/agentcore-websearch ~/.claude/skills/

# …or as an MCP server (no CLI needed):
claude mcp add agentcore-websearch -- uvx mcp-proxy-for-aws "$GATEWAY_URL" --region us-east-1
```

Then ask Claude Code to "search the web with agentcore".

**[Codex](https://developers.openai.com/codex/)**

```bash
# As a skill (requires the CLI from Option A):
cp -r skills/agentcore-websearch ~/.codex/skills/
```

```toml
# …or as an MCP server in ~/.codex/config.toml (no CLI needed):
[mcp_servers.agentcore_websearch]
command = "uvx"
args = ["mcp-proxy-for-aws", "https://<gateway-id>.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp", "--region", "us-east-1"]
```

## Clean up

Delete the stack to remove the gateway, target, and IAM role:

```bash
aws cloudformation delete-stack --region us-east-1 --stack-name agentcore-websearch
aws cloudformation wait stack-delete-complete --region us-east-1 --stack-name agentcore-websearch
```

## Reference

- **[AGENTS.md](AGENTS.md)** — full setup/teardown guide, confirmation policy, and how
  auth works.

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for how to report a
security issue. Do not open public issues for security findings.

## License

MIT-0. See [LICENSE](LICENSE).
