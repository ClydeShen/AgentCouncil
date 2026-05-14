#!/usr/bin/env python3
"""Send a direct message to another agent's inbox.

Usage: python send_message.py <from_agent_id> <to_agent_id> <message_content>
"""

import json
import sys
import uuid

import httpx

HUB_URL = "http://127.0.0.1:8000"


def main() -> None:
    if len(sys.argv) < 4:
        print("Usage: send_message.py <from_agent_id> <to_agent_id> <message_content>")
        sys.exit(1)

    from_agent = sys.argv[1]
    to_agent = sys.argv[2]
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
                    "action": "send_message",
                    "from_agent": from_agent,
                    "to_agent": to_agent,
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
        print(f"ERROR: {result.get('error', 'Send failed')}")
        sys.exit(1)

    print(f"Message sent from '{from_agent}' to '{to_agent}'.")


def _extract_result(body: dict) -> dict:
    try:
        arts = body["result"]["task"]["artifacts"]
        return arts[0]["parts"][0]["data"]
    except (KeyError, IndexError):
        return {"ok": False, "error": f"Unexpected response: {json.dumps(body)}"}


if __name__ == "__main__":
    main()
