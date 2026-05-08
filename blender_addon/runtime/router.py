"""Turn-class types for the draft-first product runtime.

``TurnClass`` and ``ClassifierMeta`` are the shared vocabulary used by
``AgentRuntime._infer_turn_intent`` (the live classifier) and by
``routing_obs`` (observability layer).

The ``TurnRouter`` classifier was removed — its logic now lives inline in
``core/runtime.py:AgentRuntime._infer_turn_intent``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TurnClass(str, Enum):
    TRIVIAL_CHAT = "trivial_chat"
    CONTEXT_INQUIRY = "context_inquiry"
    DRAFT_WORKSPACE = "draft_workspace"
    EXECUTION_FEEDBACK = "execution_feedback"
    STATE_CONTROL = "state_control"


@dataclass
class ClassifierMeta:
    """Metadata produced alongside the TurnClass for handler use."""

    turn_class: TurnClass
    confidence: str = "high"          # "high" | "medium" | "low"
    signals: list[str] = field(default_factory=list)
    needs_baseline_refresh: bool = False
    raw_message: str = ""
    # --- Observability fields (read-only, no effect on dispatch) ---
    turn_intent: str = ""
    session_state: str = ""
    goal_mode: str = ""
