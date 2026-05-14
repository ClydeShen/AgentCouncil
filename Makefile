HOST ?= 0.0.0.0
PORT ?= 8000

.PHONY: start stop install

start:
	uv run python server.py --host $(HOST) --port $(PORT)

install:
	uv sync

stop:
	pkill -f "python server.py" || true
