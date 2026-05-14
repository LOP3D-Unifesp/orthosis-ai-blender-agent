"""Draft workspace state loading, metadata sync, and intent mode helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from . import TurnContext
from .draft_policy import _normalize_draft_goal_mode
from ..session.schema import DraftedScript
from ..text_utils import _has_phrase, _has_prefix, _message_words

_VALID_DRAFT_EDIT_MODES = frozenset({
    "preserve_and_refine",
    "intentional_rebuild",
    "intentional_retarget",
})


def _is_short_confirmation(message: str) -> bool:
    words = _message_words(message)
    return words in (
        ["pode"], ["sim"], ["ok"], ["claro"], ["manda"], ["vai"], ["bora"],
        ["yes"], ["sure"], ["go", "ahead"], ["do", "it"],
    )


def _is_draft_retry_request(message: str) -> bool:
    words = _message_words(message)
    word_set = set(words)
    return (
        _has_prefix(words, "tenta", "refaz", "reescrev")
        or bool({"denovo", "retry"} & word_set)
        or _has_phrase(words, "de", "novo")
        or _has_phrase(words, "try", "again")
        or _has_phrase(words, "consegue", "seguir")
        or _has_phrase(words, "pode", "seguir")
        or _has_phrase(words, "seguir", "agora")
        or ("sabe" in word_set and "seguir" in word_set)
        or ("sabe" in word_set and "fazer" in word_set)
    )


def _has_draft_action_offer(message: str) -> bool:
    words = _message_words(message)
    word_set = set(words)
    return (
        bool({"posso", "quer", "devo", "vamos", "vou"} & word_set)
        and _has_prefix(words, "escrev", "reescrev", "corrig", "ajust", "salv", "ger", "cri")
        and bool({"draft", "script", "codigo", "revisao"} & word_set)
    )


def _is_intentional_rebuild(message: str) -> bool:
    words = _message_words(message)
    word_set = set(words)
    return (
        "rebuild" in word_set
        or _has_phrase(words, "do", "zero")
        or _has_phrase(words, "from", "scratch")
        or _has_prefix(words, "reconstru", "reestrutur")
        or (_has_prefix(words, "refaz", "reescrev", "reorganiz", "recri") and "tudo" in word_set)
        or _has_phrase(words, "pode", "quebrar")
        or _has_phrase(words, "sem", "preservar")
        or ("nao" in word_set and "precisa" in word_set and _has_prefix(words, "preserv"))
    )


def _is_intentional_retarget(message: str) -> bool:
    words = _message_words(message)
    word_set = set(words)
    return (
        "retarget" in word_set
        or (bool({"mudar", "trocar", "mover", "apontar", "usar"} & word_set) and _has_prefix(words, "arvor"))
        or (_has_prefix(words, "outr", "nov") and (_has_phrase(words, "node", "group") or "modifier" in word_set))
    )


def _is_diagnose_only_request(message: str) -> bool:
    words = _message_words(message)
    return (
        _has_prefix(words, "diagnostic", "analis", "investig", "estrateg", "reflex")
        or _has_phrase(words, "por", "que")
        or "porque" in words
        or "why" in words
        or _has_phrase(words, "what", "is", "wrong")
        or _has_phrase(words, "o", "que", "esta", "errado")
        or _has_phrase(words, "me", "explica")
        or _has_phrase(words, "explica", "o", "problema")
        or _has_phrase(words, "qual", "o", "problema")
    )


def _is_functional_expansion_request(message: str) -> bool:
    words = _message_words(message)
    return (
        _has_prefix(words, "adicion", "inclu", "expand", "estend", "ampli", "implement", "faz", "cri", "ger")
        or _has_phrase(words, "novo", "recurso")
        or _has_phrase(words, "nova", "fase")
        or _has_phrase(words, "nova", "parte")
        or _has_phrase(words, "suporte", "para")
        or _has_phrase(words, "support", "for")
        or _has_phrase(words, "agora", "quero")
        or _has_phrase(words, "tambem", "quero")
    )


def _is_focal_correction_request(message: str) -> bool:
    words = _message_words(message)
    word_set = set(words)
    negative_motion = "nao" in word_set and bool({"acontece", "acompanha", "fica", "segue"} & word_set)
    return (
        _has_prefix(words, "corrig", "consert", "ajust", "refina", "melhor", "revis", "preserv", "mant")
        or _is_draft_retry_request(message)
        or bool({"retry", "fix", "repair", "patch"} & word_set)
        or _has_phrase(words, "sem", "quebrar")
        or negative_motion
        or _has_prefix(words, "avanca", "recua", "descola", "grudad", "colad")
        or _has_phrase(words, "face", "frontal")
    )


def _read_draft_info(ctx: TurnContext, block_name: str) -> dict:
    raw_info = _read_draft_payload(ctx, block_name)
    result = raw_info.get("result")
    return result if isinstance(result, dict) else {}


def _read_draft_payload(ctx: TurnContext, block_name: str) -> dict:
    try:
        raw = ctx.execute_tool("read_script_draft", {"block_name": block_name})
        if str(raw).startswith(("ERROR:", "BLOCKED:")):
            return {"status": "error", "error": str(raw), "result": {}}
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return {"status": "", "error": "", "result": {}}
        result = parsed.get("result", parsed)
        return {
            "status": str(parsed.get("status") or ""),
            "error": str(parsed.get("error") or ""),
            "result": result if isinstance(result, dict) else {},
        }
    except Exception:
        return {"status": "error", "error": "read_script_draft_exception", "result": {}}


def _target_tree_for_draft(ctx: TurnContext, draft: DraftedScript | None = None) -> str:
    runtime_memory = getattr(ctx._runtime, "_session_memory", {}) or {}
    if not isinstance(runtime_memory, dict):
        runtime_memory = {}
    return str(
        getattr(draft, "tree_name", "")
        or getattr(ctx.session.execution_state, "draft_target_tree", "")
        or runtime_memory.get("target_tree", "")
        or ""
    ).strip()


def _sync_draft_metadata_from_read(ctx: TurnContext, block_name: str, info: dict) -> DraftedScript | None:
    if not isinstance(info, dict) or not info:
        return None
    es = ctx.session.execution_state
    existing = getattr(es, "current_draft", None)
    version = int(
        info.get("version")
        or getattr(existing, "version", 0)
        or getattr(es, "draft_revision", 0)
        or 0
    )
    if version <= 0:
        version = 1
    description = str(info.get("description") or getattr(existing, "description", "") or "")[:500]
    tree_name = str(info.get("tree_name") or getattr(existing, "tree_name", "") or getattr(es, "draft_target_tree", "") or "")
    char_count = int(info.get("char_count") or len(str(info.get("content") or "")))
    draft = DraftedScript(
        block_name=str(info.get("block_name") or block_name or "GN_Agent_Draft"),
        description=description,
        tree_name=tree_name,
        version=version,
        status=str(getattr(existing, "status", "") or "open"),
        last_written_chars=char_count,
        appended_last=bool(getattr(existing, "appended_last", False)),
        revision_parent=int(info.get("revision_parent") or getattr(existing, "revision_parent", 0) or getattr(es, "revision_parent", 0) or 0),
        revision_kind=str(info.get("revision_kind") or getattr(existing, "revision_kind", "") or getattr(es, "revision_kind", "") or ""),
        revision_changed_from_previous=str(
            info.get("revision_changed_from_previous")
            or getattr(existing, "revision_changed_from_previous", "")
            or getattr(es, "revision_changed_from_previous", "")
            or ""
        ),
        revision_validity=str(info.get("current_revision_validity") or info.get("revision_validity") or getattr(existing, "revision_validity", "") or "partial"),
    )
    es.current_draft = draft
    es.draft_revision = version
    es.draft_block_name = draft.block_name
    es.draft_target_tree = tree_name
    es.last_saved_char_count = char_count
    es.last_saved_summary = description
    es.current_revision_validity = draft.revision_validity
    es.revision_parent = draft.revision_parent
    es.revision_kind = draft.revision_kind
    es.revision_changed_from_previous = draft.revision_changed_from_previous
    es.last_valid_draft_revision = int(info.get("last_valid_draft_revision") or getattr(es, "last_valid_draft_revision", 0) or (version if draft.revision_validity == "valid" else 0))
    es.last_failed_revision = int(info.get("last_failed_revision") or getattr(es, "last_failed_revision", 0) or 0)
    return draft


def _last_assistant_text(session) -> str:
    history = getattr(getattr(session, "history", None), "messages", []) or []
    for item in reversed(history):
        role = str(getattr(item, "role", "") or "")
        if role != "assistant":
            continue
        content = str(getattr(item, "content", "") or "").strip()
        if content:
            return content
    return ""


def _normalize_draft_edit_mode(value: Any) -> str:
    mode = str(value or "").strip()
    if mode in _VALID_DRAFT_EDIT_MODES:
        return mode
    return "preserve_and_refine"


def _pending_action_instruction(es, session, message: str) -> str:
    if not (_is_short_confirmation(message) or _is_draft_retry_request(message)):
        return ""
    action = str(getattr(es, "pending_draft_action", "") or "").strip()
    prompt = str(getattr(es, "pending_draft_prompt", "") or "").strip()
    if not action:
        last_assistant = _last_assistant_text(session)
        if _has_draft_action_offer(last_assistant):
            action = "write_confirmed_draft_revision"
            prompt = last_assistant[:1200]
    if not action:
        return ""
    return (
        "\n\n[Pending confirmed draft action]\n"
        f"The user's short message confirms the pending action `{action}` from the previous assistant turn.\n"
        f"Previous proposal/context:\n{prompt[:1200]}\n"
        "Do not ask for confirmation again. If the pending action is a draft correction/write, read the current draft if needed, "
        "perform only the minimum targeted inspection needed, then save exactly one complete revised script with write_script_draft. "
        "After a successful write, stop and report the Text Editor revision."
    )


def _is_economy_retry_turn(es, session, message: str) -> bool:
    if _pending_action_instruction(es, session, message):
        return True
    if _is_draft_retry_request(message):
        return True
    if bool(getattr(es, "retry_requires_draft_change", False)):
        return True
    if str(getattr(es, "pending_draft_action", "") or "").strip():
        return True
    return False


def _detect_draft_edit_mode(es, session, message: str, current_draft_content: str) -> str:
    return _detect_draft_edit_mode_from_source(
        es,
        session,
        message,
        current_draft_content,
        stored_edit_mode=getattr(es, "draft_edit_mode", "preserve_and_refine"),
    )


def _detect_draft_edit_mode_from_source(
    es,
    session,
    message: str,
    current_draft_content: str,
    *,
    stored_edit_mode: Any = "preserve_and_refine",
) -> str:
    stored_mode = _normalize_draft_edit_mode(stored_edit_mode)
    prompt = str(getattr(es, "pending_draft_prompt", "") or "").strip().lower()
    if _is_intentional_retarget(message):
        return "intentional_retarget"
    if _is_intentional_rebuild(message):
        return "intentional_rebuild"
    if "living-draft preservation fix" in prompt or "preserve the existing live node anchors" in prompt:
        return "preserve_and_refine"
    if (
        (_is_short_confirmation(message) or _is_draft_retry_request(message))
        and (
            str(getattr(es, "pending_draft_action", "") or "").strip()
            or stored_mode != "preserve_and_refine"
        )
    ):
        return stored_mode
    if not str(current_draft_content or "").strip():
        return stored_mode if stored_mode != "preserve_and_refine" else "preserve_and_refine"
    return stored_mode if stored_mode != "preserve_and_refine" else "preserve_and_refine"


def _message_has_explicit_write_intent(message: str) -> bool:
    words = _message_words(message)
    return bool(
        _has_prefix(
            words,
            "corrig", "consert", "ajust", "refina", "melhor", "revis",
            "reescrev", "edita", "atualiz", "adicion", "inclu", "expand",
            "estend", "ampli", "implement", "retarget", "rebuild", "muda",
            "troca", "substitui", "escrev", "salv", "continua", "continue",
        )
        or _is_short_confirmation(message)
    )


def _detect_draft_goal_mode(es, session, message: str, current_draft_content: str) -> str:
    return _detect_draft_goal_mode_from_source(
        es,
        session,
        message,
        current_draft_content,
        stored_goal_mode="",
    )


def _detect_draft_goal_mode_from_source(
    es,
    session,
    message: str,
    current_draft_content: str,
    *,
    stored_goal_mode: str = "",
) -> str:
    body = str(message or "").strip()
    persisted_mode = _normalize_draft_goal_mode(stored_goal_mode)
    if not body:
        return persisted_mode
    if _pending_action_instruction(es, session, body):
        if persisted_mode and persisted_mode != "diagnose_only":
            return persisted_mode
        return "focal_correction" if current_draft_content.strip() else "functional_expansion"
    explicit_write = _message_has_explicit_write_intent(body)
    if _is_diagnose_only_request(body) and not explicit_write:
        return "diagnose_only"
    if (_is_short_confirmation(body) or _is_draft_retry_request(body)) and persisted_mode:
        if (
            persisted_mode == "functional_expansion"
            and not current_draft_content.strip()
            and not _is_intentional_rebuild(body)
        ):
            return "focal_correction"
        return persisted_mode
    if bool(getattr(es, "retry_requires_draft_change", False)):
        return "focal_correction"
    outcome = str(getattr(es, "last_execution_outcome", "") or "").strip().lower()
    if outcome in {"executed_no_effect", "executed_failed", "executed_partial_failure", "reverted_by_user"}:
        if current_draft_content.strip():
            return "focal_correction"
    if _is_functional_expansion_request(body) and not _is_focal_correction_request(body):
        return "functional_expansion"
    if _is_focal_correction_request(body):
        return "focal_correction"
    if explicit_write and current_draft_content.strip():
        return "focal_correction"
    if explicit_write:
        return "functional_expansion"
    if current_draft_content.strip():
        return persisted_mode if persisted_mode != "functional_expansion" else "focal_correction"
    return persisted_mode


def _store_pending_action_from_response(es, message: str, response: str) -> None:
    text = str(response or "").strip()
    if not text:
        return
    if _has_draft_action_offer(text):
        es.pending_draft_action = "write_confirmed_draft_revision"
        es.pending_draft_prompt = (
            "User message:\n"
            f"{str(message or '')[:500]}\n\n"
            "Assistant proposal:\n"
            f"{text[:1200]}"
        )
        return
    if not (_is_short_confirmation(message) or _is_draft_retry_request(message)):
        es.pending_draft_action = ""
        es.pending_draft_prompt = ""
        es.draft_edit_mode = "preserve_and_refine"


@dataclass
class DraftWorkspacePipelineState:
    es: Any
    draft: DraftedScript | None
    block_name: str
    economy_retry: bool
    draft_payload: dict[str, Any]
    info: dict[str, Any]
    content: str
    draft_obj: DraftedScript | None
    tree_name_hint: str
    runtime_memory: dict[str, Any]
    relevant_nodes: list[Any]
    edit_mode: str
    goal_mode: str
    goal_guidance: dict[str, Any]
    stored_edit_mode: str
    stored_live_node_refs: list[str]
    stored_expected_parameter_refs: list[str]
    stored_expected_focus_regions: list[str]


def _load_draft_workspace_state(
    ctx: TurnContext,
    *,
    target_tree_for_draft: Callable[[TurnContext, DraftedScript | None], str] | None = None,
) -> DraftWorkspacePipelineState:
    es = ctx.session.execution_state
    draft = getattr(es, "current_draft", None)
    block_name = str(getattr(draft, "block_name", "") or getattr(es, "draft_block_name", "") or "GN_Agent_Draft")
    economy_retry = _is_economy_retry_turn(es, ctx.session, ctx.message)
    draft_payload = _read_draft_payload(ctx, block_name)
    info = draft_payload.get("result") if isinstance(draft_payload, dict) else {}
    info = info if isinstance(info, dict) else {}
    content = str(info.get("content", ""))
    draft_obj = _sync_draft_metadata_from_read(ctx, block_name, info) if info else None
    resolver = target_tree_for_draft or _target_tree_for_draft
    tree_name_hint = str(
        info.get("tree_name", "") or getattr(draft_obj, "tree_name", "") or resolver(ctx, draft_obj)
    ).strip()
    runtime_memory = getattr(ctx._runtime, "_session_memory", {}) or {}
    if not isinstance(runtime_memory, dict):
        runtime_memory = {}
    relevant_nodes = runtime_memory.get("relevant_nodes") or []
    if not isinstance(relevant_nodes, list):
        relevant_nodes = []
    stored_edit_mode = str(info.get("edit_mode") or getattr(es, "draft_edit_mode", "preserve_and_refine"))
    edit_mode = _detect_draft_edit_mode_from_source(
        es,
        ctx.session,
        ctx.message,
        content,
        stored_edit_mode=stored_edit_mode,
    )
    meta_goal_mode = _normalize_draft_goal_mode(str(getattr(ctx.meta, "goal_mode", "") or "").strip())
    stored_goal_mode = str(info.get("goal_mode") or "").strip()
    goal_mode = _detect_draft_goal_mode_from_source(
        es,
        ctx.session,
        ctx.message,
        content,
        stored_goal_mode=stored_goal_mode,
    )
    if meta_goal_mode != "functional_expansion" or str(getattr(ctx.meta, "goal_mode", "") or "").strip():
        goal_mode = meta_goal_mode
    goal_guidance = info.get("goal_guidance", {}) if isinstance(info.get("goal_guidance"), dict) else {}
    stored_live_node_refs = info.get("live_node_refs", []) if isinstance(info.get("live_node_refs"), list) else []
    stored_expected_parameter_refs = info.get("expected_parameter_refs", []) if isinstance(info.get("expected_parameter_refs"), list) else []
    stored_expected_focus_regions = info.get("expected_focus_regions", []) if isinstance(info.get("expected_focus_regions"), list) else []
    es.draft_edit_mode = edit_mode
    return DraftWorkspacePipelineState(
        es=es,
        draft=draft,
        block_name=block_name,
        economy_retry=bool(economy_retry),
        draft_payload=draft_payload if isinstance(draft_payload, dict) else {},
        info=info,
        content=content,
        draft_obj=draft_obj,
        tree_name_hint=tree_name_hint,
        runtime_memory=runtime_memory,
        relevant_nodes=relevant_nodes,
        edit_mode=edit_mode,
        goal_mode=goal_mode,
        goal_guidance=goal_guidance,
        stored_edit_mode=_normalize_draft_edit_mode(stored_edit_mode),
        stored_live_node_refs=[str(item) for item in stored_live_node_refs if str(item).strip()][:8],
        stored_expected_parameter_refs=[str(item) for item in stored_expected_parameter_refs if str(item).strip()][:12],
        stored_expected_focus_regions=[str(item) for item in stored_expected_focus_regions if str(item).strip()][:12],
    )
