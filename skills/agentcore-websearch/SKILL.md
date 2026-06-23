---
name: agentcore-websearch
description: Web search via an AWS Bedrock AgentCore Gateway, called with local AWS/IAM credentials (SigV4) — no API keys or bearer tokens. Use when the user asks to search the web, look up current events, find recent/online information, or research topics needing up-to-date web results through their AgentCore Web Search gateway. Triggers - 'agentcore search', 'search the web with agentcore', 'web search', 'look up', 'find online', 'what is the latest', 'current news about', 'research'. Requires a gateway that was already provisioned (see the project's AGENTS.md); this skill does not create or delete AWS resources.
---

# AgentCore Web Search

Search the web using the **AgentCore Web Search** tool through a private MCP gateway
in the user's AWS account. Authentication is **local AWS credentials (SigV4/IAM)** —
no API keys or tokens. Results are grounded, cited, and current.

> [!NOTE]
> This skill **only searches**. It assumes the AgentCore Gateway + Web Search tool
> already exist and that `AGENTCORE_GATEWAY_URL` is configured. Creating or deleting
> that infrastructure (the `setup.sh` / `teardown.sh` scripts) is **not** part of
> this skill — see the project's **AGENTS.md** for the one-time setup/teardown guide.
> This skill never creates or deletes AWS resources.

## Self-contained — search files live in this folder

This folder ships everything needed to *search*: a packaged Python CLI
(`pyproject.toml` + `src/agentcore_websearch/`), the `websearch` convenience wrapper,
`.env.example`, and this `SKILL.md`. Copying this one folder
(e.g. into `~/.claude/skills/`) gives a working search skill — provided a gateway
already exists.

Resolve `DIR` to this skill's own directory:

```bash
DIR="$HOME/.claude/skills/agentcore-websearch"   # or wherever this folder lives
```

## Prerequisites

- A provisioned AgentCore Gateway with the Web Search tool, and its URL available as
  `AGENTCORE_GATEWAY_URL` (in the environment or in this folder's `.env`). If it
  isn't set up yet, follow **AGENTS.md** in the project repository first.
- AWS credentials available (an `AWS_PROFILE` or the default credential chain) whose
  IAM principal has `bedrock-agentcore:InvokeGateway` on the gateway.
- **Python 3.9+**. Install the CLI once (it declares its one dependency,
  `mcp-proxy-for-aws`, which brings boto3/botocore and the `mcp` SDK):
  `cd "$DIR" && python3 -m venv .venv && . .venv/bin/activate && pip install .`
  This installs an `agentcore-websearch` console command. (`pipx install .` also works.)

## Search

```bash
# after `pip install .` in this folder:
agentcore-websearch "<search query>"

# or, without activating the venv, the bundled wrapper:
DIR="$HOME/.claude/skills/agentcore-websearch"   # this skill folder
"$DIR/websearch" "<search query>"
```

Options:
- `--max-results N` — number of results, 1–25 (default 10)
- `--json` — raw tool result JSON (parse `results[]` with fields `text`, `url`,
  `title`, `publishedDate`)
- `--list-tools` — show the gateway's tools (diagnostic)

The CLI auto-loads `AGENTCORE_GATEWAY_URL` (and optional `AWS_PROFILE`) from a `.env`
in the current directory or the package directory, or from the environment if exported.

### Workflow

1. Formulate a focused query (**must be ≤ 200 characters**).
2. Run the wrapper with an appropriate `--max-results`.
3. Read the printed results (title, URL, publication date, snippet).
4. **Always cite sources** (title + URL) in your answer — an AWS acceptable-use
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
- **Transport:** the CLI uses the `mcp-proxy-for-aws` library
  (`aws_iam_streamablehttp_client`) with the `mcp` SDK's `ClientSession`, in-process —
  the library does the SigV4 signing, MCP handshake, and region signing. No signing
  code or subprocess lives in this folder.
- **Common errors:**
  - `AGENTCORE_GATEWAY_URL is not set` → the gateway isn't configured here; set the
    env var, or provision it per the project's **AGENTS.md**.
  - credentials missing/expired → refresh your `AWS_PROFILE` / SSO login.
  - `Insufficient permissions` → caller lacks `bedrock-agentcore:InvokeGateway`.
  - `mcp-proxy-for-aws is required` → run `pip install .` in this folder.
