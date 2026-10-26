"""
Minimal client for talking to an MCP server over "Streamable HTTP" transport
(a single POST endpoint, JSON-RPC 2.0 messages, optional SSE response).

This isn't LaunchPoint-specific — it just knows how to: initialize a session,
list available tools, and call one.
"""

import os
import json
import time
import random
import itertools
import email.utils
import requests

MCP_URL = os.environ["LAUNCHPOINT_MCP_URL"]
# Default key (Krea, micro1, Tab). Clients on another LaunchPoint account
# pass their own key to get_session().
API_KEY = os.environ.get("LAUNCHPOINT_API_KEY", "").strip()

_id_counter = itertools.count(1)

# A 429 is retried until a request has been tried this many times.
RATE_LIMIT_ATTEMPTS = 5
MAX_RETRY_WAIT_SECONDS = 60


def _retry_delay(resp: requests.Response, attempt: int) -> float:
    """Seconds to wait after a 429: the server's Retry-After if it sent one
    (seconds or an HTTP date), else exponential backoff (5s, 10s, 20s, 40s).
    Jitter keeps parallel jobs on the same key from retrying in lockstep."""
    delay = 5 * 2 ** attempt
    retry_after = resp.headers.get("Retry-After", "").strip()
    if retry_after.isdigit():
        delay = int(retry_after)
    elif retry_after:
        try:
            when = email.utils.parsedate_to_datetime(retry_after)
            delay = when.timestamp() - time.time()
        except (TypeError, ValueError):
            pass
    return min(max(delay, 0), MAX_RETRY_WAIT_SECONDS) + random.uniform(0, 2)


class MCPSession:
    def __init__(self, url: str, api_key: str):
        self.url = url
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        self.session_id = None

    def _post(self, payload: dict, retries: int = 3) -> dict:
        headers = dict(self.headers)
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id

        # Report runs now make dozens of calls (paginating list_posts/list_payouts),
        # and this endpoint occasionally stalls past 30s on an individual request —
        # retry transient network/timeout errors rather than failing the whole run.
        # Clients sharing an API key also get rate limited (429) when their jobs
        # overlap, so wait and retry those too.
        timeouts = 0
        for attempt in range(RATE_LIMIT_ATTEMPTS):
            last = attempt == RATE_LIMIT_ATTEMPTS - 1
            try:
                resp = requests.post(self.url, headers=headers, json=payload, timeout=45)
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                timeouts += 1
                if timeouts == retries or last:
                    raise
                continue
            if resp.status_code == 429 and not last:
                time.sleep(_retry_delay(resp, attempt))
                continue
            resp.raise_for_status()
            break

        # Server may hand back a session id on first response
        if "Mcp-Session-Id" in resp.headers:
            self.session_id = resp.headers["Mcp-Session-Id"]

        # Notifications (e.g. "notifications/initialized") get no JSON-RPC
        # response — servers typically reply 202 with an empty body.
        if not resp.text.strip():
            return {}

        content_type = resp.headers.get("Content-Type", "")
        if "text/event-stream" in content_type:
            # Parse SSE: take the last "data: {...}" line as the JSON-RPC response
            data_lines = [
                line[len("data:"):].strip()
                for line in resp.text.splitlines()
                if line.startswith("data:")
            ]
            if not data_lines:
                raise RuntimeError(f"No data in SSE response: {resp.text}")
            return json.loads(data_lines[-1])
        return resp.json()

    def initialize(self) -> dict:
        result = self._post({
            "jsonrpc": "2.0",
            "id": next(_id_counter),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "vo-creations-launchpoint-bot", "version": "1.0"},
            },
        })
        # Some servers require an "initialized" notification after this
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return result

    def list_tools(self) -> list:
        result = self._post({
            "jsonrpc": "2.0",
            "id": next(_id_counter),
            "method": "tools/list",
        })
        return result.get("result", {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict) -> dict:
        result = self._post({
            "jsonrpc": "2.0",
            "id": next(_id_counter),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        })
        if "error" in result:
            raise RuntimeError(f"MCP tool call failed: {result['error']}")
        return result.get("result", {})


def get_session(api_key: str = "") -> MCPSession:
    session = MCPSession(MCP_URL, api_key or API_KEY)
    session.initialize()
    return session
