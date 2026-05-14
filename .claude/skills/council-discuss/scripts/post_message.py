#!/usr/bin/env python3
"""Post a message to a group conversation.

Usage: python post_message.py <conversation_id> <from_agent_id> <message_content>

Example:
  python post_message.py abc-123 claude-1 "I reviewed the PR — LGTM with minor comments"
"""

import json
import sys
import uuid

import httpx

HUB_URL = "http://127.0.0.1:8000"


def main() -> None:
    if len(sys.argv) < 4:
        print("Usage: post_message.py <conversation_id> <from_agent_id> <message_content>")
        sys.exit(1)

    conversation_id = sys.argv[1]
    from_agent = sys.argv[2]
    content = " ".join(sys.argv[3:])

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": str(uuid.uuid4()),
                "role": "ROLE_USER",
                "parts": [{"data": {
                    "action": "post_to_conversation",
                    "conversation_id": conversation_id,
                    "from_agent": from_agent,
                    "content": content,
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
        print(f"ERROR: {result.get('error', 'Post failed')}")
        sys.exit(1)

    total = int(result.get("total_messages", 0))
    print(f"Message posted by '{from_agent}' (conversation now has {total} message(s)).")


def _extract_result(body: dict) -> dict:
    try:
        arts = body["result"]["task"]["artifacts"]
        return arts[0]["parts"][0]["data"]
    except (KeyError, IndexError):
        return {"ok": False, "error": f"Unexpected response: {json.dumps(body)}"}


if __name__ == "__main__":
    main()
