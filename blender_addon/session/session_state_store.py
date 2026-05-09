"""Persisted high-level session work state — Onda 3.

Each session has its own file: ``runtime/session_state/<session_id>.json``.

The file is small and authoritative for the state machine. ``Session.execution_state.session_state`` mirrors
the persisted value so handlers can read in-memory; the dedicated file is the
source of truth across restarts and is the layer the recovery pipeline checks
first (it carries the identity needed to locate everything else).

Schema:
    {
        "session_id": str,
        "blend_path": str,
        "session_state": str,         # one of SESSION_STATES
        "previous_state": str,        # for debugging transition history
        "updated_at": iso8601,
        "transition_count": int,
    }
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .schema import SESSION_STATES, utc_now_iso

_SUBDIR = "session_state"


class SessionStateStore:
    """Filesystem-backed store for the persisted session_state field."""

    def __init__(self, project_root: Path) -> None:
        self._dir = Path(project_root) / "runtime" / _SUBDIR

    def _ensure_dir(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)

    def path(self, session_id: str) -> Path:
        return self._dir / f"{session_id}.json"

    def load(self, session_id: str) -> dict[str, Any] | None:
        if not session_id:
            return None
        p = self.path(session_id)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        state = str(data.get("session_state") or "")
        if state not in SESSION_STATES:
            data["session_state"] = "IDLE"
        return data

    def read_state(self, session_id: str) -> str:
        """Return the persisted session_state, or empty string if absent."""
        data = self.load(session_id)
        if not data:
            return ""
        return str(data.get("session_state") or "")

    def write(
        self,
        session_id: str,
        *,
        session_state: str,
        blend_path: str = "",
        previous_state: str = "",
    ) -> Path | None:
        """Atomically write the state file. Returns the path, or None on no-op."""
        if not session_id:
            return None
        if session_state not in SESSION_STATES:
            session_state = "IDLE"
        self._ensure_dir()
        p = self.path(session_id)

        prior = self.load(session_id) or {}
        transition_count = int(prior.get("transition_count") or 0)
        if previous_state and previous_state != session_state:
            transition_count += 1

        payload = {
            "session_id": session_id,
            "blend_path": blend_path or str(prior.get("blend_path") or ""),
            "session_state": session_state,
            "previous_state": previous_state or str(prior.get("session_state") or ""),
            "updated_at": utc_now_iso(),
            "transition_count": transition_count,
        }

        # Atomic write — temp file in same dir, then os.replace.
        fd, tmp_name = tempfile.mkstemp(prefix=f".{session_id}.", suffix=".json.tmp", dir=str(self._dir))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp_name, p)
        except Exception:
            try:
                os.unlink(tmp_name)
            except Exception:
                pass
            raise
        return p

    def delete(self, session_id: str) -> None:
        if not session_id:
            return
        p = self.path(session_id)
        try:
            p.unlink()
        except FileNotFoundError:
            pass
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Pure transition function
# ---------------------------------------------------------------------------

def compute_next_state(session: Any) -> str:
    """Derive the next session_state from a session's ExecutionState fields.

    Pure, deterministic, no side effects. Same logic as
    ``routing_obs.infer_session_state`` — kept here so the persistence layer
    has its own copy independent of observability code.

    Onda 5 will replace the body with a true ``(state, signal) → next_state``
    transition table; the function signature stays the same so callers do not
    need to change.
    """
    es = getattr(session, "execution_state", None)
    if es is None:
        return "IDLE"

    pending = getattr(es, "pending_user_decision", None)
    if pending is not None and str(getattr(pending, "status", "") or "") == "pending":
        current = str(getattr(es, "session_state", "") or "")
        return current if current == "STRATEGY_PROPOSED" else "STRATEGY_PROPOSED"

    # When a strategy decision was answered, preserve STRATEGY_APPROVED for the
    # rest of the turn so retry_requires_draft_change cannot collapse it to REPAIRING.
    if pending is not None and str(getattr(pending, "status", "") or "") == "answered":
        kind = str(getattr(pending, "kind", "") or "")
        if kind in {"strategy_choice", "repair_direction", "write_confirmation"}:
            return "STRATEGY_APPROVED"

    phase = str(getattr(es, "phase", "") or "")
    current_draft = getattr(es, "current_draft", None)
    draft_revision = int(getattr(es, "draft_revision", 0) or 0)
    last_executed_revision = int(getattr(es, "last_executed_revision", 0) or 0)
    last_execution_outcome = str(getattr(es, "last_execution_outcome", "") or "")
    last_failure = getattr(es, "last_failure", None)
    retry_requires_draft_change = bool(getattr(es, "retry_requires_draft_change", False))

    active_draft = (
        current_draft is not None
        or draft_revision > 0
        or (bool(getattr(es, "drafting_mode", False)) and bool(getattr(es, "draft_block_name", "")))
    )

    if retry_requires_draft_change:
        return "REPAIRING"
    if last_execution_outcome in ("error", "failed", "failure"):
        return "REPAIRING"
    if phase == "failed":
        return "REPAIRING"
    if last_failure is not None and str(getattr(last_failure, "error", "") or "").strip():
        return "REPAIRING"

    if (
        last_executed_revision > 0
        and last_executed_revision == draft_revision
        and last_execution_outcome in ("success", "partial", "partial_success")
    ):
        return "RESOLVED"

    if active_draft and draft_revision > last_executed_revision:
        return "PENDING_USER_EXECUTION"

    if phase == "drafting" or (active_draft and last_executed_revision == 0):
        return "DRAFTING"

    if phase == "reading":
        return "EXPLORING"

    return "IDLE"
