#!/usr/bin/env python3
"""List all agents registered in a channel.

Usage: python list_agents.py <channel_id>
"""

import json
import sys
import uuid

import httpx

HUB_URL = "http://127.0.0.1:8000"


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: list_agents.py <channel_id>")
        sys.exit(1)

    channel_id = sys.argv[1]

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": str(uuid.uuid4()),
                "role": "ROLE_USER",
                "parts": [{"data": {"action": "list_agents", "channel_id": channel_id}}],
            }
        },
    }

    try:
        resp = httpx.post(HUB_URL, json=payload, headers={"A2A-Version": "1.0"}, timeout=5)
        resp.raise_for_status()
    except httpx.ConnectError:
        print(f"ERROR: Cannot reach hub at {HUB_URL}. Is server.py running?")
        sys.exit(1)

    agents = _extract_result(resp.json())
    if isinstance(agents, dict) and not agents.get("ok", True):
        print(f"ERROR: {agents.get('error')}")
        sys.exit(1)

    if not agents:
        print(f"No agents registered in channel '{channel_id}'.")
        return

    print(f"Agents in channel '{channel_id}' ({len(agents)} total):")
    for a in agents:
        caps = ", ".join(a.get("capabilities", [])) or "(none)"
        print(f"  {a['agent_id']} — {a['name']} [{caps}]")


def _extract_result(body: dict):
    try:
        arts = body["result"]["task"]["artifacts"]
        return arts[0]["parts"][0]["data"]
    except (KeyError, IndexError):
        return {"ok": False, "error": f"Unexpected response: {json.dumps(body)}"}


if __name__ == "__main__":
    main()
