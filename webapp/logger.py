"""Conversation logger — writes each chat session to a JSON file on disk."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"

_conversation_files: dict[str, Path] = {}


def _ensure_log_dir() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _file_for(conversation_id: str) -> Path:
    return _conversation_files.get(conversation_id, LOG_DIR / f"{conversation_id}.json")


def init_conversation(conversation_id: str) -> Path:
    """Create a new log file for a conversation. Returns the file path."""
    _ensure_log_dir()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    short_id = conversation_id[:8]
    filename = f"{ts}_{short_id}.json"
    path = LOG_DIR / filename

    data = {
        "conversation_id": conversation_id,
        "started_at": _now_iso(),
        "last_updated": _now_iso(),
        "exchanges": [],
    }
    path.write_text(json.dumps(data, indent=2))

    _conversation_files[conversation_id] = path
    return path


def log_exchange(
    conversation_id: str,
    user_message: str,
    tool_calls: list[dict[str, Any]],
    assistant_response: str,
) -> None:
    """Append an exchange to the conversation's log file.

    Auto-initializes the log file if this is the first exchange.
    """
    if conversation_id not in _conversation_files:
        init_conversation(conversation_id)

    path = _file_for(conversation_id)
    data = json.loads(path.read_text())

    data["last_updated"] = _now_iso()
    data["exchanges"].append({
        "timestamp": _now_iso(),
        "user_message": user_message,
        "tool_calls": tool_calls,
        "assistant_response": assistant_response,
    })

    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)
