"""
Minimal client for talking to an MCP server over "Streamable HTTP" transport
(a single POST endpoint, JSON-RPC 2.0 messages, optional SSE response).

This isn't LaunchPoint-specific — it just knows how to: initialize a session,
list available tools, and call one.
"""

import os
import json
import itertools
import requests

MCP_URL = os.environ["LAUNCHPOINT_MCP_URL"]
API_KEY = os.environ["LAUNCHPOINT_API_KEY"]

_id_counter = itertools.count(1)


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
        for attempt in range(retries):
            try:
                resp = requests.post(self.url, headers=headers, json=payload, timeout=45)
                resp.raise_for_status()
                break
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                if attempt == retries - 1:
                    raise

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


def get_session() -> MCPSession:
    session = MCPSession(MCP_URL, API_KEY)
    session.initialize()
    return session
