#!/usr/bin/env python3
"""Create a new channel-scoped group conversation.

Usage: python create_conversation.py <channel_id> <name> <participant1> [participant2 ...]

Example:
  python create_conversation.py project-alpha "auth-refactor review" claude-1 codex-1 gemini-1
"""

import json
import sys
import uuid

import httpx

HUB_URL = "http://127.0.0.1:8000"


def main() -> None:
    if len(sys.argv) < 4:
        print("Usage: create_conversation.py <channel_id> <name> <participant1> [participant2 ...]")
        sys.exit(1)

    channel_id = sys.argv[1]
    name = sys.argv[2]
    participants = sys.argv[3:]

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": str(uuid.uuid4()),
                "role": "ROLE_USER",
                "parts": [{"data": {
                    "action": "create_conversation",
                    "channel_id": channel_id,
                    "name": name,
                    "participants": participants,
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

    result = _extract_result(resp.json())
    if not result.get("ok"):
        print(f"ERROR: Failed to create conversation — {result.get('error', 'unknown error')}")
        sys.exit(1)

    conv_id = result["conversation_id"]
    print(f"Conversation created: '{name}'")
    print(f"  conversation_id: {conv_id}")
    print(f"  channel: {channel_id}")
    print(f"  participants: {', '.join(participants)}")
    print(f"\nUse this conversation_id in post_message.py and get_conversation.py.")


def _extract_result(body: dict) -> dict:
    try:
        arts = body["result"]["task"]["artifacts"]
        return arts[0]["parts"][0]["data"]
    except (KeyError, IndexError):
        return {"ok": False, "error": f"Unexpected response: {json.dumps(body)}"}


if __name__ == "__main__":
    main()
