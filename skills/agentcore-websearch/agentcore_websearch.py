#!/usr/bin/env python3
"""
agentcore-websearch — call the AWS Bedrock AgentCore Web Search tool from the CLI
using your local AWS credentials (SigV4 / IAM). No bearer tokens required.

The gateway is an MCP (Model Context Protocol) server reachable over Streamable
HTTP. This client:
  1. SigV4-signs every request as service "bedrock-agentcore" using boto3/botocore
     credentials resolved from the standard chain (env, AWS_PROFILE, ~/.aws, role).
  2. Performs the MCP `initialize` handshake, carrying the Mcp-Session-Id header.
  3. Calls `tools/call` for the `WebSearch` tool.
  4. Parses JSON or text/event-stream (SSE) responses.

Usage:
  export AGENTCORE_GATEWAY_URL="https://<gateway-id>.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
  export AWS_PROFILE=your-profile            # optional; default credential chain otherwise
  ./agentcore_websearch.py "your search query"
  ./agentcore_websearch.py "latest python release" --max-results 5
  ./agentcore_websearch.py "aws news" --json          # raw MCP result
  ./agentcore_websearch.py --list-tools               # tools/list

Config resolution order (highest first):
  --gateway-url flag  >  AGENTCORE_GATEWAY_URL env   (required — no built-in default)
  --region flag       >  region parsed from gateway URL  >  AWS_REGION  >  us-east-1
  --profile flag      >  AWS_PROFILE env  >  default credential chain
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.parse

try:
    import requests
except ImportError:
    sys.exit("ERROR: requests is required.  pip install requests")

try:
    from botocore.session import Session
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest
except ImportError:
    sys.exit("ERROR: botocore is required.  pip install botocore>=1.43")

SERVICE = "bedrock-agentcore"
TOOL_NAME = "WebSearch"
PROTOCOL_VERSION = "2025-06-18"

# The gateway endpoint must be an HTTPS AgentCore Gateway host. We validate the
# configured URL before making any request. Although the client uses requests
# (HTTP/HTTPS only), validating here keeps the guarantee explicit and local — a value like
# "file:///etc/passwd" would otherwise be read as a local file (SSRF / local file
# read). Restricting to https on a *.gateway.bedrock-agentcore.<region>.amazonaws.com
# host closes that vector.
GATEWAY_HOST_RE = re.compile(
    r"^[a-z0-9-]+\.gateway\.bedrock-agentcore\.[a-z0-9-]+\.amazonaws\.com$"
)


class MCPError(RuntimeError):
    pass


class AgentCoreWebSearch:
    def __init__(self, gateway_url, region, profile=None):
        self.url = self._validate_url(gateway_url)
        self.region = region
        sess = Session(profile=profile) if profile else Session()
        self.creds = sess.get_credentials()
        if self.creds is None:
            raise MCPError(
                "No AWS credentials found. Set AWS_PROFILE or run `aws configure`."
            )
        # The SigV4 signing region MUST match the gateway host's region, which is
        # encoded in the URL (…gateway.bedrock-agentcore.<region>.amazonaws.com).
        # An explicit --region/AWS_REGION that disagrees with the host would be
        # signed for the wrong region and rejected ("Invalid credentials"), so the
        # host region always wins when it can be parsed from the URL.
        host_region = self._region_from_url(gateway_url)
        self.region = (
            host_region
            or region
            or sess.get_config_variable("region")
            or "us-east-1"
        )
        self._session_id = None
        self._next_id = 0

    @staticmethod
    def _validate_url(url):
        """Reject anything that is not an HTTPS AgentCore Gateway URL.

        The client uses the requests library (HTTP/HTTPS only), but we still pin
        the URL to https on a known AgentCore Gateway host as defence in depth, so
        a malicious or misconfigured AGENTCORE_GATEWAY_URL cannot redirect requests
        to an unintended host or downgrade the scheme.
        """
        if not url:
            raise MCPError("gateway URL is empty")
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https":
            raise MCPError(
                f"gateway URL must use https, got '{parsed.scheme or url}://...'"
            )
        if not parsed.hostname or not GATEWAY_HOST_RE.match(parsed.hostname):
            raise MCPError(
                "gateway URL host is not an AgentCore Gateway endpoint "
                "(expected <id>.gateway.bedrock-agentcore.<region>.amazonaws.com): "
                f"{parsed.hostname or url}"
            )
        return url

    @staticmethod
    def _region_from_url(url):
        """Extract the AWS region embedded in a gateway host, or None."""
        m = re.search(r"gateway\.bedrock-agentcore\.([a-z0-9-]+)\.amazonaws\.com", url)
        return m.group(1) if m else None

    def _rpc_id(self):
        self._next_id += 1
        return self._next_id

    # Transient auth/throttle/server statuses worth retrying. The gateway
    # intermittently returns 401/403 "Authentication/Authorization error" right
    # after a token rotation or cold path even when credentials are valid, so we
    # re-sign (fresh X-Amz-Date, refreshed creds) and retry with backoff.
    _RETRY_STATUSES = {401, 403, 429, 500, 502, 503, 504}
    _MAX_ATTEMPTS = 5

    def _post(self, payload):
        """SigV4-sign and POST one JSON-RPC message; return parsed result dict."""
        body = json.dumps(payload).encode("utf-8")
        last_err = None
        raw = ""
        ctype = ""
        for attempt in range(1, self._MAX_ATTEMPTS + 1):
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }
            if self._session_id:
                headers["Mcp-Session-Id"] = self._session_id

            # SigV4 sign (re-signed each attempt → fresh date + refreshed creds)
            aws_req = AWSRequest(method="POST", url=self.url, data=body, headers=headers)
            SigV4Auth(self.creds, SERVICE, self.region).add_auth(aws_req)
            signed = dict(aws_req.headers)

            # Use requests (HTTP/HTTPS only) rather than urllib, which also honours
            # file://, ftp://, etc. self.url is additionally validated by
            # _validate_url(), so this is defence in depth.
            try:
                resp = requests.post(
                    self.url, data=body, headers=signed, timeout=60
                )
            except requests.exceptions.RequestException as e:
                last_err = MCPError(f"connection error: {e}")
                if attempt < self._MAX_ATTEMPTS:
                    time.sleep(min(2 ** (attempt - 1), 8))
                    continue
                raise last_err from None

            if resp.status_code >= 400:
                last_err = MCPError(
                    f"HTTP {resp.status_code} {resp.reason}: {resp.text}"
                )
                if resp.status_code in self._RETRY_STATUSES \
                        and attempt < self._MAX_ATTEMPTS:
                    time.sleep(min(2 ** (attempt - 1), 8))  # 1,2,4,8s backoff
                    continue
                raise last_err from None

            sid = resp.headers.get("Mcp-Session-Id")
            if sid:
                self._session_id = sid
            ctype = resp.headers.get("Content-Type", "")
            raw = resp.text
            break

        # Notifications (no id) return empty/202 — nothing to parse.
        if not raw.strip():
            return None

        msg = self._parse_body(ctype, raw)
        if msg is None:
            return None
        if "error" in msg:
            raise MCPError(f"MCP error: {json.dumps(msg['error'])}")
        return msg.get("result")

    @staticmethod
    def _parse_body(ctype, raw):
        """Handle both application/json and text/event-stream (SSE)."""
        if "text/event-stream" in ctype:
            for line in raw.splitlines():
                line = line.strip()
                if line.startswith("data:"):
                    data = line[len("data:"):].strip()
                    if data and data != "[DONE]":
                        try:
                            return json.loads(data)
                        except json.JSONDecodeError:
                            continue
            return None
        return json.loads(raw)

    def initialize(self):
        result = self._post({
            "jsonrpc": "2.0",
            "id": self._rpc_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "agentcore-websearch-cli", "version": "1.0.0"},
            },
        })
        # best-effort initialized notification
        try:
            self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except MCPError:
            pass
        return result

    def list_tools(self):
        return self._post({
            "jsonrpc": "2.0", "id": self._rpc_id(), "method": "tools/list", "params": {},
        })

    def resolve_tool_name(self):
        """Find the WebSearch tool's fully-qualified name.

        AgentCore Gateway namespaces tools as `<target-name>___<ToolName>`, so the
        WebSearch tool is exposed as e.g. `web-search-tool___WebSearch` rather than
        bare `WebSearch`. Discover it instead of hardcoding the prefix.
        """
        listing = self.list_tools() or {}
        names = [t.get("name", "") for t in listing.get("tools", [])]
        for n in names:
            if n == TOOL_NAME or n.endswith("___" + TOOL_NAME):
                return n
        # fall back to anything containing WebSearch, else the bare name
        for n in names:
            if TOOL_NAME.lower() in n.lower():
                return n
        return TOOL_NAME

    def search(self, query, max_results=None, tool_name=None):
        args = {"query": query}
        if max_results is not None:
            args["maxResults"] = max_results
        return self._post({
            "jsonrpc": "2.0",
            "id": self._rpc_id(),
            "method": "tools/call",
            "params": {"name": tool_name or self.resolve_tool_name(), "arguments": args},
        })


def extract_results(call_result):
    """Pull the structured results[] out of an MCP tools/call response."""
    if not call_result:
        return []
    for block in call_result.get("content", []):
        if block.get("type") == "text":
            try:
                payload = json.loads(block["text"])
            except (json.JSONDecodeError, KeyError):
                continue
            if isinstance(payload, dict) and "results" in payload:
                return payload["results"]
    return []


def main():
    p = argparse.ArgumentParser(
        prog="agentcore-websearch",
        description="Search the web via AWS Bedrock AgentCore Web Search (IAM/SigV4).",
    )
    p.add_argument("query", nargs="?", help="search query (<=200 chars)")
    p.add_argument("-n", "--max-results", type=int, default=10,
                   help="max results 1-25 (default 10)")
    p.add_argument("--json", action="store_true", help="print raw MCP result JSON")
    p.add_argument("--list-tools", action="store_true", help="list gateway tools and exit")
    p.add_argument("--gateway-url",
                   default=os.environ.get("AGENTCORE_GATEWAY_URL"),
                   help="AgentCore Gateway MCP URL "
                        "(or set AGENTCORE_GATEWAY_URL)")
    p.add_argument("--region",
                   default=os.environ.get("AWS_REGION")
                   or os.environ.get("AWS_DEFAULT_REGION"))
    p.add_argument("--profile", default=os.environ.get("AWS_PROFILE"))
    args = p.parse_args()

    if not args.gateway_url:
        p.error("no gateway URL: set AGENTCORE_GATEWAY_URL or pass --gateway-url "
                "(e.g. https://<gateway-id>.gateway.bedrock-agentcore."
                "us-east-1.amazonaws.com/mcp)")
    if not args.list_tools and not args.query:
        p.error("a query is required (or use --list-tools)")
    if args.query and len(args.query) > 200:
        p.error("query must be <= 200 characters")
    if not 1 <= args.max_results <= 25:
        p.error("--max-results must be between 1 and 25")

    try:
        client = AgentCoreWebSearch(args.gateway_url, args.region, args.profile)
        client.initialize()

        if args.list_tools:
            tools = client.list_tools() or {}
            print(json.dumps(tools, indent=2))
            return

        result = client.search(args.query, args.max_results)
    except MCPError as e:
        sys.exit(f"ERROR: {e}")

    if args.json:
        print(json.dumps(result, indent=2))
        return

    results = extract_results(result)
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


if __name__ == "__main__":
    main()
