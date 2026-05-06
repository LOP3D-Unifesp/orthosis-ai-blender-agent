"""Append-only JSONL store for visible chat history.

Each session gets its own file:  runtime/chat_history/<session_id>.jsonl

Every line is a JSON object with keys: role, content, ts, turn_class.
The file is the source of truth for what the user sees in the panel.
It is written immediately when a message is produced — independently of
the V1 session JSON — so the conversation survives even if the V1 save fails.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_SUBDIR = "chat_history"


def _utc_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


class ChatHistoryStore:
    """Filesystem-backed, append-only store for chat messages."""

    def __init__(self, project_root: Path) -> None:
        self._dir = Path(project_root) / "runtime" / _SUBDIR

    def _ensure_dir(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)

    def path(self, session_id: str) -> Path:
        return self._dir / f"{session_id}.jsonl"

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def append(
        self,
        session_id: str,
        *,
        role: str,
        content: str,
        ts: str = "",
        turn_class: str = "",
    ) -> None:
        """Append one message to the JSONL file."""
        self._ensure_dir()
        entry: dict[str, Any] = {
            "role": role,
            "content": content,
            "ts": ts or _utc_now_iso(),
            "turn_class": turn_class,
        }
        with self.path(session_id).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def load(self, session_id: str) -> list[dict[str, Any]]:
        """Return all messages for the session, in order."""
        p = self.path(session_id)
        if not p.exists():
            return []
        messages: list[dict[str, Any]] = []
        with p.open("r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    messages.append(json.loads(raw))
                except json.JSONDecodeError:
                    pass
        return messages

    # ------------------------------------------------------------------
    # Clear
    # ------------------------------------------------------------------

    def clear(self, session_id: str) -> None:
        """Delete the JSONL file for the session."""
        p = self.path(session_id)
        if p.exists():
            p.unlink()

    # ------------------------------------------------------------------
    # One-shot migration
    # ------------------------------------------------------------------

    def migrate_from_messages(self, session_id: str, messages: list[Any]) -> int:
        """Write existing session messages to JSONL.

        Idempotent: skips if the JSONL already exists.
        Returns the number of messages written (0 if skipped).
        """
        if self.path(session_id).exists():
            return 0
        count = 0
        for msg in messages:
            if isinstance(msg, dict):
                role = str(msg.get("role", ""))
                content = str(msg.get("content", ""))
                ts = str(msg.get("ts", ""))
                turn_class = str(msg.get("turn_class", ""))
            else:
                role = str(getattr(msg, "role", ""))
                content = str(getattr(msg, "content", ""))
                ts = str(getattr(msg, "ts", ""))
                turn_class = str(getattr(msg, "turn_class", ""))
            if role and content:
                self.append(session_id, role=role, content=content, ts=ts, turn_class=turn_class)
                count += 1
        return count
