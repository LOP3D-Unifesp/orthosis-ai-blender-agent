"""Structured session schema (Phase 1 of REFATOR_PLAN.md).

This subpackage introduces the v1 structured session model in parallel with
the legacy flat-dict ``session_store.SessionStore``. Phase 1 only adds the
data shape, persistence, and migration: it does not yet rewire the runtime.
The legacy store remains the source of truth for active runtime code; the
v1 schema is consulted by tests and (later, in Phase 2) by the turn router
behind the ``USE_STRUCTURED_SESSION_V1`` feature flag.
"""

from __future__ import annotations

from .schema import (
    SCHEMA_VERSION,
    SESSION_STATES,
    BaselineWorkspace,
    ExecutionState,
    Focus,
    History,
    HistoryMessage,
    Identity,
    LastFailure,
    Lifecycle,
    OperationalState,
    PendingUserDecision,
    Session,
    UIState,
    compute_focus_signature,
    utc_now_iso,
)
from .store import SessionV1Store
from .baseline import BaselineBuilder, compute_tree_signature
from .history import BoundedHistory
from .session_state_store import SessionStateStore, compute_next_state

__all__ = [
    "SCHEMA_VERSION",
    "SESSION_STATES",
    "BaselineBuilder",
    "BaselineWorkspace",
    "BoundedHistory",
    "ExecutionState",
    "Focus",
    "History",
    "HistoryMessage",
    "Identity",
    "LastFailure",
    "Lifecycle",
    "OperationalState",
    "PendingUserDecision",
    "Session",
    "SessionStateStore",
    "SessionV1Store",
    "UIState",
    "compute_focus_signature",
    "compute_next_state",
    "compute_tree_signature",
    "utc_now_iso",
]
