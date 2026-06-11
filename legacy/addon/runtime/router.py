"""Turn-class types and intent inference for the draft-first product runtime.

``TurnClass`` and ``ClassifierMeta`` are the shared vocabulary used by
``infer_turn_intent`` (the live classifier) and by ``routing_obs``
(observability layer).
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


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


def infer_turn_intent(session: Any, user_message: str):
    """Infer the slim workspace goal using the four Phase-3 rules.

    Returns ``(TurnClass, ClassifierMeta, goal_mode: str)``.
    """
    text = str(user_message or "").strip()
    lowered = text.lower()
    normalized = unicodedata.normalize("NFKD", lowered)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = "".join(ch if ch.isalnum() else " " for ch in normalized)
    word_list = normalized.split()
    words = set(word_list)

    def has_prefix(*prefixes: str) -> bool:
        return any(any(word.startswith(prefix) for prefix in prefixes) for word in words)

    es = getattr(session, "execution_state", None)
    pending = getattr(es, "pending_user_decision", None) if es is not None else None
    pending_status = str(getattr(pending, "status", "") or "")
    session_state = str(getattr(es, "session_state", "") or "")
    has_active_draft = (
        getattr(es, "current_draft", None) is not None
        or int(getattr(es, "draft_revision", 0) or 0) > 0
        or bool(getattr(es, "drafting_mode", False))
    ) if es is not None else False

    signals: list[str] = []
    if pending_status == "answered":
        signals.append("pending_decision_resolved")
        meta = ClassifierMeta(
            turn_class=TurnClass.DRAFT_WORKSPACE,
            signals=signals,
            raw_message=text,
            turn_intent="strategy_approval",
            session_state=session_state or "STRATEGY_APPROVED",
            goal_mode="focal_correction",
        )
        return TurnClass.DRAFT_WORKSPACE, meta, "focal_correction"

    if text.startswith("[RESULTADO DE EXECUÇÃO"):
        signals.append("execution_result_prefix")
        meta = ClassifierMeta(
            turn_class=TurnClass.EXECUTION_FEEDBACK,
            signals=signals,
            raw_message=text,
            turn_intent="feedback_fix",
            session_state=session_state,
            goal_mode="feedback_fix",
        )
        return TurnClass.EXECUTION_FEEDBACK, meta, "feedback_fix"

    pending_kind = str(getattr(pending, "kind", "") or "")
    diagnosis_request = (
        has_prefix("diagnostic", "analis", "investig", "certeza", "verific")
        or (
            "antes" in words
            and "de" in words
            and has_prefix("escrev", "salv", "ger", "cri")
        )
    )
    continuation_request = (
        word_list in (["continua"], ["continue"], ["continuar"], ["segue"], ["prossegue"])
        or word_list == ["pode", "continuar"]
    )
    retry_state_active = bool(
        getattr(es, "retry_requires_draft_change", False)
        or str(getattr(es, "pending_draft_action", "") or "").strip()
        or session_state in {"REPAIRING", "STRATEGY_APPROVED"}
    ) if es is not None else False
    retry_request = bool(
        has_active_draft
        and retry_state_active
        and "tenta" in words
        and bool({"denovo", "novo", "novamente"} & words)
    )
    if retry_request:
        signals.append("stateful_retry_request")
        meta = ClassifierMeta(
            turn_class=TurnClass.DRAFT_WORKSPACE,
            signals=signals,
            raw_message=text,
            turn_intent="draft_refinement",
            session_state=session_state,
            goal_mode="focal_correction",
            needs_baseline_refresh=True,
        )
        return TurnClass.DRAFT_WORKSPACE, meta, "focal_correction"
    if has_active_draft and (
        diagnosis_request
        or (
            pending_status == "pending"
            and pending_kind in {"strategy_choice", "repair_direction", "write_confirmation"}
            and continuation_request
        )
    ):
        signals.append("diagnose_only_request" if diagnosis_request else "pending_diagnosis_continuation")
        meta = ClassifierMeta(
            turn_class=TurnClass.DRAFT_WORKSPACE,
            signals=signals,
            raw_message=text,
            turn_intent="diagnose_only",
            session_state=session_state,
            goal_mode="diagnose_only",
            needs_baseline_refresh=True,
        )
        return TurnClass.DRAFT_WORKSPACE, meta, "diagnose_only"

    write_request = has_prefix(
        "escrev", "salv", "ger", "cri", "faz", "corrig", "corrij",
        "ajust", "arrum", "consert", "reescrev", "refa", "alter",
        "mud", "implement", "apli", "write", "save", "generate",
        "create", "fix", "adjust", "rewrite",
    )
    if write_request:
        signals.append("explicit_write_imperative")
        goal_mode = "focal_correction" if has_active_draft else "functional_expansion"
        meta = ClassifierMeta(
            turn_class=TurnClass.DRAFT_WORKSPACE,
            signals=signals,
            raw_message=text,
            turn_intent="draft_refinement" if has_active_draft else "draft_write",
            session_state=session_state,
            goal_mode=goal_mode,
            needs_baseline_refresh=True,
        )
        return TurnClass.DRAFT_WORKSPACE, meta, goal_mode

    signals.append("default_inquiry")
    meta = ClassifierMeta(
        turn_class=TurnClass.CONTEXT_INQUIRY,
        confidence="low",
        signals=signals,
        raw_message=text,
        turn_intent="pure_inquiry",
        session_state=session_state,
        goal_mode="inquiry",
        needs_baseline_refresh=True,
    )
    return TurnClass.CONTEXT_INQUIRY, meta, "inquiry"
