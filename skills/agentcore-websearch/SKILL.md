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

## Prerequisites

- The `agentcore-websearch` CLI on `PATH` (from `pip install .` / `pipx install .` in
  the project repo). Check with `agentcore-websearch --help`.
- `AGENTCORE_GATEWAY_URL` available — exported, or in a `.env` in the working
  directory. (If the gateway isn't set up yet, follow the project's README/AGENTS.md.)
- AWS credentials (an `AWS_PROFILE` or the default chain) whose IAM principal has
  `bedrock-agentcore:InvokeGateway` on the gateway.

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

1. Formulate a focused query (**must be ≤ 200 characters**).
2. Run `agentcore-websearch` with an appropriate `--max-results`.
3. Read the printed results (title, URL, publication date, snippet).
4. **Always cite sources** (title + URL) in the answer — an AWS acceptable-use
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
  - `agentcore-websearch: command not found` → `pip install .` in the project repo.
