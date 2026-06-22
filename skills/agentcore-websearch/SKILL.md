---
name: agentcore-websearch
description: Web search via AWS Bedrock AgentCore Web Search, called with local AWS/IAM credentials (SigV4) — no API keys or bearer tokens. Also manages the full lifecycle of the underlying AWS gateway (create/teardown). Use when the user asks to search the web, look up current events, find recent/online information, research topics needing up-to-date web results, OR to set up / tear down their AgentCore Web Search gateway. Triggers - 'agentcore search', 'search the web with agentcore', 'web search', 'look up', 'find online', 'what is the latest', 'current news about', 'research', 'set up agentcore websearch', 'create the gateway', 'tear down agentcore', 'delete the gateway'.
---

# AgentCore Web Search — full lifecycle

Search the web using the **AgentCore Web Search** tool through a private MCP gateway
in the user's AWS account, and manage that gateway's lifecycle. Authentication is
**local AWS credentials (SigV4/IAM)** — no API keys or tokens. Results are grounded,
cited, and current.

This skill covers four operations: **status → setup → search → teardown**.

## Resolve the repo directory first

Every command below runs from the `agentcore-websearch` repo. Resolve it once:

```bash
DIR="${AGENTCORE_WEBSEARCH_DIR:-$HOME/agentcore-websearch}"
```

If that path doesn't exist, ask the user where the repo is checked out (or to clone
it) and set `AGENTCORE_WEBSEARCH_DIR` accordingly. Do not guess other paths.

## Prerequisites

- The `agentcore-websearch` repo checked out locally (contains `setup.sh`,
  `teardown.sh`, `websearch`).
- AWS credentials available (an `AWS_PROFILE` or the default credential chain) with
  permission to create IAM roles and AgentCore gateways.
- **AWS CLI v2 ≥ 2.35.0** (setup needs the gateway `connector` target shape).
- **Python 3.9+** with `boto3` (for the search CLI only).

---

## 0. Check status (always safe — do this first)

Before searching or setting up, determine whether the gateway already exists. This
is read-only and never needs confirmation.

```bash
DIR="${AGENTCORE_WEBSEARCH_DIR:-$HOME/agentcore-websearch}"
# Is the CLI already configured?
[ -f "$DIR/.env" ] && grep -q AGENTCORE_GATEWAY_URL "$DIR/.env" && echo "configured (.env present)" || echo "not configured"
# Does a gateway exist in the account?
aws bedrock-agentcore-control list-gateways --region us-east-1 \
  --query "items[?name=='WebSearchGateway'].{id:gatewayId,status:status}" --output table
```

- **Configured + gateway READY** → go straight to **§2 Search**.
- **Not configured / no gateway** → propose **§1 Setup** (with confirmation).

---

## 1. Setup — creates billable AWS resources ⚠️ CONFIRM FIRST

> [!IMPORTANT]
> `setup.sh` **creates real AWS resources** (an IAM role, an AgentCore Gateway, and
> a web-search target) and Web Search is **billed at ~$7 per 1,000 queries**.
> **You MUST get the user's explicit agreement before running it.** State exactly
> what will be created and the cost, then wait for a clear "yes".

What setup creates (all in `us-east-1`):
1. IAM service role `AgentCoreWebSearchGatewayRole` (assumed by the gateway at
   query time to call the connector).
2. AgentCore Gateway `WebSearchGateway` with `AWS_IAM` inbound auth.
3. A `web-search` connector target exposing the `WebSearch` tool.

After the user agrees:

```bash
DIR="${AGENTCORE_WEBSEARCH_DIR:-$HOME/agentcore-websearch}"
# Pass the user's profile if they use one:
AWS_PROFILE=<their-profile> "$DIR/setup.sh"
```

`setup.sh` is **idempotent** (reuses existing role/gateway/target) and writes the
gateway URL to `$DIR/.env`. Optional overrides: `REGION`, `GATEWAY_NAME`,
`ROLE_NAME`, `TARGET_NAME` (must match at teardown).

Then install the Python dependency for the search CLI (once):

```bash
cd "$DIR" && python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
```

---

## 2. Search — the everyday operation

```bash
DIR="${AGENTCORE_WEBSEARCH_DIR:-$HOME/agentcore-websearch}"
"$DIR/websearch" "<search query>"
```

Options:
- `--max-results N` — number of results, 1–25 (default 10)
- `--json` — raw MCP result JSON (parse `content[0].text` → `results[]` with
  fields `text`, `url`, `title`, `publishedDate`)
- `--list-tools` — show the gateway's tools (diagnostic)

The wrapper reads `AGENTCORE_GATEWAY_URL` from `$DIR/.env` (written by setup), or
from the environment if exported.

### Search workflow

1. Formulate a focused query (**must be ≤ 200 characters**).
2. Run the wrapper with an appropriate `--max-results`.
3. Read the printed results (title, URL, publication date, snippet).
4. **Always cite sources** (title + URL) in your answer — an AWS acceptable-use
   requirement for AgentCore Web Search.

### Examples

```bash
DIR="${AGENTCORE_WEBSEARCH_DIR:-$HOME/agentcore-websearch}"
"$DIR/websearch" "latest TypeScript release"
"$DIR/websearch" "AWS re:Invent 2026 keynotes" --max-results 15 --json
```

---

## 3. Teardown — destroys AWS resources ⚠️ CONFIRM FIRST

> [!IMPORTANT]
> `teardown.sh` **permanently deletes** the web-search target, the gateway, and the
> IAM role created by setup. **You MUST get the user's explicit agreement before
> running it.** Confirm they want the resources destroyed; after teardown, searching
> will fail until setup is run again.

After the user agrees:

```bash
DIR="${AGENTCORE_WEBSEARCH_DIR:-$HOME/agentcore-websearch}"
AWS_PROFILE=<their-profile> "$DIR/teardown.sh"
```

If setup used custom names, pass the same `GATEWAY_NAME`/`ROLE_NAME`/`TARGET_NAME`
so teardown targets the right resources. Optionally also remove local artifacts:

```bash
rm -rf "$DIR/.venv" "$DIR/.env"
```

Verify nothing remains:

```bash
aws bedrock-agentcore-control list-gateways --region us-east-1 \
  --query "items[?name=='WebSearchGateway'].gatewayId" --output text
# (empty output = fully torn down)
```

---

## Confirmation policy (do not skip)

- **Read-only** (status checks, `list-gateways`, `--list-tools`, searching an
  already-configured gateway): run without asking.
- **`setup.sh`**: ask first — it creates billable resources.
- **`teardown.sh`**: ask first — it deletes resources irreversibly.
- When in doubt, describe the action and its cost/impact, then wait for a clear yes.

## Notes & limits

- **Region:** the gateway lives in `us-east-1`; the CLI signs for the host region
  automatically, so a different `AWS_REGION` in the shell is fine.
- **Cost:** ~$7 per 1,000 queries (each search = one query). The gateway/role/target
  themselves have no standing charge, but leaving them up is harmless if unused.
- **Auto-retry:** the CLI re-signs and retries transient `401/403/429/5xx` responses
  up to 5 times with backoff. If an error still surfaces, it's a real failure:
  - `401 Authentication error` → AWS credentials missing/expired (refresh SSO/profile).
  - `403 Insufficient permissions` → caller lacks `bedrock-agentcore:InvokeGateway`.
  - `Execution role is not authorized for connector` → gateway service-role policy
    issue (infra, not the caller).
  - `AGENTCORE_GATEWAY_URL is not set` → run §1 Setup, or export the URL.
