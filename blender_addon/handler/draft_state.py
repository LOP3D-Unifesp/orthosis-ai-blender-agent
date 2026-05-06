"""Draft workspace state loading, metadata sync, and intent mode helpers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable

from . import TurnContext
from .draft_policy import _normalize_draft_goal_mode
from ..session.schema import DraftedScript

_DIAGNOSE_ONLY_RE = re.compile(
    r"\b("
    r"diagnostic|diagnostico|diagn[oó]stico|analis|analisa|analisar|investiga|investigar|"
    r"estrategia|estratégia|strategy|reflection|reflex[aã]o|reflexao|"
    r"por\s+que|porque|what\s+is\s+wrong|what's\s+wrong|why|o\s+que\s+esta\s+errado|"
    r"me\s+explica|explica\s+o\s+problema|qual\s+o\s+problema"
    r")\b",
    re.IGNORECASE,
)
_FUNCTIONAL_EXPANSION_RE = re.compile(
    r"\b("
    r"adicion|inclu|expand|estend|ampli|implement|faz|fazer|cria|criar|gera|gerar|"
    r"novo\s+recurso|nova\s+fase|nova\s+parte|suporte\s+para|support\s+for|"
    r"agora\s+quero|tamb[eé]m\s+quero"
    r")\b",
    re.IGNORECASE,
)
_FOCAL_CORRECTION_RE = re.compile(
    r"\b("
    r"corrig|corrige|conserta|ajust|refina|melhor|revis|tenta\s+de\s+novo|retry|"
    r"preserv|mant[eé]m|sem\s+quebrar|fix|repair|patch|"
    r"n[aã]o\s+(acontece|acompanha|fica|segue)|nao\s+(acontece|acompanha|fica|segue)|"
    r"avanca|avança|recua|descola|grudad[oa]s?|colad[oa]s?|face\s+frontal"
    r")\b",
    re.IGNORECASE,
)
_EXPLICIT_WRITE_RE = re.compile(
    r"\b("
    r"corrig|conserta|ajust|refina|melhor|revis|reescrev|edita|atualiz|"
    r"adicion|inclu|expand|estend|ampli|implement|"
    r"retarget|rebuild|muda|troca|substitui|escrev|salv|continua|continue"
    r")\b",
    re.IGNORECASE,
)
_SHORT_CONFIRMATION_RE = re.compile(
    r"^\s*(pode|sim|ok|claro|manda|vai|bora|yes|sure|go\s+ahead|do\s+it)\s*[!.]?\s*$",
    re.IGNORECASE,
)
_DRAFT_RETRY_REQUEST_RE = re.compile(
    r"\b("
    r"consegue\s+tentar|pode\s+tentar|tenta|tentar|refaz|refazer|reescreve|reescrever|"
    r"consegue\s+seguir|pode\s+seguir|seguir\s+agora|sabe\s+o\s+que\s+precisa\s+fazer|"
    r"sabe\s+oq\s+precisa\s+fazer|sabe\s+como\s+seguir|de\s+novo|denovo|try\s+again|retry"
    r")\b",
    re.IGNORECASE,
)
_DRAFT_ACTION_OFFER_RE = re.compile(
    r"\b(posso|quer|devo|vamos|vou)\b.{0,120}\b(escrever|reescrever|corrigir|ajustar|salvar|gerar|criar)\b.{0,120}\b(draft|script|codigo|revisao)\b",
    re.IGNORECASE | re.DOTALL,
)
_INTENTIONAL_REBUILD_RE = re.compile(
    r"\b("
    r"do\s+zero|from\s+scratch|rebuild|reconstru(ir|cao)|reestrutur(ar|a[cç][aã]o)|"
    r"refazer\s+tudo|reescrever\s+tudo|reorganizar\s+inteir|recriar\s+inteir|"
    r"pode\s+quebrar|nao\s+precisa\s+preservar|sem\s+preservar"
    r")\b",
    re.IGNORECASE,
)
_INTENTIONAL_RETARGET_RE = re.compile(
    r"\b("
    r"retarget|mudar\s+de\s+arvor|trocar\s+de\s+arvor|outra\s+arvor|novo\s+node\s+group|"
    r"outro\s+node\s+group|outro\s+modifier|novo\s+modifier|mover\s+para\s+outra\s+arvor|"
    r"apontar\s+para\s+outra\s+arvor|usar\s+a\s+arvor\s+"
    r")\b",
    re.IGNORECASE,
)
_VALID_DRAFT_EDIT_MODES = frozenset({
    "preserve_and_refine",
    "intentional_rebuild",
    "intentional_retarget",
})


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
    if not (_SHORT_CONFIRMATION_RE.match(message or "") or _DRAFT_RETRY_REQUEST_RE.search(message or "")):
        return ""
    action = str(getattr(es, "pending_draft_action", "") or "").strip()
    prompt = str(getattr(es, "pending_draft_prompt", "") or "").strip()
    if not action:
        last_assistant = _last_assistant_text(session)
        if _DRAFT_ACTION_OFFER_RE.search(last_assistant):
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
    if _DRAFT_RETRY_REQUEST_RE.search(message or ""):
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
    if _INTENTIONAL_RETARGET_RE.search(str(message or "")):
        return "intentional_retarget"
    if _INTENTIONAL_REBUILD_RE.search(str(message or "")):
        return "intentional_rebuild"
    if "living-draft preservation fix" in prompt or "preserve the existing live node anchors" in prompt:
        return "preserve_and_refine"
    if (
        (_SHORT_CONFIRMATION_RE.match(message or "") or _DRAFT_RETRY_REQUEST_RE.search(message or ""))
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
    body = str(message or "")
    return bool(_EXPLICIT_WRITE_RE.search(body) or _SHORT_CONFIRMATION_RE.match(body))


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
    if _DIAGNOSE_ONLY_RE.search(body) and not explicit_write:
        return "diagnose_only"
    if (_SHORT_CONFIRMATION_RE.match(body) or _DRAFT_RETRY_REQUEST_RE.search(body)) and persisted_mode:
        if (
            persisted_mode == "functional_expansion"
            and not current_draft_content.strip()
            and not _INTENTIONAL_REBUILD_RE.search(body)
        ):
            return "focal_correction"
        return persisted_mode
    if bool(getattr(es, "retry_requires_draft_change", False)):
        return "focal_correction"
    outcome = str(getattr(es, "last_execution_outcome", "") or "").strip().lower()
    if outcome in {"executed_no_effect", "executed_failed", "executed_partial_failure", "reverted_by_user"}:
        if current_draft_content.strip():
            return "focal_correction"
    if _FUNCTIONAL_EXPANSION_RE.search(body) and not _FOCAL_CORRECTION_RE.search(body):
        return "functional_expansion"
    if _FOCAL_CORRECTION_RE.search(body):
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
    if _DRAFT_ACTION_OFFER_RE.search(text):
        es.pending_draft_action = "write_confirmed_draft_revision"
        es.pending_draft_prompt = (
            "User message:\n"
            f"{str(message or '')[:500]}\n\n"
            "Assistant proposal:\n"
            f"{text[:1200]}"
        )
        return
    if not (_SHORT_CONFIRMATION_RE.match(message or "") or _DRAFT_RETRY_REQUEST_RE.search(message or "")):
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
