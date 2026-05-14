#!/usr/bin/env python3
"""Read the full history of a group conversation.

Usage: python get_conversation.py <conversation_id>
"""

import json
import sys
import uuid

import httpx

HUB_URL = "http://127.0.0.1:8000"


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: get_conversation.py <conversation_id>")
        sys.exit(1)

    conversation_id = sys.argv[1]

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": str(uuid.uuid4()),
                "role": "ROLE_USER",
                "parts": [{"data": {"action": "get_conversation", "conversation_id": conversation_id}}],
            }
        },
    }

    try:
        resp = httpx.post(HUB_URL, json=payload, headers={"A2A-Version": "1.0"}, timeout=5)
        resp.raise_for_status()
    except httpx.ConnectError:
        print(f"ERROR: Cannot reach hub at {HUB_URL}. Is server.py running?")
        sys.exit(1)

    conv = _extract_result(resp.json())
    if isinstance(conv, dict) and not conv.get("ok", True):
        print(f"ERROR: {conv.get('error')}")
        sys.exit(1)

    messages = conv.get("messages", [])
    participants = conv.get("participants", [])
    print(f"=== {conv.get('name', conversation_id)} ===")
    print(f"Channel: {conv.get('channel_id')}  |  Participants: {', '.join(participants)}")
    print(f"Created: {conv.get('created_at')}  |  Messages: {len(messages)}")
    print()

    if not messages:
        print("(no messages yet)")
        return

    for msg in messages:
        print(f"[{msg['at']}] {msg['from']}:")
        print(f"  {msg['content']}")
        print()


def _extract_result(body: dict):
    try:
        arts = body["result"]["task"]["artifacts"]
        return arts[0]["parts"][0]["data"]
    except (KeyError, IndexError):
        return {"ok": False, "error": f"Unexpected response: {json.dumps(body)}"}


if __name__ == "__main__":
    main()
