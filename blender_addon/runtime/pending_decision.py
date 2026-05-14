"""Pending user decision helpers for the repair conversation loop."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any

from ..session.schema import PendingUserDecision


@dataclass(frozen=True)
class PendingDecisionResolution:
    status: str
    answered_with: str = ""
    needs_clarification: bool = False
    question: bool = False


def set_pending_decision(
    ctx: Any,
    *,
    kind: str,
    options: list[str],
    prompt_summary: str,
    source_revision: int = 0,
    related_failure: str = "",
    run_id: str = "",
    turn: int = 0,
) -> PendingUserDecision:
    """Materialize a decision prompt in ExecutionState and journal."""
    session = getattr(ctx, "session", None)
    es = getattr(session, "execution_state", None)
    if es is None:
        raise ValueError("set_pending_decision requires session.execution_state")

    runtime = getattr(ctx, "_runtime", None)
    runtime_state = getattr(runtime, "_session_state", {}) if runtime is not None else {}
    if not turn and isinstance(runtime_state, dict):
        turn = int(runtime_state.get("turn_counter") or 0)
    if not run_id:
        journal = getattr(runtime, "journal", None)
        run_id = str(getattr(journal, "_current_run_id", "") or getattr(journal, "current_run_id", "") or "")

    decision = PendingUserDecision(
        kind=kind,
        options=list(options or []),
        prompt_summary=str(prompt_summary or "")[:140],
        source_revision=int(source_revision or 0),
        related_failure=str(related_failure or ""),
        proposed_at_turn=int(turn or 0),
        proposed_at_run_id=run_id,
        status="pending",
        answered_with="",
        answered_at_turn=0,
    )
    es.pending_user_decision = decision
    try:
        if str(kind or "") in {"strategy_choice", "repair_direction", "write_confirmation"}:
            es.post_failure_state = "STRATEGY_PROPOSED"
            es.session_state = "STRATEGY_PROPOSED"
    except Exception:
        pass

    _log_runtime_event(
        runtime,
        "pending_decision_proposed",
        {
            "kind": decision.kind,
            "options": list(decision.options),
            "prompt_summary": decision.prompt_summary,
            "source_revision": int(decision.source_revision),
            "related_failure": decision.related_failure,
            "proposed_at_turn": int(decision.proposed_at_turn),
            "proposed_at_run_id": decision.proposed_at_run_id,
        },
    )
    return decision


def resolve_pending_decision(session: Any, message: str, *, runtime: Any = None) -> PendingDecisionResolution:
    """Resolve, cancel, or keep the pending decision before normal routing."""
    es = getattr(session, "execution_state", None)
    decision = getattr(es, "pending_user_decision", None) if es is not None else None
    _log_runtime_event(
        runtime,
        "pending_decision_resolution_attempt",
        {
            "has_decision": decision is not None,
            "status": str(getattr(decision, "status", "")) if decision is not None else "none",
            "kind": str(getattr(decision, "kind", "")) if decision is not None else "",
            "options": list(getattr(decision, "options", [])) if decision is not None else [],
            "message_preview": str(message or "")[:80],
        },
    )
    if not isinstance(decision, PendingUserDecision) or decision.status != "pending":
        return PendingDecisionResolution("none")

    text = str(message or "")
    normalized = _normalize(text)
    question = ("?" in text) or _looks_like_question(normalized)

    if not question and _is_clear_denial(normalized):
        decision.status = "cancelled"
        try:
            es.post_failure_state = ""
            es.session_state = "REPAIRING" if bool(getattr(es, "retry_requires_draft_change", False)) else "IDLE"
        except Exception:
            pass
        _log_runtime_event(
            runtime,
            "pending_decision_cancelled",
            {"kind": decision.kind, "options": list(decision.options)},
        )
        return PendingDecisionResolution("cancelled")

    answered = "" if question else _match_option(normalized, decision.options)

    if answered:
        decision.status = "answered"
        decision.answered_with = answered
        decision.answered_at_turn = _next_turn(runtime)
        try:
            if str(decision.kind or "") in {"strategy_choice", "repair_direction", "write_confirmation"}:
                es.post_failure_state = "STRATEGY_APPROVED"
                es.session_state = "STRATEGY_APPROVED"
                es.approved_strategy_label = answered
                es.approved_strategy_prompt = text[:500]
                es.pending_draft_action = "write_approved_strategy_revision"
                # Preserve existing pending_draft_prompt (diagnosis context) — append user approval.
                existing_prompt = str(getattr(es, "pending_draft_prompt", "") or "").strip()
                if existing_prompt and len(existing_prompt) > 100:
                    es.pending_draft_prompt = existing_prompt[:1200] + f"\n\nUser approval: {text[:200]}"
                else:
                    es.pending_draft_prompt = text[:800]
        except Exception:
            pass
        _log_runtime_event(
            runtime,
            "pending_decision_resolved",
            {
                "kind": decision.kind,
                "answered_with": answered,
                "options": list(decision.options),
                "answered_at_turn": int(decision.answered_at_turn),
            },
        )
        return PendingDecisionResolution("answered", answered_with=answered)

    if question:
        _log_runtime_event(
            runtime,
            "pending_decision_kept",
            {"kind": decision.kind, "reason": "user_question", "options": list(decision.options)},
        )
        return PendingDecisionResolution("pending", question=True)

    if _is_ambiguous_affirmative(normalized):
        _log_runtime_event(
            runtime,
            "pending_decision_kept",
            {"kind": decision.kind, "reason": "ambiguous_affirmative", "options": list(decision.options)},
        )
        return PendingDecisionResolution("pending", needs_clarification=True)

    if _mentions_unavailable_strategy_choice(normalized, decision.options):
        _log_runtime_event(
            runtime,
            "pending_decision_kept",
            {"kind": decision.kind, "reason": "option_outside_pending_decision", "options": list(decision.options)},
        )
        return PendingDecisionResolution("pending", needs_clarification=True)

    _log_runtime_event(
        runtime,
        "pending_decision_kept",
        {"kind": decision.kind, "reason": "no_match", "normalized": normalized[:80], "options": list(decision.options)},
    )
    return PendingDecisionResolution("pending")


def clarification_response(session: Any) -> str:
    es = getattr(session, "execution_state", None)
    decision = getattr(es, "pending_user_decision", None) if es is not None else None
    options = list(getattr(decision, "options", []) or [])
    pos = _positive_options(options)
    if len(pos) >= 2:
        return f"Qual opção você quer seguir — {pos[0]} ou {pos[1]}?"
    if len(pos) == 1:
        return f"Confirma que quer seguir com a direção proposta?"
    return "Qual direção você quer seguir?"


def _normalize(text: str) -> str:
    raw = unicodedata.normalize("NFKD", str(text or ""))
    no_marks = "".join(ch for ch in raw if not unicodedata.combining(ch))
    lowered = no_marks.lower()
    out = []
    for ch in lowered:
        out.append(ch if ch.isalnum() else " ")
    return " ".join("".join(out).split())


_NEGATIVE_NORMS = {"nao", "nenhuma", "nenhum", "cancelar", "cancela"}
_AFFIRMATIVES = {
    "sim", "pode", "ok", "okay", "pode seguir", "pode continuar",
    "segue", "siga", "confirma", "confirmo", "confirmado", "concordo",
    "certo", "claro", "feito", "vai", "bora", "vamos", "manda",
    "vamos la", "vamo la", "tudo bem", "por favor",
}
_STRATEGY_WORDS = {"caminho", "opcao", "opcoes", "estrategia", "abordagem", "path", "option", "rota"}


def _positive_options(options: list[str]) -> list[str]:
    """Return options that are not clear negatives/cancellations."""
    return [o for o in options if _normalize(o) not in _NEGATIVE_NORMS and str(o).strip()]


def _match_option(normalized_message: str, options: list[str]) -> str:
    if not normalized_message or not options:
        return ""
    word_list = normalized_message.split()
    words = set(word_list)
    ordinals = {
        "1": 0,
        "primeira": 0,
        "primeiro": 0,
        "segunda": 1,
        "segundo": 1,
        "2": 1,
        "terceira": 2,
        "terceiro": 2,
        "3": 2,
    }
    for token, index in ordinals.items():
        if token in words and index < len(options):
            positions = [idx for idx, word in enumerate(word_list) if word == token]
            last_pos = max(positions) if positions else -1
            is_end_of_short = (last_pos == len(word_list) - 1) and len(word_list) <= 4
            has_strategy_ctx = bool(words & _STRATEGY_WORDS)
            if not (is_end_of_short or has_strategy_ctx):
                continue
            return str(options[index])
    normalized_options = [(_normalize(opt), str(opt)) for opt in options if str(opt).strip()]
    option_map = {norm: original for norm, original in normalized_options}
    pos = _positive_options(options)
    # Single positive path: any affirmative word anywhere in the message resolves to it.
    # Phrase-level denials are caught upstream by _is_clear_denial before this function
    # runs, so matching any affirmative word here is safe.
    if len(pos) == 1 and bool(words & _AFFIRMATIVES):
        return str(pos[0])
    # Single positive path: strategy-language approval ("caminho B", "opção A", "path X")
    # when the user is referencing a path but options only have one non-negative choice.
    if len(pos) == 1 and bool(words & _STRATEGY_WORDS):
        return str(pos[0])
    best: tuple[int, str] | None = None
    for norm, original in normalized_options:
        if not norm:
            continue
        positions = [index for index, word in enumerate(word_list) if word == norm]
        if positions:
            # Harden single-letter option matching to prevent Portuguese articles ("a", "e")
            # from matching option labels.  A single-letter option is accepted only when:
            #   (a) it is the final word of a short message (≤3 words), or
            #   (b) the message contains an explicit strategy-context word.
            if len(norm) == 1:
                last_pos = max(positions)
                is_end_of_short = (last_pos == len(word_list) - 1) and len(word_list) <= 3
                has_strategy_ctx = bool(words & _STRATEGY_WORDS)
                if not (is_end_of_short or has_strategy_ctx):
                    continue
            candidate = (max(positions), original)
            if best is None or candidate[0] > best[0]:
                best = candidate
    if best is not None:
        return best[1]
    return ""


def _looks_like_question(normalized_message: str) -> bool:
    if not normalized_message:
        return False
    starts = ("por que", "porque", "como", "qual", "quais", "o que", "onde", "quando")
    return normalized_message.startswith(starts) or normalized_message.startswith("mas por que")


def _is_clear_denial(normalized_message: str) -> bool:
    if not normalized_message:
        return False
    words = set(normalized_message.split())
    return bool(words & {"nao", "nenhuma", "nenhum", "esquece", "cancela", "cancelar"}) or normalized_message.startswith("muda")


def _is_ambiguous_affirmative(normalized_message: str) -> bool:
    if not normalized_message:
        return False
    words = set(normalized_message.split())
    return bool(words & _AFFIRMATIVES)


def _mentions_unavailable_strategy_choice(normalized_message: str, options: list[str]) -> bool:
    if not normalized_message:
        return False
    normalized_options = {_normalize(option) for option in options if str(option).strip()}
    if {"a", "b"} & normalized_options:
        return False
    # Single positive path: strategy language is just the user approving; let _match_option handle it.
    if len(_positive_options(options)) <= 1:
        return False
    words = set(normalized_message.split())
    mentions_choice = bool(words & {"a", "b", "primeira", "segunda", "1", "2"})
    mentions_strategy = bool(words & {"caminho", "opcao", "estrategia", "abordagem"})
    return mentions_choice and mentions_strategy


def _next_turn(runtime: Any) -> int:
    state = getattr(runtime, "_session_state", {}) if runtime is not None else {}
    if isinstance(state, dict):
        return int(state.get("turn_counter") or 0) + 1
    return 0


def _log_runtime_event(runtime: Any, event_type: str, payload: dict[str, Any]) -> None:
    journal = getattr(runtime, "journal", None)
    if journal is None:
        return
    try:
        journal.log_runtime_event(event_type=event_type, payload=payload)
    except Exception:
        pass
