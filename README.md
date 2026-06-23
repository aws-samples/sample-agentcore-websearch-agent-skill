# AgentCore Web Search CLI (IAM / SigV4)

This project **creates an Amazon Bedrock AgentCore Gateway and connects the managed
Web Search tool to it**, then lets you call that tool from the command line using your
**local AWS credentials** — no API keys, no bearer tokens. It ships a from-scratch
setup script (gateway + IAM role + web-search target) at the repo root, plus a
search-only [Claude Code](https://docs.claude.com/claude-code) skill in
`skills/agentcore-websearch/`. See [AGENTS.md](AGENTS.md) for the setup/teardown guide.

Because the gateway speaks the **Model Context Protocol (MCP)** and authenticates
callers with **IAM (SigV4)**, it is a good fit for grounding IAM-authenticated,
Bedrock-hosted agents in live web results — for example:

- **Claude Code on Bedrock** — give the coding agent current web knowledge.
- **Codex on Bedrock** — same, for OpenAI-style coding agents running against Bedrock.
- **Cowork (3P) on Bedrock** — let third-party Cowork agents search the web through
  your own gateway, with all queries staying inside your AWS account.

AgentCore Web Search itself is a fully managed, MCP-compliant web search tool. Queries
are served entirely within AWS (zero data egress), and results come back with titles,
URLs, snippets, and publication dates. Pricing is ~$7 per 1,000 queries.

> **Region:** Web Search is currently available only in `us-east-1`.

> [!WARNING]
> **Not for production use.** This repository is a sample / demonstration intended
> for learning and experimentation. It has not been hardened for production
> workloads — it omits production concerns such as least-privilege role scoping,
> monitoring/alarming, rate limiting, multi-region/HA, automated credential
> rotation, and comprehensive error handling. Review, adapt, and test it against
> your own security and operational requirements before any real-world use. It is
> provided "as is" without warranty (see [LICENSE](LICENSE)).

## How it works

```
your machine                                          AWS account (us-east-1)
┌────────────────────────────────┐   MCP over HTTPS    ┌──────────────────────┐   assume role    ┌──────────────┐
│ websearch CLI (this repo)       │   (JSON-RPC 2.0:    │  AgentCore Gateway   │ ───────────────▶ │ web-search   │
│  agentcore-websearch (package)  │    initialize,      │  MCP endpoint  /mcp  │  InvokeWebSearch │ connector    │
│  • mcp_proxy_for_aws library    │ ──────────────────▶ │  authorizer: AWS_IAM │                  │ (managed     │
│    (SigV4 streamable-http)      │    tools/list,      │                      │                  │  web index)  │
│  • mcp SDK ClientSession        │    tools/call)      │                      │                  │              │
└────────────────────────────────┘   SigV4-signed      └──────────────────────┘                  └──────────────┘
```

The CLI is a thin client built on AWS's
[`mcp-proxy-for-aws`](https://pypi.org/project/mcp-proxy-for-aws/) **library**: it
calls `aws_iam_streamablehttp_client(...)` to open a **SigV4-signed, Streamable-HTTP
MCP connection** to the gateway's `/mcp` endpoint, and drives the protocol
(`initialize`, `tools/list`, `tools/call`) with the official `mcp` SDK's
`ClientSession`. Credential resolution, region signing, and transport all live in
those libraries — the connection runs **in-process**, with no subprocess to spawn and
no hand-rolled signing code.

> A Bedrock-hosted agent (Claude Code / Codex / Cowork on Bedrock) reaches the same
> gateway by registering `mcp-proxy-for-aws` as a stdio MCP **server** — see
> [Connect a Bedrock-hosted agent](#connect-a-bedrock-hosted-agent-claude-code--codex--cowork-on-bedrock).
> This CLI uses the same package as a library instead.

- **Inbound** (CLI → gateway): each MCP HTTPS request is SigV4-signed as service
  `bedrock-agentcore`. The signing region is derived from the gateway hostname, so a
  mismatched `AWS_REGION` in your shell won't break it. Your IAM principal needs
  `bedrock-agentcore:InvokeGateway` on the gateway.
- **Outbound** (gateway → connector): the gateway assumes a service role that grants
  `bedrock-agentcore:InvokeWebSearch`, then calls the managed web-search connector
  entirely within AWS.

## Prerequisites

- An AWS account and credentials (`aws configure` or SSO profile) with permission to
  create IAM roles and AgentCore gateways.
- **AWS CLI v2 >= 2.35.0** and `bash` — earlier CLI versions lack the gateway
  `connector` target shape (`setup.sh` checks and tells you to upgrade). Setup deploys
  an **AWS CloudFormation** stack.
- **Python 3.9+** — only for running the search CLI. Its one dependency is
  `mcp-proxy-for-aws` (which brings `boto3`, `botocore`, and the `mcp` SDK). Not
  needed to create the infrastructure.
- Access to Amazon Bedrock AgentCore in `us-east-1`.
- `git` to clone this repository.

## Get the code

```bash
git clone https://github.com/aws-samples/agentcore-websearch.git
cd agentcore-websearch
```

**Layout in brief:** provisioning lives at the **project root** (`setup.sh`,
`teardown.sh`, `iam/`); the **search skill** lives in `skills/agentcore-websearch/`.
The full setup/teardown guide is [AGENTS.md](AGENTS.md).

## Two ways to use it

1. **Run it locally** — provision the gateway (step 1, from the repo root), then
   search from your terminal with the `websearch` CLI (step 3).
2. **Use it as a Claude Code skill** — import `skills/agentcore-websearch/` so Claude
   Code can search for you. See [Use it as a Claude Code skill](#use-it-as-a-claude-code-skill).
   (Provisioning is still a one-time step — see [AGENTS.md](AGENTS.md).)

## 1. Create the infrastructure (from the repo root)

`setup.sh` deploys the CloudFormation stack `agentcore-websearch`
([`cfn/agentcore-websearch.yaml`](cfn/agentcore-websearch.yaml): IAM service role +
AgentCore Gateway with `AWS_IAM` inbound auth + web-search target), then prints the
gateway URL **and writes it into `skills/agentcore-websearch/.env`** so the search CLI
works immediately.

```bash
# from the repo root; uses your current AWS credentials / AWS_PROFILE
AWS_PROFILE=your-profile ./setup.sh
```

Useful overrides (all optional — pass the same `STACK_NAME` to `teardown.sh`):

```bash
STACK_NAME=agentcore-websearch \
GATEWAY_NAME=MyWebSearchGateway \
TARGET_NAME=web-search-tool \
REGION=us-east-1 \
AWS_PROFILE=your-profile ./setup.sh
```

See [AGENTS.md](AGENTS.md) for the full setup/teardown guide (what gets created, the
confirmation policy, and how auth works).

## 2. Install the search CLI dependency

```bash
cd skills/agentcore-websearch
python -m venv .venv && . .venv/bin/activate
pip install .            # installs the `agentcore-websearch` console command
```

> The CLI is a proper Python package (`pyproject.toml`); `pip install .` (or
> `pipx install .`) gives you an `agentcore-websearch` command. Its only dependency is
> [`mcp-proxy-for-aws`](https://pypi.org/project/mcp-proxy-for-aws/) (which brings
> `boto3`, `botocore`, and the `mcp` SDK); the CLI imports its
> `aws_iam_streamablehttp_client` to do the SigV4 signing and MCP transport in-process.
> `setup.sh` already wrote this folder's `.env`; to point at a different gateway, copy
> `.env.example` to `.env` and edit `AGENTCORE_GATEWAY_URL`.

## 3. Trigger and test the search locally

From `skills/agentcore-websearch/`, run the `websearch` wrapper. It loads
`AGENTCORE_GATEWAY_URL` (and optionally `AWS_PROFILE`) from the `.env` that `setup.sh`
wrote, opens a SigV4-signed MCP connection with your local AWS credentials, and prints ranked results.

**Smoke test** — confirm the gateway and tool are reachable:

```bash
agentcore-websearch --list-tools
```

Expected (the tool name is namespaced by the target):

```json
{
  "tools": [
    { "name": "web-search-tool___WebSearch",
      "inputSchema": { "type": "object",
        "properties": { "query": {"type": "string"},
                        "maxResults": {"type": "integer"} },
        "required": ["query"] } }
  ]
}
```

**Run searches:**

```bash
agentcore-websearch "latest AWS AgentCore announcement"
agentcore-websearch "newest python version" --max-results 5
agentcore-websearch "aws news" --json          # raw MCP result for parsing
```

A successful search prints numbered results — each with a title, URL, publication
date, and snippet. For example:

```
1. Introducing Web Search on Amazon Bedrock AgentCore  (2026-06-18)
   https://aws.amazon.com/blogs/machine-learning/introducing-web-search-on-amazon-bedrock-agentcore/
   Web Search on Amazon Bedrock AgentCore, now generally available, ...
```

**Run the module directly** (equivalent to the console command):

```bash
. .venv/bin/activate
export AGENTCORE_GATEWAY_URL="https://<gateway-id>.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
python -m agentcore_websearch.cli "your query" --max-results 10
```

**If a search fails**, the error usually tells you which credential is missing:

| Message | Cause | Fix |
|---|---|---|
| `AGENTCORE_GATEWAY_URL is not set` | no `.env` / env var | run step 1, or `cp .env.example .env` and fill it in |
| `401 Authentication error` | AWS credentials missing/expired | refresh your `AWS_PROFILE` / SSO login |
| `403 Insufficient permissions` | caller lacks `bedrock-agentcore:InvokeGateway` | grant it (admin creds already have it) |
| `Execution role is not authorized for connector` | gateway service-role policy | re-run `./setup.sh` to repair the role |

The CLI auto-retries transient `401/403/429/5xx` responses up to 5 times before
surfacing an error.

### Configuration reference

| Variable | Required | Purpose |
|---|---|---|
| `AGENTCORE_GATEWAY_URL` | yes | Gateway MCP endpoint (from `setup.sh`) |
| `AWS_PROFILE` | no | AWS profile; otherwise the default credential chain is used |
| `AWS_REGION` | no | Overridden by the region in the gateway URL anyway |

CLI flags `--gateway-url`, `--profile`, `--region` override the environment.

## Layout

**Provisioning lives at the project root; the search skill is self-contained in
`skills/agentcore-websearch/`.**

```
.                                   # README, AGENTS.md, LICENSE, NOTICE, CONTRIBUTING, CODE_OF_CONDUCT
├── AGENTS.md                       # full setup/teardown guide (provision from the repo root)
├── setup.sh                        # deploys the CloudFormation stack, writes the skill .env
├── teardown.sh                     # deletes the CloudFormation stack
├── cfn/agentcore-websearch.yaml    # CloudFormation: IAM role + Gateway + web-search target
└── skills/agentcore-websearch/     # ← search skill (copy this into ~/.claude/skills/)
    ├── SKILL.md                    # Claude Code skill definition (search only)
    ├── pyproject.toml              # packaging: installs the `agentcore-websearch` command
    ├── src/agentcore_websearch/    # the package (cli.py = entry point)
    ├── websearch                   # convenience wrapper around the installed CLI
    └── .env.example                # copy to .env and fill in (setup.sh writes .env here)
```

Setup/teardown (root) and search (skill) are separated on purpose: the skill you copy
into Claude Code can only **search** — it never creates or deletes AWS resources.

## Use it as a Claude Code skill

Instead of running the CLI yourself, you can let [Claude Code](https://docs.claude.com/claude-code)
run searches for you. Install the skill by copying the folder into your Claude
Code skills directory:

```bash
# from the cloned repo root
cp -r skills/agentcore-websearch ~/.claude/skills/
```

Because the folder is self-contained (the packaged CLI and its `pyproject.toml` all
live inside it), that single `cp -r` is the entire install — no other files from the
repo are needed. (You still clone the repo first to get the folder to copy, and run
`pip install .` in it.)

The skill is **search-only** — it does not create or delete AWS resources. Provision
the gateway once from the repo root (step 1, or [AGENTS.md](AGENTS.md)); `setup.sh`
writes the gateway URL into `skills/agentcore-websearch/.env`, so the copied skill
works as long as that `.env` (or an exported `AGENTCORE_GATEWAY_URL`) is present and
your AWS credentials can invoke the gateway.

Then ask Claude Code to *"search the web with agentcore for …"* and it runs a query.

See [`skills/agentcore-websearch/SKILL.md`](skills/agentcore-websearch/SKILL.md) for
the full skill instructions, and [AGENTS.md](AGENTS.md) for setup/teardown.

## Connect a Bedrock-hosted agent (Claude Code / Codex / Cowork on Bedrock)

You don't need this repo's CLI to use the gateway from an agent — any MCP client can
register AWS's `mcp-proxy-for-aws` as a **stdio MCP server** pointed at your gateway.
The proxy SigV4-signs every call with the agent host's IAM role, so an
IAM-authenticated, Bedrock-hosted agent gets web search with no extra credentials.

Example MCP server entry (the shape most clients accept; field names vary by client):

```json
{
  "mcpServers": {
    "agentcore-websearch": {
      "command": "uvx",
      "args": [
        "mcp-proxy-for-aws",
        "https://<gateway-id>.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp",
        "--region", "us-east-1"
      ]
    }
  }
}
```

- **Claude Code on Bedrock** — add it with
  `claude mcp add agentcore-websearch -- uvx mcp-proxy-for-aws <gateway-url> --region us-east-1`.
- **Codex on Bedrock** — add the same `command`/`args` under `mcp_servers` in your
  Codex config.
- **Cowork (3P) on Bedrock** — register the same stdio server; queries stay inside
  your AWS account via your own gateway.

The agent's IAM principal (or instance/role credentials) needs
`bedrock-agentcore:InvokeGateway` on the gateway, exactly like the CLI.

## ⚠️ Note on the InvokeWebSearch ARN

The AWS docs show `arn:aws:bedrock-agentcore::aws:tool/web-search.v1` (empty region),
which is **rejected** with "Execution role is not authorized for connector
web-search". The working ARN includes the region:

```
arn:aws:bedrock-agentcore:us-east-1:aws:tool/web-search.v1
```

`setup.sh` and the IAM templates use the correct form.

## Cleanup

Delete all resources created by `setup.sh` (the gateway, target, and IAM role) to
avoid any further charges. Run from the **repo root**:

```bash
AWS_PROFILE=your-profile ./teardown.sh
```

Also remove local artifacts if you no longer need them:

```bash
rm -rf skills/agentcore-websearch/.venv skills/agentcore-websearch/.env
```

See [AGENTS.md](AGENTS.md) for the full teardown guide.

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for information on
reporting a potential security issue. Do not create a public GitHub issue for
security findings.

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). This project
follows the [Amazon Open Source Code of Conduct](CODE_OF_CONDUCT.md).

## License

This library is licensed under the MIT-0 License. See the [LICENSE](LICENSE) file.
