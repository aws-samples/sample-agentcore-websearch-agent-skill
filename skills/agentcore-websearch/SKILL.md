---
name: agentcore-websearch
description: Web search via an AWS Bedrock AgentCore Gateway, called with local AWS/IAM credentials (SigV4) — no API keys or bearer tokens. Use when the user asks to search the web, look up current events, find recent/online information, or research topics needing up-to-date web results through their AgentCore Web Search gateway. Triggers - 'agentcore search', 'search the web with agentcore', 'web search', 'look up', 'find online', 'what is the latest', 'current news about', 'research'. Requires the agentcore-websearch CLI installed and a gateway already provisioned (see the project's README/AGENTS.md); this skill does not create or delete AWS resources.
---

# AgentCore Web Search

Search the web using the **AgentCore Web Search** tool through a private MCP gateway
in the user's AWS account, via the `agentcore-websearch` CLI. Authentication is
**local AWS credentials (SigV4/IAM)** — no API keys or tokens. Results are grounded,
cited, and current.

> [!NOTE]
> This skill **only searches**. It assumes the `agentcore-websearch` CLI is installed
> and the AgentCore Gateway already exists, with `AGENTCORE_GATEWAY_URL` set (env or a
> `.env`). Provisioning the gateway and installing the CLI is a one-time step — see
> the project's **README.md** / **AGENTS.md**. This skill never creates or deletes
> AWS resources.

## Prerequisites — run this preflight check first

Before searching, **actually run the commands below in the shell** and read their
printed output. Do **not** infer readiness from a `.env` file, from this
conversation, or from earlier turns — environment variables that matter are the ones
live in the shell that will run `agentcore-websearch`, so verify them with a real
`echo`.

```bash
# 1. Is the CLI installed and on PATH?
command -v agentcore-websearch || echo "MISSING: run 'uv tool install .' in the project repo"

# 2. Is the gateway URL actually set in THIS shell's environment?
echo "AGENTCORE_GATEWAY_URL=${AGENTCORE_GATEWAY_URL:-<empty>}"

# 3. Which AWS identity/profile will sign requests?
echo "AWS_PROFILE=${AWS_PROFILE:-<default chain>}"
aws sts get-caller-identity --query Arn --output text 2>&1
```

Interpret the real output:

- **Line 2 prints `<empty>`** → the URL is not exported in this shell. If you're
  running the CLI from a directory containing a `.env`, the CLI will load it — but
  confirm by running `agentcore-websearch --list-tools` (below), not by reading the
  file. Otherwise export it: `export AGENTCORE_GATEWAY_URL=https://…/mcp` (see the
  project's README/AGENTS.md to provision the gateway if it doesn't exist yet).
- **Line 3 shows an unexpected profile/account** → the caller will sign as the wrong
  identity (a common cause of `403`). Override per-call with `--profile <name>`, or
  `export AWS_PROFILE=<name>`.
- **`get-caller-identity` errors** → credentials are missing/expired; refresh your
  `AWS_PROFILE` / SSO login.

The caller's IAM principal needs `bedrock-agentcore:InvokeGateway` on the gateway.
Confirm the whole chain end-to-end with a live, non-destructive call:

```bash
agentcore-websearch --list-tools    # prints the WebSearch tool on success
```

## Search

```bash
agentcore-websearch "<search query>"
```

Options:
- `--max-results N` — number of results, 1–25 (default 10)
- `--json` — raw tool result JSON (`results[]` with `text`, `url`, `title`, `publishedDate`)
- `--list-tools` — show the gateway's tools (diagnostic)
- `--gateway-url` / `--profile` / `--region` — override the environment/`.env`

### Workflow

1. On first use in a session, run the [preflight check](#prerequisites--run-this-preflight-check-first)
   and read its real output — don't assume the env is set.
2. Formulate a focused query (**must be ≤ 200 characters**).
3. Run `agentcore-websearch` with an appropriate `--max-results`.
4. Read the printed results (title, URL, publication date, snippet).
5. **Always cite sources** (title + URL) in the answer — an AWS acceptable-use
   requirement for AgentCore Web Search.

### Examples

```bash
agentcore-websearch "latest TypeScript release"
agentcore-websearch "AWS re:Invent 2026 keynotes" --max-results 15 --json
```

## Notes & limits

- **Region:** the gateway lives in `us-east-1`; the CLI signs for the host region
  automatically, so a different `AWS_REGION` in the shell is fine.
- **Cost:** ~$7 per 1,000 queries (each search = one query).
- **Common errors:**
  - `AGENTCORE_GATEWAY_URL is not set` → export it, or `cd` to a dir with a `.env`,
    or provision per the project's README/AGENTS.md.
  - credentials missing/expired → refresh your `AWS_PROFILE` / SSO login.
  - `Insufficient permissions` → caller lacks `bedrock-agentcore:InvokeGateway`.
  - `agentcore-websearch: command not found` → `uv tool install .` in the project repo.
