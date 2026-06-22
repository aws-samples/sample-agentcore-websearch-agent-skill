# AgentCore Web Search CLI (IAM / SigV4)

Call the **AWS Bedrock AgentCore Web Search** tool from the command line using your
**local AWS credentials** — no API keys, no bearer tokens. Includes a from-scratch
setup script and a [Claude Code](https://docs.claude.com/claude-code) skill.

AgentCore Web Search is a fully managed, MCP-compliant web search tool. Queries are
served entirely within AWS (zero data egress), and results come back with titles,
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
your machine                              AWS account (us-east-1)
┌──────────────┐                       ┌──────────────────────────┐                  ┌──────────────┐
│ websearch CLI│   MCP over HTTPS       │  AgentCore Gateway        │   assume role    │ web-search   │
│              │   (JSON-RPC 2.0:       │  MCP endpoint  /mcp       │ ───────────────▶ │ connector    │
│ agentcore_   │    initialize,         │  authorizer: AWS_IAM      │  InvokeWebSearch │ (managed     │
│ websearch.py │    tools/list,         │                           │                  │  web index)  │
│  + requests  │    tools/call)         │                           │                  │              │
│              │ ─────────────────────▶ │                           │                  │              │
│              │   SigV4-signed (IAM)   │                           │                  │              │
└──────────────┘                       └──────────────────────────┘                  └──────────────┘
```

The CLI is a minimal **MCP (Model Context Protocol) client**: it speaks JSON-RPC 2.0
over Streamable HTTP to the gateway's `/mcp` endpoint — an `initialize` handshake
(carrying the `Mcp-Session-Id`), then `tools/list` and `tools/call` for the
`WebSearch` tool. Every one of those HTTP(S) requests is SigV4-signed.

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
  `connector` target shape (`setup.sh` checks and tells you to upgrade).
- **Python 3.9+** — only for running the search CLI (`agentcore_websearch.py`),
  which uses `boto3` to SigV4-sign requests. Not needed to create the infrastructure.
- Access to Amazon Bedrock AgentCore in `us-east-1`.
- `git` to clone this repository.

## Get the code

Clone the repository, then move into the runnable bundle. **All runtime files live in
`skills/agentcore-websearch/`** (the same self-contained folder you can later import
as a Claude Code skill — see [Use it as a Claude Code skill](#use-it-as-a-claude-code-skill)).

```bash
git clone https://github.com/aws-samples/agentcore-websearch.git
cd agentcore-websearch/skills/agentcore-websearch
```

> Every command in the steps below is run **from `skills/agentcore-websearch/`**.

## Two ways to use it

1. **Run it locally** — follow steps 1–3 below to create the gateway and search from
   your terminal with the `websearch` CLI.
2. **Use it as a Claude Code skill** — import the bundle so Claude Code can run the
   whole lifecycle for you. See [Use it as a Claude Code skill](#use-it-as-a-claude-code-skill).

Both paths share the same setup (steps 1–2); the skill just lets Claude drive it.

## 1. Create the infrastructure

The setup script creates the IAM service role, the gateway (with `AWS_IAM` inbound
auth), and the web-search target — then prints the gateway URL.

```bash
# uses your current AWS credentials / AWS_PROFILE
AWS_PROFILE=your-profile ./setup.sh
```

Useful overrides (all optional):

```bash
GATEWAY_NAME=MyWebSearchGateway \
ROLE_NAME=MyWebSearchGatewayRole \
REGION=us-east-1 \
AWS_PROFILE=your-profile ./setup.sh
```

At the end it prints an `export AGENTCORE_GATEWAY_URL=...` line and writes a local
`.env` (in the bundle folder).

## 2. Configure the CLI

`setup.sh` already writes `.env`; if you need to do it manually, copy the example and
fill in the gateway URL from step 1:

```bash
cp .env.example .env
# edit .env -> AGENTCORE_GATEWAY_URL=...   (and optionally AWS_PROFILE=...)
```

Install the Python dependency (a virtualenv is recommended):

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```

> `boto3` here is only used by the search CLI to SigV4-sign requests; any recent
> version works. (Creating the infrastructure is done entirely by `setup.sh` via the
> AWS CLI — no Python or boto3 involved.)

## 3. Trigger and test the search locally

From `skills/agentcore-websearch/`, run the `websearch` wrapper. It loads
`AGENTCORE_GATEWAY_URL` (and optionally `AWS_PROFILE`) from the `.env` that `setup.sh`
wrote, signs the request with your local AWS credentials, and prints ranked results.

**Smoke test** — confirm the gateway and tool are reachable:

```bash
./websearch --list-tools
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
./websearch "latest AWS AgentCore announcement"
./websearch "newest python version" --max-results 5
./websearch "aws news" --json          # raw MCP result for parsing
```

A successful search prints numbered results — each with a title, URL, publication
date, and snippet. For example:

```
1. Introducing Web Search on Amazon Bedrock AgentCore  (2026-06-18)
   https://aws.amazon.com/blogs/machine-learning/introducing-web-search-on-amazon-bedrock-agentcore/
   Web Search on Amazon Bedrock AgentCore, now generally available, ...
```

**Direct Python invocation** (without the wrapper / `.env`):

```bash
. .venv/bin/activate
export AGENTCORE_GATEWAY_URL="https://<gateway-id>.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
python agentcore_websearch.py "your query" --max-results 10
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

The repo root holds the README and open-source governance files. Everything runnable
lives in the self-contained skill bundle, so copying that one folder is all you need:

```
.                                   # README, LICENSE, NOTICE, CONTRIBUTING, CODE_OF_CONDUCT
└── skills/agentcore-websearch/     # ← self-contained bundle (also the Claude Code skill)
    ├── SKILL.md                    # Claude Code skill definition (full lifecycle)
    ├── setup.sh                    # creates IAM role + gateway + web-search target
    ├── teardown.sh                 # deletes everything setup.sh created
    ├── websearch                   # bash wrapper; loads .env, requires AGENTCORE_GATEWAY_URL
    ├── agentcore_websearch.py      # MCP client (SigV4-signs initialize + tools/call, auto-retries)
    ├── iam/*.template.json         # IAM trust/permission templates (placeholders filled by setup.sh)
    ├── requirements.txt            # boto3 (runtime, for the search CLI only)
    └── .env.example                # copy to .env and fill in
```

## Use it as a Claude Code skill

Instead of running the CLI yourself, you can let [Claude Code](https://docs.claude.com/claude-code)
drive the whole lifecycle. Install the skill by copying the bundle into your Claude
Code skills directory:

```bash
# from the cloned repo root
cp -r skills/agentcore-websearch ~/.claude/skills/
```

Because the folder is self-contained (scripts, Python client, IAM templates, and
`requirements.txt` all live inside it), that single `cp -r` is the entire install —
no other files from the repo are needed. (You still clone the repo first to get the
folder to copy.)

Once installed, the skill manages the **full lifecycle** — checking status, creating
the gateway (`setup.sh`), searching, and tearing it down (`teardown.sh`). It asks for
your explicit confirmation before any setup or teardown, since those create or delete
billable AWS resources; searching an already-configured gateway runs without prompting.

Then ask Claude Code to:

- *"set up agentcore websearch"* — creates the gateway (after confirming)
- *"search the web with agentcore for …"* — runs a query
- *"tear down agentcore websearch"* — deletes the resources (after confirming)

See [`skills/agentcore-websearch/SKILL.md`](skills/agentcore-websearch/SKILL.md) for
the full skill instructions.

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
avoid any further charges. Run from `skills/agentcore-websearch/`:

```bash
AWS_PROFILE=your-profile ./teardown.sh
```

Also remove local artifacts if you no longer need them:

```bash
rm -rf .venv .env
```

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for information on
reporting a potential security issue. Do not create a public GitHub issue for
security findings.

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). This project
follows the [Amazon Open Source Code of Conduct](CODE_OF_CONDUCT.md).

## License

This library is licensed under the MIT-0 License. See the [LICENSE](LICENSE) file.
