"""Routing observability helpers — read-only, no effect on dispatch.

Provides two functions used in production:

  ``infer_session_state(session)``
      Infers the current work state (IDLE, DRAFTING, REPAIRING, etc.) from
      ExecutionState fields. Called by handler/workspace.py.

  ``compute_shadow_handler(turn_intent, session_state, chosen_class)``
      Returns what capability-routing would choose vs. what the classifier
      chose, used only for journal logging in core/runtime.py.

``enrich_meta_observability`` and ``infer_turn_intent`` were removed — they
were only called from TurnRouter.classify() which no longer exists.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Session state labels
# ---------------------------------------------------------------------------

SESSION_STATES = frozenset({
    "IDLE",
    "EXPLORING",
    "DRAFTING",
    "PENDING_USER_EXECUTION",
    "REPAIRING",
    "STRATEGY_PROPOSED",
    "STRATEGY_APPROVED",
    "RESOLVED",
})


def infer_session_state(session: Any) -> str:
    """Return the session work state.

    Prefer the persisted value on ``execution_state.session_state``; fall back
    to field-derived inference for sessions that predate the persisted field.
    Pure function — reads only, never writes to session.
    """
    es = getattr(session, "execution_state", None)
    if es is None:
        return "IDLE"

    persisted = str(getattr(es, "session_state", "") or "")
    if persisted in SESSION_STATES:
        return persisted

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


# ---------------------------------------------------------------------------
# Shadow handler
# ---------------------------------------------------------------------------

def compute_shadow_handler(
    turn_intent: str,
    session_state: str,
    chosen_class: str,
) -> str:
    """What handler would capability-routing choose, given intent + state?

    Returns the same value as ``chosen_class`` when there is no divergence,
    so callers can check ``shadow != chosen`` to detect mismatches.
    """
    write_intents = {"inquiry_then_write", "draft_write", "draft_refinement", "feedback_fix", "strategy_approval"}

    if turn_intent in write_intents and chosen_class == "context_inquiry":
        return "draft_workspace"

    if (
        turn_intent == "execution_feedback"
        and chosen_class == "context_inquiry"
        and session_state in {"PENDING_USER_EXECUTION", "REPAIRING", "STRATEGY_PROPOSED", "STRATEGY_APPROVED"}
    ):
        return "execution_feedback"

    if chosen_class == "draft_workspace" and turn_intent in {
        "pure_inquiry",
        "execution_feedback",
        "continuation",
    }:
        if session_state in {"PENDING_USER_EXECUTION", "REPAIRING", "STRATEGY_PROPOSED", "STRATEGY_APPROVED", "DRAFTING"}:
            return "draft_workspace+intent_mismatch"

    return chosen_class
