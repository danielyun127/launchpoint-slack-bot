"""
Run this once: python discover_tools.py

Connects to the LaunchPoint MCP server and prints every tool it exposes,
along with the input schema each tool expects. Send me the output and
I'll wire launchpoint_client.py's fetch_via_mcp() to call the right tool
with the right arguments.
"""

import json
from dotenv import load_dotenv

load_dotenv()

from mcp_client import get_session

if __name__ == "__main__":
    session = get_session()
    tools = session.list_tools()
    print(f"Found {len(tools)} tool(s):\n")
    for tool in tools:
        print(f"- {tool.get('name')}")
        print(f"  description: {tool.get('description', '(none)')}")
        print(f"  input schema: {json.dumps(tool.get('inputSchema', {}), indent=2)}")
        print()
