"""Draft workspace finalization helpers."""

from __future__ import annotations

import json
from typing import Any

from . import TurnContext
from .draft_policy import _normalize_draft_goal_mode


def _recent_write_calls(runtime) -> list[dict]:
    calls: list[dict] = []
    for call in list(getattr(runtime, "_current_turn_tools", []) or []):
        if not isinstance(call, dict):
            continue
        if str(call.get("name") or "") == "write_script_draft":
            calls.append(call)
    return calls


def _last_successful_write(runtime) -> tuple[dict, dict]:
    calls = _recent_write_calls(runtime)
    for call in reversed(calls):
        status = str(call.get("status") or "").lower()
        payload = call.get("result_payload")
        payload_dict = dict(payload) if isinstance(payload, dict) else {}
        skipped = bool(payload_dict.get("skipped_placeholder_write", False))
        if status == "success" and not skipped:
            raw = call.get("input")
            return (dict(raw) if isinstance(raw, dict) else {}, payload_dict)
    return {}, {}


def _last_failed_write(runtime) -> tuple[dict, str, dict]:
    calls = _recent_write_calls(runtime)
    for call in reversed(calls):
        status = str(call.get("status") or "").lower()
        if status and status != "success":
            raw = call.get("input")
            payload = call.get("result_payload")
            return (
                dict(raw) if isinstance(raw, dict) else {},
                str(call.get("result") or ""),
                dict(payload) if isinstance(payload, dict) else {},
            )
    return {}, "", {}


def _current_turn_tool_names(runtime) -> list[str]:
    calls = getattr(runtime, "_current_turn_tools", []) if runtime is not None else []
    if not isinstance(calls, list):
        return []
    names: list[str] = []
    for call in calls:
        if not isinstance(call, dict):
            continue
        name = str(call.get("name") or "").strip()
        if name:
            names.append(name)
    return names


def _draft_no_write_reason(
    state: Any,
    *,
    tool_policy: dict[str, Any],
    runtime,
) -> tuple[str, str]:
    goal_mode = str(tool_policy.get("goal_mode") or getattr(state, "goal_mode", "") or "")
    if goal_mode == "diagnose_only" or not bool(tool_policy.get("write_allowed", False)):
        return (
            "diagnose_only",
            "Nao salvei o draft porque este turno estava em modo de diagnostico; primeiro eu precisava analisar antes de propor uma revisao.",
        )

    attempt_state = getattr(runtime, "_draft_attempt_state", None)
    block_reason = str(getattr(attempt_state, "last_block_reason", "") or "")
    if block_reason == "draft_source_not_read":
        return (
            block_reason,
            "Nao salvei o draft porque o `GN_Agent_Draft` atual nao foi relido neste turno.",
        )
    if block_reason == "draft_target_not_resolved":
        return (
            block_reason,
            "Nao salvei o draft porque a arvore alvo nao foi resolvida com seguranca neste turno.",
        )
    if block_reason == "draft_context_gate_missing":
        return (
            block_reason,
            "Nao salvei o draft porque faltou contexto deterministico minimo para uma escrita segura.",
        )
    if block_reason == "draft_context_not_collected":
        return (
            block_reason,
            "Nao salvei o draft porque o contexto preparado ainda nao foi coletado neste turno.",
        )
    if block_reason == "draft_structural_memory_missing":
        return (
            block_reason,
            "Nao salvei o draft porque a leitura fresca da arvore GN falhou. Vou precisar da bridge funcionando para escrever uma revisao decente, sem chutar nomes de nos ou sockets.",
        )
    if block_reason.startswith("draft_context_gate_blocked:"):
        blockers = [item for item in block_reason.split(":", 1)[1].split(",") if item]
        blocker_text = ", ".join(sorted({str(item).strip() for item in blockers if str(item).strip()}))
        return (
            "prepared_context_blocked",
            "Nao salvei o draft porque o contexto preparado ainda estava bloqueado"
            + (f": {blocker_text}." if blocker_text else "."),
        )
    if block_reason == "write_not_allowed_for_turn":
        return (
            block_reason,
            "Nao salvei o draft porque este turno nao permitia escrita.",
        )

    prepared_blockers = [
        str(item).strip()
        for item in (tool_policy.get("prepared_context_blockers") or [])
        if str(item).strip()
    ]
    if prepared_blockers:
        blocker_text = ", ".join(sorted(dict.fromkeys(prepared_blockers)))
        return (
            "prepared_context_blocked",
            f"Nao salvei o draft porque o contexto preparado ainda estava bloqueado: {blocker_text}.",
        )

    tool_names = _current_turn_tool_names(runtime)
    if "prepare_draft_context" not in tool_names:
        return (
            "prepared_context_not_requested",
            "Nao salvei o draft porque o turno terminou antes de preparar o contexto de escrita.",
        )
    if "write_script_draft" not in tool_names:
        return (
            "write_not_attempted",
            "Nao salvei o draft porque o agente ficou em leitura e nao chegou a chamar `write_script_draft`.",
        )
    return (
        "write_not_completed",
        "Nao salvei o draft porque a tentativa nao chegou a uma revisao completa valida.",
    )


def _log_draft_workspace_outcome(
    ctx: TurnContext,
    *,
    state: Any,
    tool_policy: dict[str, Any],
    outcome: str,
    reason: str = "",
) -> None:
    tool_names = _current_turn_tool_names(getattr(ctx, "_runtime", None))
    ctx.log_event("draft_workspace_outcome", {
        "handler": "draft_workspace",
        "turn_class": "draft_workspace",
        "goal_mode": str(tool_policy.get("goal_mode") or getattr(state, "goal_mode", "") or ""),
        "write_allowed": bool(tool_policy.get("write_allowed", False)),
        "write_script_draft_exposed": True,
        "write_script_draft_called": "write_script_draft" in tool_names,
        "tools_called": tool_names,
        "outcome": outcome,
        "reason": reason,
    })


def _failed_write_diagnostics(failed_write_result: str, failed_write_payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(failed_write_payload) if isinstance(failed_write_payload, dict) else {}
    text = str(failed_write_result or "")
    parsed = {}
    try:
        maybe = json.loads(text)
        if isinstance(maybe, dict):
            parsed = maybe
    except Exception:
        parsed = {}
    error_text = str(parsed.get("error") or "")
    if not error_text:
        error_text = text
    reject_reason = str(payload.get("reject_reason") or "")
    return {
        "error_text": error_text,
        "reject_reason": reject_reason,
        "goal_mode": str(payload.get("goal_mode") or ""),
        "goal_guidance": payload.get("goal_guidance", {}) if isinstance(payload.get("goal_guidance"), dict) else {},
        "tree_name": str(payload.get("tree_name") or ""),
        "previous_tree_name": str(payload.get("previous_tree_name") or ""),
        "previous_live_node_refs": payload.get("previous_live_node_refs", []) if isinstance(payload.get("previous_live_node_refs"), list) else [],
        "candidate_live_node_refs": payload.get("candidate_live_node_refs", []) if isinstance(payload.get("candidate_live_node_refs"), list) else [],
        "previous_parameter_refs": payload.get("previous_parameter_refs", []) if isinstance(payload.get("previous_parameter_refs"), list) else [],
        "candidate_parameter_refs": payload.get("candidate_parameter_refs", []) if isinstance(payload.get("candidate_parameter_refs"), list) else [],
        "previous_focus_regions": payload.get("previous_focus_regions", []) if isinstance(payload.get("previous_focus_regions"), list) else [],
        "candidate_focus_regions": payload.get("candidate_focus_regions", []) if isinstance(payload.get("candidate_focus_regions"), list) else [],
    }


def _semantic_regression_retry_guidance(diagnostics: dict[str, Any]) -> str:
    reject_reason = str(diagnostics.get("reject_reason") or "")
    goal_mode = _normalize_draft_goal_mode(diagnostics.get("goal_mode"))
    goal_guidance = diagnostics.get("goal_guidance", {}) if isinstance(diagnostics.get("goal_guidance"), dict) else {}
    guidance_summary = str(goal_guidance.get("summary") or "").strip()
    suggested_output = str(goal_guidance.get("suggested_output") or "").strip()
    focus_priorities = goal_guidance.get("focus_priorities", []) if isinstance(goal_guidance.get("focus_priorities"), list) else []
    previous_tree_name = str(diagnostics.get("previous_tree_name") or diagnostics.get("tree_name") or "").strip()
    previous_refs = diagnostics.get("previous_live_node_refs", []) if isinstance(diagnostics.get("previous_live_node_refs"), list) else []
    candidate_refs = diagnostics.get("candidate_live_node_refs", []) if isinstance(diagnostics.get("candidate_live_node_refs"), list) else []
    previous_parameters = diagnostics.get("previous_parameter_refs", []) if isinstance(diagnostics.get("previous_parameter_refs"), list) else []
    candidate_parameters = diagnostics.get("candidate_parameter_refs", []) if isinstance(diagnostics.get("candidate_parameter_refs"), list) else []
    previous_regions = diagnostics.get("previous_focus_regions", []) if isinstance(diagnostics.get("previous_focus_regions"), list) else []
    candidate_regions = diagnostics.get("candidate_focus_regions", []) if isinstance(diagnostics.get("candidate_focus_regions"), list) else []
    if goal_mode == "diagnose_only":
        guidance = (
            "Previous write_script_draft failed because the candidate regressed the living draft during a diagnosis-first turn.\n"
            "Retry should not jump straight to another rewrite: first explain the likely failure and propose the smallest safe next correction.\n"
        )
    elif goal_mode == "functional_expansion":
        guidance = (
            "Previous write_script_draft failed because the candidate regressed the living draft while trying to expand it.\n"
            "Retry must extend the current GN_Agent_Draft incrementally instead of replacing working capabilities blindly.\n"
        )
    else:
        guidance = (
            "Previous write_script_draft failed because the candidate regressed the living draft.\n"
            "Retry must preserve the current GN_Agent_Draft capabilities instead of replacing them blindly.\n"
        )
    if guidance_summary:
        guidance += f"Mode guidance: {guidance_summary}\n"
    if reject_reason.startswith("target_tree_changed:") and previous_tree_name:
        guidance += f"Keep the draft on the existing target tree `{previous_tree_name}` unless the user explicitly asks to branch or retarget.\n"
    if reject_reason.startswith(("regression_lost_live_node_refs", "regression_replaced_live_node_refs")):
        if previous_refs:
            guidance += (
                "Preserve the existing live node anchors already used by the current draft: "
                + ", ".join(str(item) for item in previous_refs[:8] if str(item).strip())
                + ".\n"
            )
        guidance += "Do not drop or replace those live references unless the replacement still keeps the same functional anchors.\n"
    if reject_reason.startswith(("regression_lost_expected_parameters", "regression_replaced_expected_parameters")) and previous_parameters:
        guidance += (
            "Preserve the parameter semantics already present in the living draft: "
            + ", ".join(str(item) for item in previous_parameters[:8] if str(item).strip())
            + ".\n"
        )
    if reject_reason.startswith(("regression_lost_focus_regions", "regression_replaced_focus_regions")) and previous_regions:
        guidance += (
            "Preserve the focus regions already covered by the living draft: "
            + ", ".join(str(item) for item in previous_regions[:8] if str(item).strip())
            + ".\n"
        )
    if focus_priorities:
        guidance += (
            "Prioritize: "
            + ", ".join(str(item) for item in focus_priorities[:8] if str(item).strip())
            + ".\n"
        )
    if suggested_output:
        guidance += f"Expected output shape: {suggested_output}.\n"
    if candidate_refs or candidate_parameters or candidate_regions:
        guidance += (
            "The rejected candidate shifted toward: "
            + "; ".join(
                part for part in [
                    "nodes=" + ", ".join(str(item) for item in candidate_refs[:5]) if candidate_refs else "",
                    "parameters=" + ", ".join(str(item) for item in candidate_parameters[:5]) if candidate_parameters else "",
                    "regions=" + ", ".join(str(item) for item in candidate_regions[:5]) if candidate_regions else "",
                ]
                if part
            )
            + ". Avoid that drift unless it is explicitly requested.\n"
        )
    return guidance.strip()
