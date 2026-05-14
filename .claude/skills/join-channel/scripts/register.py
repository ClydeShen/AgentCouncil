#!/usr/bin/env python3
"""Register this agent with the AgentCouncil hub.

Usage: python register.py <agent_id> <name> <channel_id> [capability ...]

Example:
  python register.py claude-alice "Claude (Alice)" project-alpha code-review python
"""

import json
import sys
import uuid

import httpx

HUB_URL = "http://127.0.0.1:8000"


def main() -> None:
    if len(sys.argv) < 4:
        print("Usage: register.py <agent_id> <name> <channel_id> [capability ...]")
        print("Example: register.py claude-1 'Claude Reviewer' my-project code-review")
        sys.exit(1)

    agent_id = sys.argv[1]
    name = sys.argv[2]
    channel_id = sys.argv[3]
    capabilities = sys.argv[4:]

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": str(uuid.uuid4()),
                "role": "ROLE_USER",
                "parts": [{"data": {
                    "action": "register_agent",
                    "agent_id": agent_id,
                    "name": name,
                    "channel_id": channel_id,
                    "capabilities": capabilities,
                }}],
            }
        },
    }

    try:
        resp = httpx.post(HUB_URL, json=payload, headers={"A2A-Version": "1.0"}, timeout=5)
        resp.raise_for_status()
    except httpx.ConnectError:
        print(f"ERROR: Cannot reach hub at {HUB_URL}. Is server.py running?")
        sys.exit(1)
    except httpx.HTTPStatusError as e:
        print(f"ERROR: Hub returned HTTP {e.response.status_code}: {e.response.text}")
        sys.exit(1)

    result = _extract_result(resp.json())
    if not result.get("ok"):
        print(f"ERROR: Registration failed — {result.get('error', 'unknown error')}")
        sys.exit(1)

    caps_str = ", ".join(capabilities) if capabilities else "(none)"
    print(f"Registered '{name}' (id={agent_id}) in channel '{channel_id}'")
    print(f"Capabilities: {caps_str}")


def _extract_result(body: dict) -> dict:
    try:
        arts = body["result"]["task"]["artifacts"]
        return arts[0]["parts"][0]["data"]
    except (KeyError, IndexError):
        return {"ok": False, "error": f"Unexpected response: {json.dumps(body)}"}


if __name__ == "__main__":
    main()
