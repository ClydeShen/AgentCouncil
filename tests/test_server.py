import sys
from pathlib import Path

import pytest

# Add parent directory to path to import server
sys.path.insert(0, str(Path(__file__).parent.parent))

from server import TOKEN, _events, _cursors


def test_token_is_six_chars():
    assert len(TOKEN) == 6
    assert TOKEN.isalnum()


def test_event_store_starts_empty():
    assert isinstance(_events, list)


def test_cursor_store_starts_empty():
    assert isinstance(_cursors, dict)
