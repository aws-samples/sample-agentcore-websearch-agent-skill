#!/usr/bin/env python3
"""
agentcore-websearch — search the web via an AWS Bedrock AgentCore Gateway from the
CLI, using your local AWS credentials (SigV4 / IAM). No API keys or bearer tokens.

This is a thin client built directly on AWS's `mcp-proxy-for-aws` *library*:
`aws_iam_streamablehttp_client` opens a SigV4-signed, Streamable-HTTP MCP connection
to the gateway, and the official `mcp` SDK's `ClientSession` drives the protocol
(`initialize`, `tools/list`, `tools/call`). All signing and transport live in those
libraries — there is no hand-rolled SigV4 code and no subprocess/proxy to spawn.

Usage:
  export AGENTCORE_GATEWAY_URL="https://<gateway-id>.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
  export AWS_PROFILE=your-profile            # optional; default credential chain otherwise
  ./agentcore_websearch.py "your search query"
  ./agentcore_websearch.py "latest python release" --max-results 5
  ./agentcore_websearch.py "aws news" --json          # raw tool result
  ./agentcore_websearch.py --list-tools               # tools/list

Config resolution (highest first):
  --gateway-url flag  >  AGENTCORE_GATEWAY_URL env   (required — no built-in default)
  --region flag       >  region parsed from gateway URL  >  AWS_REGION  >  us-east-1
  --profile flag      >  AWS_PROFILE env  >  default credential chain
"""
import argparse
import asyncio
import json
import os
import re
import sys
import urllib.parse

try:
    from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client
    from mcp import ClientSession
except ImportError:
    sys.exit(
        "ERROR: mcp-proxy-for-aws is required.  pip install -r requirements.txt "
        "(or: pip install mcp-proxy-for-aws)"
    )

SERVICE = "bedrock-agentcore"
TOOL_NAME = "WebSearch"

# The gateway endpoint must be an HTTPS AgentCore Gateway host. We validate it before
# connecting so a malformed or unexpected value fails fast with a clear message (and
# can't point the client at an unintended host or a non-https scheme).
GATEWAY_HOST_RE = re.compile(
    r"^[a-z0-9-]+\.gateway\.bedrock-agentcore\.[a-z0-9-]+\.amazonaws\.com$"
)


class WebSearchError(RuntimeError):
    pass


def validate_url(url):
    """Reject anything that is not an HTTPS AgentCore Gateway URL."""
    if not url:
        raise WebSearchError("gateway URL is empty")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise WebSearchError(
            f"gateway URL must use https, got '{parsed.scheme or url}://...'"
        )
    if not parsed.hostname or not GATEWAY_HOST_RE.match(parsed.hostname):
        raise WebSearchError(
            "gateway URL host is not an AgentCore Gateway endpoint "
            "(expected <id>.gateway.bedrock-agentcore.<region>.amazonaws.com): "
            f"{parsed.hostname or url}"
        )
    return url


def region_from_url(url):
    """Extract the AWS region embedded in a gateway host, or None."""
    m = re.search(r"gateway\.bedrock-agentcore\.([a-z0-9-]+)\.amazonaws\.com", url)
    return m.group(1) if m else None


def resolve_tool_name(names):
    """The gateway namespaces tools as `<target>___WebSearch`; find it."""
    for n in names:
        if n == TOOL_NAME or n.endswith("___" + TOOL_NAME):
            return n
    for n in names:
        if TOOL_NAME.lower() in n.lower():
            return n
    if names:
        return names[0]
    raise WebSearchError("gateway exposes no tools")


async def _connect(url, region, profile):
    """Open a SigV4-signed MCP session to the gateway (async context managers)."""
    # aws_iam_streamablehttp_client resolves credentials from the given profile (or
    # the default chain) and SigV4-signs every request as `aws_service`.
    return aws_iam_streamablehttp_client(
        endpoint=url,
        aws_service=SERVICE,
        aws_region=region,
        aws_profile=profile,
    )


async def run_list_tools(url, region, profile):
    async with await _connect(url, region, profile) as (read, write, _sid):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            return result.tools


async def run_search(url, region, profile, query, max_results):
    args = {"query": query}
    if max_results is not None:
        args["maxResults"] = max_results
    async with await _connect(url, region, profile) as (read, write, _sid):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool_name = resolve_tool_name([t.name for t in tools.tools])
            return await session.call_tool(tool_name, args)


def result_payload(call_result):
    """Pull the structured JSON payload out of an MCP tool result."""
    # Prefer the structured field when the SDK populates it; else parse text blocks.
    structured = getattr(call_result, "structuredContent", None)
    if isinstance(structured, dict) and "results" in structured:
        return structured
    for block in getattr(call_result, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            try:
                parsed = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(parsed, dict) and "results" in parsed:
                return parsed
    return {}


def print_results(payload):
    results = payload.get("results", [])
    if not results:
        print("No results.")
        return
    for i, r in enumerate(results, 1):
        title = r.get("title") or "(untitled)"
        url = r.get("url", "")
        date = r.get("publishedDate", "")
        text = (r.get("text") or "").strip().replace("\n", " ")
        if len(text) > 280:
            text = text[:277] + "..."
        head = f"{i}. {title}"
        if date:
            head += f"  ({date})"
        print(head)
        if url:
            print(f"   {url}")
        if text:
            print(f"   {text}")
        print()



def _load_dotenv():
    """Load KEY=VALUE lines from a local .env (cwd, then this file's dir) into the
    environment, without overriding values already set. Keeps the packaged CLI
    self-sufficient — no bash wrapper needed. Lines starting with # are ignored."""
    import pathlib
    seen = set()
    for base in (pathlib.Path.cwd(), pathlib.Path(__file__).resolve().parent):
        env_path = base / ".env"
        if env_path in seen or not env_path.is_file():
            continue
        seen.add(env_path)
        for raw in env_path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


def main():
    _load_dotenv()
    p = argparse.ArgumentParser(
        prog="agentcore-websearch",
        description="Search the web via AWS Bedrock AgentCore Web Search (IAM/SigV4), "
                    "using the mcp-proxy-for-aws library.",
    )
    p.add_argument("query", nargs="?", help="search query (<=200 chars)")
    p.add_argument("-n", "--max-results", type=int, default=10,
                   help="max results 1-25 (default 10)")
    p.add_argument("--json", action="store_true", help="print raw tool result JSON")
    p.add_argument("--list-tools", action="store_true", help="list gateway tools and exit")
    p.add_argument("--gateway-url",
                   default=os.environ.get("AGENTCORE_GATEWAY_URL"),
                   help="AgentCore Gateway MCP URL (or set AGENTCORE_GATEWAY_URL)")
    p.add_argument("--region",
                   default=os.environ.get("AWS_REGION")
                   or os.environ.get("AWS_DEFAULT_REGION"))
    p.add_argument("--profile", default=os.environ.get("AWS_PROFILE"))
    args = p.parse_args()

    if not args.gateway_url:
        p.error("no gateway URL: set AGENTCORE_GATEWAY_URL or pass --gateway-url "
                "(e.g. https://<gateway-id>.gateway.bedrock-agentcore."
                "us-east-1.amazonaws.com/mcp)")
    if args.query and len(args.query) > 200:
        p.error("query must be <= 200 characters")
    if not args.list_tools and not args.query:
        p.error("a query is required (or use --list-tools)")
    if not 1 <= args.max_results <= 25:
        p.error("--max-results must be between 1 and 25")

    try:
        url = validate_url(args.gateway_url)
        region = region_from_url(url) or args.region or "us-east-1"

        if args.list_tools:
            tools = asyncio.run(run_list_tools(url, region, args.profile))
            print(json.dumps(
                {"tools": [
                    {"name": t.name,
                     "description": getattr(t, "description", None),
                     "inputSchema": getattr(t, "inputSchema", None)}
                    for t in tools
                ]},
                indent=2, default=str))
            return

        result = asyncio.run(run_search(url, region, args.profile,
                                        args.query, args.max_results))
    except WebSearchError as e:
        sys.exit(f"ERROR: {e}")
    except Exception as e:  # surface signing/transport/connection failures cleanly
        sys.exit(f"ERROR: {type(e).__name__}: {e}")

    payload = result_payload(result)
    if args.json:
        print(json.dumps(payload, indent=2, default=str))
        return
    print_results(payload)


if __name__ == "__main__":
    main()
