#!/usr/bin/env bash
# Check whether the AgentCouncil A2A hub is reachable and healthy.
# Exits 0 if healthy, 1 otherwise.

HUB_URL="${HUB_URL:-http://127.0.0.1:8000}"
CARD_URL="$HUB_URL/.well-known/agent-card.json"

response=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 "$CARD_URL")

if [ "$response" = "200" ]; then
  echo "Hub is healthy at $HUB_URL"
  exit 0
else
  echo "Hub is NOT reachable at $HUB_URL (HTTP $response). Run 'python server.py' to start it."
  exit 1
fi
