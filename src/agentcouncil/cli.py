import argparse
import logging

import uvicorn


def main() -> None:
    from agentcouncil.server import TOKEN, app

    parser = argparse.ArgumentParser(description="AgentCouncil Hub")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    args = parser.parse_args()

    display_host = "127.0.0.1" if args.host == "0.0.0.0" else args.host
    base = f"http://{display_host}:{args.port}"
    print(f"AgentCouncil hub starting on {base}")
    print("─" * 51)
    print("Share this link to invite agents:")
    print()
    print(f"  {base}/join/{TOKEN}")
    print()
    print("─" * 51)
    print(f"Dashboard:     {base}/dashboard")
    print(f"MCP endpoint:  {base}/mcp")
    print(f"Agent card:    {base}/.well-known/agent-card.json")

    class _NoSSEFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            return "/dashboard/events" not in record.getMessage()

    logging.getLogger("uvicorn.access").addFilter(_NoSSEFilter())
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
