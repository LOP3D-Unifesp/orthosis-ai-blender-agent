"""Bounded chat history helper for the v1 schema (Phase 1).

The Phase 1 contract is intentionally narrow:

* append messages with role/content/turn_class metadata,
* enforce the ``max_messages`` bound,
* expose a hook to roll evicted messages into ``older_summary``.

The actual summarisation logic (LLM-driven) belongs to Phase 2; Phase 1
provides a pluggable callback so a future Runtime can wire one in without
touching the dataclass.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

from .schema import History, HistoryMessage, utc_now_iso

VALID_ROLES = frozenset({"user", "assistant", "system"})


SummariserCallback = Callable[[list[HistoryMessage], str | None], str | None]


class BoundedHistory:
    """Thin wrapper around :class:`History` that enforces invariants."""

    def __init__(self, history: History, *, summariser: SummariserCallback | None = None) -> None:
        self.history = history
        self.summariser = summariser

    # ---- writes ----------------------------------------------------------

    def append(self, *, role: str, content: str, turn_class: str = "", ts: str | None = None) -> HistoryMessage | None:
        """Append a message and return it, or ``None`` if it was rejected."""
        normalized_role = str(role or "").strip().lower()
        if normalized_role not in VALID_ROLES:
            return None
        text = str(content or "")
        if not text.strip():
            return None
        message = HistoryMessage(
            role=normalized_role,
            content=text,
            ts=ts or utc_now_iso(),
            turn_class=str(turn_class or ""),
        )
        self.history.messages.append(message)
        self._enforce_bound()
        return message

    def extend(self, items: Iterable[dict[str, Any]]) -> int:
        """Append a batch of dict-shaped messages, returning the count appended."""
        appended = 0
        for item in items or []:
            if not isinstance(item, dict):
                continue
            if self.append(
                role=str(item.get("role", "")),
                content=str(item.get("content", item.get("text", ""))),
                turn_class=str(item.get("turn_class", "")),
                ts=str(item.get("ts", item.get("timestamp", "") or "")) or None,
            ) is not None:
                appended += 1
        return appended

    def clear(self) -> None:
        self.history.messages = []
        self.history.older_summary = None

    # ---- reads -----------------------------------------------------------

    def recent(self, n: int) -> list[HistoryMessage]:
        if n <= 0:
            return []
        return list(self.history.messages[-n:])

    def __len__(self) -> int:
        return len(self.history.messages)

    # ---- invariant -------------------------------------------------------

    def _enforce_bound(self) -> None:
        cap = max(int(self.history.max_messages), 0)
        if cap <= 0:
            return
        if len(self.history.messages) <= cap:
            return
        evicted = self.history.messages[:-cap]
        self.history.messages = self.history.messages[-cap:]
        if not evicted:
            return
        if self.summariser is None:
            return
        try:
            new_summary = self.summariser(evicted, self.history.older_summary)
        except Exception:
            # Phase 1: a misbehaving summariser must never break history writes.
            return
        if new_summary is not None:
            self.history.older_summary = str(new_summary)
