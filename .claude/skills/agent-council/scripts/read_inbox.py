#!/usr/bin/env python3
"""Retrieve and clear pending direct messages from this agent's inbox.

Usage: python read_inbox.py <agent_id>
"""

import json
import sys
import uuid

import httpx

HUB_URL = "http://127.0.0.1:8000"


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: read_inbox.py <agent_id>")
        sys.exit(1)

    agent_id = sys.argv[1]

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": str(uuid.uuid4()),
                "role": "ROLE_USER",
                "parts": [{"data": {"action": "read_inbox", "agent_id": agent_id}}],
            }
        },
    }

    try:
        resp = httpx.post(HUB_URL, json=payload, headers={"A2A-Version": "1.0"}, timeout=5)
        resp.raise_for_status()
    except httpx.ConnectError:
        print(f"ERROR: Cannot reach hub at {HUB_URL}. Is server.py running?")
        sys.exit(1)

    messages = _extract_result(resp.json())
    if isinstance(messages, dict) and not messages.get("ok", True):
        print(f"ERROR: {messages.get('error')}")
        sys.exit(1)

    if not messages:
        print(f"Inbox empty for agent '{agent_id}'.")
        return

    print(f"Inbox for '{agent_id}' — {len(messages)} message(s) (now cleared):")
    for msg in messages:
        print(f"\n  From: {msg['from']}  At: {msg['at']}")
        print(f"  {msg['content']}")


def _extract_result(body: dict):
    try:
        arts = body["result"]["task"]["artifacts"]
        return arts[0]["parts"][0]["data"]
    except (KeyError, IndexError):
        return {"ok": False, "error": f"Unexpected response: {json.dumps(body)}"}


if __name__ == "__main__":
    main()
