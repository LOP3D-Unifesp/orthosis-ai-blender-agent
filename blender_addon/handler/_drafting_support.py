"""Handlers for the unified draft workspace flow."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import HandlerResult, TurnContext
from .draft_policy import (
    _collect_named_terms,
    _dedupe_semantic_terms,
    _draft_coverage_refresh_status,
    _draft_workspace_tool_policy,
    _fallback_goal_guidance,
    _filter_actionable_focus_regions,
    _normalize_draft_goal_mode,
    _prepared_context_semantic_expectations,
    _semantic_identity,
)
from .draft_response import (
    _brief_chat_summary,
    _draft_source_note,
    _draft_summary,
    _finalize_round_limit_text,
    _line_count,
    _raw_python_draft_candidate,
    _runtime_loop_blocker,
    _sanitize_draft_chat_response,
    _validate_agent_loop_code_fence,
    extract_code_fences,
)
from .draft_finalize import (
    _current_turn_tool_names,
    _draft_no_write_reason,
    _failed_write_diagnostics,
    _last_failed_write,
    _last_successful_write,
    _log_draft_workspace_outcome,
    _recent_write_calls,
    _semantic_regression_retry_guidance,
)
from .draft_state import (
    DraftWorkspacePipelineState,
    _detect_draft_edit_mode,
    _detect_draft_edit_mode_from_source,
    _detect_draft_goal_mode,
    _detect_draft_goal_mode_from_source,
    _is_economy_retry_turn,
    _load_draft_workspace_state,
    _message_has_explicit_write_intent,
    _normalize_draft_edit_mode,
    _pending_action_instruction,
    _read_draft_info,
    _read_draft_payload,
    _store_pending_action_from_response,
    _sync_draft_metadata_from_read,
    _target_tree_for_draft,
)
from .feedback_evidence import (
    _analysis_has_diagnosis,
    _analysis_has_failure_reason,
    _analysis_is_useful,
    _analysis_strategy_count,
    _concrete_evidence_terms,
    _extract_failed_draft_static_evidence,
    _fallback_post_failure_diagnosis,
    _minimum_useful_analysis_response,
    _node_name_terms,
    _post_failure_contract_status,
    _post_failure_missing_sections,
    _post_failure_quality_status,
    _post_failure_strategy_count,
    _read_archived_draft_revision,
    _read_failed_draft_info,
    _render_failed_draft_evidence_pack,
    _structural_node_index,
    _text_mentions_any,
)
from .prompt import build_system_prompt
from ..runtime.tree_renderer import compact_tree_summary_for_baseline, render_compact_tree
from ..session.baseline import BaselineBuilder
from ..session.schema import DraftedScript
_EXECUTION_DIAGNOSIS_RE = re.compile(
    r"\b("
    r"erro|falh|deu\s+errado|n[aÃ£]o\s+(deu|funcionou|foi)|nada\s+aconteceu|"
    r"sem\s+efeito|ctrl\s*\+?\s*z|desfiz|revert|apagou|sumiu|problemas?|sliders?.*n[aÃ£]o|"
    r"por\s+que|porque|o\s+que\s+.*errad|n[aÃ£]o\s+esta\s+funcionando|why|wrong|failed|nothing\s+happened|no\s+effect"
    r")\b",
    re.IGNORECASE,
)
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
_TREE_CHANGED_BY_USER_RE = re.compile(
    r"\b("
    r"mudei|mudou|alterei|alterou|editei|mexi|modifiquei|"
    r"voltei|reverti|desfiz|undo|ctrl\s*\+?\s*z|restaurei|resetei|"
    r"arvor[ea]\s+(mudou|alterada|diferente|revertida|voltou)"
    r")\b",
    re.IGNORECASE,
)
_VALID_DRAFT_GOAL_MODES = {"diagnose_only", "focal_correction", "functional_expansion", "feedback_fix"}

def _replace_last_assistant_message(runtime, text: str) -> None:
    messages = getattr(runtime, "_messages", None)
    if not isinstance(messages, list) or not messages:
        return
    for idx in range(len(messages) - 1, -1, -1):
        item = messages[idx]
        if isinstance(item, dict) and item.get("role") == "assistant":
            messages[idx] = {"role": "assistant", "content": text}
            return


def _with_draft_streaming_disabled(ctx: TurnContext, fn):
    runtime = ctx._runtime
    previous = getattr(runtime, "on_text_chunk", None)
    try:
        runtime.on_text_chunk = None
        return fn()
    finally:
        runtime.on_text_chunk = previous



def _read_prepare_draft_context(ctx: TurnContext, state: "DraftWorkspacePipelineState") -> dict[str, Any]:
    force_refresh = bool(
        state.goal_mode != "diagnose_only"
        or _TREE_CHANGED_BY_USER_RE.search(str(ctx.message or ""))
    )
    tool_input = {
        "tree_name": state.tree_name_hint,
        "user_message": ctx.message,
        "prefer_from_scratch": (not bool(state.content.strip())) or state.edit_mode == "intentional_rebuild",
        "goal_mode": state.goal_mode,
        "has_existing_draft": bool(state.content.strip()),
        "stored_live_node_refs": state.stored_live_node_refs,
        "stored_expected_parameter_refs": state.stored_expected_parameter_refs,
        "stored_expected_focus_regions": state.stored_expected_focus_regions,
        "force_refresh": force_refresh,
    }
    if force_refresh:
        ctx.log_event("draft_context_force_refresh_requested", {
            "reason": "mandatory_before_draft_write" if state.goal_mode != "diagnose_only" else "user_reported_tree_changed",
            "tree_name": state.tree_name_hint,
        })
    try:
        raw = ctx.execute_tool("prepare_draft_context", tool_input)
        if str(raw).startswith(("ERROR:", "BLOCKED:")):
            return {}
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return {}
        result = parsed.get("result", parsed)
        if not isinstance(result, dict):
            return {}
        prepared_tree = str(result.get("tree_name") or "").strip()
        if prepared_tree:
            state.tree_name_hint = prepared_tree
        return result
    except Exception:
        return {}


def _prepared_draft_context_prompt(prepared_context: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if not isinstance(prepared_context, dict) or not prepared_context:
        return "", {}
    prompt_context = str(prepared_context.get("prompt_context") or "").strip()
    structural_memory = prepared_context.get("structural_memory", {})
    if not isinstance(structural_memory, dict):
        structural_memory = {}
    write_requirements = prepared_context.get("write_requirements", {})
    if not isinstance(write_requirements, dict):
        write_requirements = {}
    warnings = prepared_context.get("warnings", [])
    if not isinstance(warnings, list):
        warnings = []
    text = prompt_context
    if write_requirements:
        blockers = write_requirements.get("blockers", []) if isinstance(write_requirements.get("blockers"), list) else []
        if blockers:
            text += (
                "\n- explicit_blockers: "
                + ", ".join(str(item) for item in blockers[:5] if str(item).strip())
            )
    if warnings:
        text += "\n- context_warnings: " + " | ".join(str(item) for item in warnings[:3])
    if not text:
        return "", structural_memory
    return "\n\n[Prepared Draft Context]\n" + text, structural_memory



def _tree_memory_stores(ctx: TurnContext) -> list[tuple[str, dict]]:
    stores: list[tuple[str, dict]] = []
    runtime_state = getattr(ctx._runtime, "_session_state", {}) or {}
    runtime_store = runtime_state.get("tree_structural_memory") if isinstance(runtime_state, dict) else {}
    if isinstance(runtime_store, dict):
        stores.append(("runtime_state", runtime_store))
    op = getattr(ctx.session, "operational_state", None)
    op_store = getattr(op, "tree_structural_memory", {}) if op is not None else {}
    if isinstance(op_store, dict):
        stores.append(("session_operational_state", op_store))
    return stores


def _fresh_tree_structural_memory(ctx: TurnContext, tree_name: str) -> tuple[dict, str]:
    if not tree_name:
        return {}, ""
    runtime_state = getattr(ctx._runtime, "_session_state", {}) or {}
    if isinstance(runtime_state, dict) and bool(runtime_state.get("simulate_bridge_failure", False)):
        return {}, ""
    for source, store in _tree_memory_stores(ctx):
        entry = store.get(tree_name) if isinstance(store, dict) else None
        if not isinstance(entry, dict):
            continue
        if bool(entry.get("stale", False)):
            continue
        if int(entry.get("node_count", entry.get("total_nodes", 0)) or 0) <= 0:
            continue
        return dict(entry), source
    return {}, ""


def _compact_structural_memory(memory: dict, *, max_chars: int = 1400) -> str:
    if not isinstance(memory, dict) or not memory:
        return ""
    payload = {
        "tree_name": memory.get("tree_name", ""),
        "node_count": memory.get("node_count", memory.get("total_nodes", 0)),
        "frame_count": memory.get("frame_count", 0),
        "group_count": memory.get("group_count", 0),
        "phase_dominant": memory.get("phase_dominant", ""),
        "major_regions": memory.get("major_regions", memory.get("frames", []))[:8]
        if isinstance(memory.get("major_regions", memory.get("frames", [])), list) else [],
        "parameters": memory.get("parameters", {}),
        "node_groups": memory.get("node_groups", [])[:10] if isinstance(memory.get("node_groups", []), list) else [],
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return text[:max_chars]


def _prepare_structural_memory(
    ctx: TurnContext,
    tree_name: str,
    *,
    recover_missing: bool = True,
    force_refresh: bool = False,
) -> tuple[str, dict]:
    """Helper to fetch or recover structural memory and format it for prompt."""
    if not tree_name:
        return "", {}
    
    memory, source = ({}, "") if force_refresh else _fresh_tree_structural_memory(ctx, tree_name)
    
    if memory:
        ctx.log_event("tree_structural_memory_used", {
            "tree_name": tree_name,
            "node_count": memory.get("node_count", memory.get("total_nodes", 0)),
            "source": source,
            "turn_class": "draft_workspace"
        })

    if (not memory and recover_missing) or force_refresh:
        ctx.log_event("structural_memory_missing", {
            "turn_class": "draft_workspace",
            "tree_name": tree_name,
            "reason": "forced_refresh_before_write" if force_refresh else "fresh_memory_missing",
        })
        try:
            raw = ctx.execute_tool(
                "build_tree_structural_memory",
                {"tree_name": tree_name, "force_refresh": bool(force_refresh)},
            )
            raw_text = str(raw or "")
            if raw_text.startswith(("ERROR:", "BLOCKED:")):
                ctx.log_event("structural_memory_recovery_failed", {
                    "tree_name": tree_name,
                    "reason": raw_text[:300],
                })
            else:
                parsed = json.loads(raw_text)
                result = parsed.get("result", parsed) if isinstance(parsed, dict) else {}
                memory = result.get("memory", result) if isinstance(result, dict) else {}
                if not isinstance(memory, dict):
                    memory = {}
                if int(memory.get("node_count", memory.get("total_nodes", 0)) or 0) > 0:
                    source = "bounded_recovery_read"
                    ctx.log_event("tree_structural_memory_used", {
                        "tree_name": tree_name,
                        "node_count": memory.get("node_count", memory.get("total_nodes", 0)),
                        "source": source,
                        "turn_class": "draft_workspace",
                        "reason": "forced_refresh_before_write" if force_refresh else "recovered_missing_structural_memory",
                    })
        except Exception as _exc:
            ctx.log_event("structural_memory_recovery_failed", {
                "tree_name": tree_name,
                "reason": str(_exc)[:300],
            })
            memory = {}

    elif not memory:
        ctx.log_event("structural_memory_missing", {
            "turn_class": "draft_workspace",
            "tree_name": tree_name,
            "reason": "fresh_memory_missing_economy_retry_no_recovery",
        })

    if not memory:
        return "", {}

    compact = render_compact_tree(memory, max_chars=3000) or _compact_structural_memory(memory)
    if not compact:
        return "", {}

    return (
        "\n\n[Structural Memory]\n"
        "Fresh tree_structural_memory is available. Use exact node names from this block "
        "before doing focal reads:\n"
        f"{compact}"
    ), memory





def _tree_render_block(memory: dict[str, Any]) -> str:
    rendered = render_compact_tree(memory, max_chars=3000)
    if not rendered:
        return ""
    return (
        "\n\n[Tree Context Render]\n"
        "Exact node names, frame labels, parameters, and key wiring available this turn:\n"
        f"{rendered}"
    )


def _tree_render_observability(memory: dict[str, Any], rendered_block: str) -> dict[str, Any]:
    marker = memory.get("marker") if isinstance(memory.get("marker"), dict) else {}
    regions = memory.get("major_regions") if isinstance(memory.get("major_regions"), list) else []
    return {
        "tree_name": str(memory.get("tree_name") or ""),
        "node_count": int(memory.get("node_count", 0) or 0),
        "frame_count": int(memory.get("frame_count", 0) or 0),
        "marker_node_names_count": len(marker.get("node_names", [])) if isinstance(marker.get("node_names"), list) else 0,
        "marker_links_count": len(marker.get("links", [])) if isinstance(marker.get("links"), list) else 0,
        "major_regions_count": len(regions),
        "render_chars": len(rendered_block),
        "contains_tree_snapshot_render": "[Tree Snapshot Render]" in rendered_block,
    }


def _refresh_baseline_from_structural_memory(ctx: TurnContext, memory: dict[str, Any]) -> None:
    summary = compact_tree_summary_for_baseline(memory)
    if not summary or int(summary.get("node_count", 0) or 0) <= 0:
        ctx.log_event("baseline_rebuild_skipped_empty", {
            "reason": "empty_or_zero_node_structural_memory",
            "tree_name": str((memory or {}).get("tree_name") or ""),
        })
        return
    baseline = getattr(ctx.session, "baseline_workspace", None)
    if baseline is None:
        return
    try:
        builder = BaselineBuilder(baseline)
        builder.rebuild_from_summary(
            summary,
            built_from="auto",
            known_parameters=summary.get("parameters") if isinstance(summary.get("parameters"), dict) else None,
        )
        ctx.log_event("baseline_workspace_rebuilt", {
            "tree_name": str(summary.get("tree_name") or ""),
            "node_count": int(summary.get("node_count", 0) or 0),
            "tree_signature": str(getattr(baseline, "tree_signature", "") or ""),
            "source": "draft_workspace_structural_memory",
        })
    except Exception as exc:
        ctx.log_event("baseline_rebuild_failed", {
            "tree_name": str(summary.get("tree_name") or ""),
            "error": str(exc)[:200],
        })



def _handle_missing_retry_draft_source(ctx: TurnContext, state: DraftWorkspacePipelineState) -> HandlerResult | None:
    if not state.economy_retry or state.content.strip():
        return None
    if state.goal_mode == "functional_expansion":
        return None
    error_text = str((state.draft_payload or {}).get("error") or "")
    if "not found" not in error_text.lower():
        return None
    state.es.pending_draft_action = "write_confirmed_draft_revision"
    state.es.pending_draft_prompt = (
        "The retry requested a draft rewrite, but GN_Agent_Draft is missing from the Blender Text Editor.\n"
        "Do not generate code in chat. Ask for the draft block to be restored or for an explicit from-scratch draft request."
    )
    state.es.draft_edit_mode = state.edit_mode
    response = (
        "Nao encontrei o bloco **GN_Agent_Draft** no Text Editor desta cena, entao eu nao tenho uma fonte de verdade para revisar sem gastar tokens "
        "inventando tudo de novo. Posso seguir de dois jeitos: restaurando/criando esse bloco primeiro, ou voce pedindo explicitamente um draft novo do zero."
    )
    _replace_last_assistant_message(ctx._runtime, response)
    return HandlerResult(
        response_text=response,
        phase_transition="drafting",
        session_mutations=[{"type": "script_draft_missing_source_block"}],
    )


def _build_draft_workspace_system(
    ctx: TurnContext,
    state: DraftWorkspacePipelineState,
) -> tuple[str, dict, dict]:
    knowledge = ctx.retrieve_knowledge(budget_tokens=0 if state.economy_retry else 120)
    system = build_system_prompt(ctx.session, "draft_workspace", knowledge=knowledge)
    system += (
        "\n\n[DRAFT WORKSPACE]\n"
        "You are in the unified draft workspace. Read the current draft, inspect the minimum necessary context, "
        "and update the draft using `write_script_draft` when the turn asks for a write. "
        "Never put Python code, imports, code fences, or raw scripts in the assistant chat message. "
        "All draft code must be saved through `write_script_draft`; chat text is only for diagnosis, status, and saved revision summaries. "
        "If writing is blocked, report the blocker in one sentence."
    )
    system += (
        "\n\n[GN Script Conventions - MANDATORY]\n"
        "For Geometry Nodes modifier inputs, use socket identifiers such as `Input_29`, not display names. "
        "For sockets inside nodes, use `socket.name`. Preserve known live anchors and target tree unless the user explicitly asks to retarget."
    )
    system += "\n\n[Draft Goal Mode]\n" f"Current goal mode: `{state.goal_mode}`.\n"
    if state.goal_mode == "diagnose_only":
        system += (
            "This turn is diagnosis-first. Do not call `write_script_draft` unless the user explicitly confirms a pending write proposal. "
            "Answer with evidence and the smallest next correction strategy.\n"
        )
    elif state.goal_mode == "focal_correction":
        system += (
            "This turn is a focal correction of the living draft. You MUST call `write_script_draft` unless there is a critical blocker.\n"
        )
    else:
        system += (
            "This turn is a functional expansion of the living draft. You MUST call `write_script_draft` unless there is a critical blocker.\n"
        )
    system += "\n\n[Draft Edit Mode]\n" f"Current mode: `{state.edit_mode}`.\n"
    system += _pending_action_instruction(state.es, ctx.session, ctx.message)
    if state.economy_retry:
        system += (
            "\n\n[Economy retry mode]\n"
            "You MUST call `write_script_draft` before this turn ends. If needed, call `build_tree_structural_memory` once first. "
            "Avoid broad reads; read the current draft if needed, then write."
        )
        ctx.log_event("draft_workspace_economy_retry_mode", {
            "block_name": state.block_name,
            "has_pending_action": bool(str(getattr(state.es, "pending_draft_action", "") or "").strip()),
            "retry_requires_draft_change": bool(getattr(state.es, "retry_requires_draft_change", False)),
        })
    last_goal = str(state.runtime_memory.get("last_goal") or "").strip()
    last_hypothesis = str(state.runtime_memory.get("last_hypothesis") or "").strip()
    if last_goal or last_hypothesis or state.relevant_nodes:
        system += "\n\n[Session Memory (Broad Context)]"
        if last_goal:
            system += f"\n- Current User Goal: {last_goal}"
        if last_hypothesis:
            system += f"\n- Working Hypothesis: {last_hypothesis}"
        if state.relevant_nodes:
            system += f"\n- Relevant Nodes in Focus: {', '.join(str(n) for n in state.relevant_nodes[:8])}"
        ctx.log_event("session_memory_used", {
            "source": "draft_workspace",
            "used": True,
            "has_goal": bool(last_goal),
            "has_hypothesis": bool(last_hypothesis),
            "relevant_nodes_count": len(state.relevant_nodes),
        })
    if state.content.strip():
        system += (
            f"\n\nCurrent draft in '{state.block_name}' "
            f"(version {state.info.get('version', '?')}, {state.info.get('line_count', '?')} lines):\n"
            "```python\n"
            f"{state.content[:5000]}\n"
            "```"
        )
        source_note = _draft_source_note(state.info)
        if source_note:
            system += "\n\n" + source_note
        if state.stored_expected_parameter_refs or state.stored_expected_focus_regions or state.stored_live_node_refs:
            system += "\n\n[Persisted Draft Coverage]"
            if state.stored_live_node_refs:
                system += "\n- Live anchors already referenced: " + ", ".join(state.stored_live_node_refs[:8])
            if state.stored_expected_parameter_refs:
                system += "\n- Parameter semantics already covered: " + ", ".join(state.stored_expected_parameter_refs[:8])
            if state.stored_expected_focus_regions:
                system += "\n- Focus regions already covered: " + ", ".join(state.stored_expected_focus_regions[:8])
    outcome = str(getattr(state.es, "last_execution_outcome", "") or "")
    notes = str(getattr(state.es, "last_execution_notes", "") or "")
    if outcome or notes:
        system += (
            "\n\nLast execution feedback:\n"
            f"- outcome: {outcome or 'unknown'}\n"
            f"- notes: {notes[:400] or '(none)'}\n"
            f"- scene_reverted_by_user: {bool(getattr(state.es, 'scene_reverted_by_user', False))}\n"
            f"- retry_requires_draft_change: {bool(getattr(state.es, 'retry_requires_draft_change', False))}"
        )
    approved_label = str(getattr(state.es, "approved_strategy_label", "") or "").strip()
    approved_prompt = str(getattr(state.es, "approved_strategy_prompt", "") or "").strip()
    if approved_label or approved_prompt:
        system += (
            "\n\nApproved post-failure strategy:\n"
            f"- strategy_label: {approved_label or 'unspecified'}\n"
            f"- user_approval: {approved_prompt[:500] or '(none)'}\n"
            "- Write the next full draft according to this approved strategy."
        )
    prepared_context = _read_prepare_draft_context(ctx, state)
    prepared_text, structural_memory = _prepared_draft_context_prompt(prepared_context)
    attempted_forced_structural_refresh = False
    if prepared_text:
        system += prepared_text
    else:
        force_structural_refresh = state.goal_mode != "diagnose_only"
        attempted_forced_structural_refresh = bool(force_structural_refresh)
        mem_text, structural_memory = _prepare_structural_memory(
            ctx,
            state.tree_name_hint,
            recover_missing=True,
            force_refresh=force_structural_refresh,
        )
        system += mem_text
    if (
        not structural_memory
        and state.goal_mode != "diagnose_only"
        and not attempted_forced_structural_refresh
    ):
        mem_text, structural_memory = _prepare_structural_memory(
            ctx,
            state.tree_name_hint,
            recover_missing=True,
            force_refresh=True,
        )
        system += mem_text
    if structural_memory:
        tree_render = _tree_render_block(structural_memory)
        if tree_render:
            system += tree_render
            ctx.log_event(
                "tree_prompt_render_injected",
                _tree_render_observability(structural_memory, tree_render),
            )
        _refresh_baseline_from_structural_memory(ctx, structural_memory)
    coverage_status = _draft_coverage_refresh_status(
        prepared_context=prepared_context,
        structural_memory=structural_memory,
        stored_expected_parameter_refs=state.stored_expected_parameter_refs,
        stored_expected_focus_regions=state.stored_expected_focus_regions,
        stored_live_node_refs=state.stored_live_node_refs,
    )
    if coverage_status.get("coverage_refresh_needed"):
        system += (
            "\n\n[Coverage Refresh Hint]\n"
            "The living draft metadata remembers important coverage, but this turn has not reconfirmed it with fresh context yet. "
            "If more evidence is needed, spend at most one focal read on the missing area, then continue editing the same draft."
        )
    return system, structural_memory, prepared_context


def _run_draft_workspace_agent_loop(
    ctx: TurnContext,
    *,
    system: str,
    economy_retry: bool,
    tool_policy: dict[str, Any],
) -> str:
    messages = ctx.build_messages()
    previous_policy = getattr(ctx._runtime, "_draft_tool_policy", {}) if ctx._runtime is not None else {}
    if ctx._runtime is not None:
        ctx._runtime._draft_tool_policy = tool_policy
    try:
        return _with_draft_streaming_disabled(
            ctx,
            lambda: ctx.call_agent_loop(
                system,
                messages,
                excluded_tools=frozenset({"execute_code", "make_plan"}),
                max_rounds=5,
            ),
        )
    finally:
        if ctx._runtime is not None:
            ctx._runtime._draft_tool_policy = previous_policy if isinstance(previous_policy, dict) else {}


def _finalize_draft_workspace_attempt(
    ctx: TurnContext,
    state: DraftWorkspacePipelineState,
    *,
    text: str,
    structural_memory: dict[str, Any],
    tool_policy: dict[str, Any],
) -> HandlerResult:
    made_draft = False
    draft_desc = "Draft atualizado"
    block_name = state.block_name

    write_input, write_payload = _last_successful_write(ctx._runtime)
    if write_input:
        made_draft = True
        draft_desc = str(
            write_payload.get("description")
            or write_input.get("description")
            or getattr(state.draft, "description", "")
            or "Draft atualizado"
        )
        block_name = str(write_payload.get("block_name") or write_input.get("block_name") or block_name)

    loop_blocker = _runtime_loop_blocker(ctx._runtime)
    if not made_draft and loop_blocker and state.goal_mode != "diagnose_only":
        state.es.pending_draft_action = "write_confirmed_draft_revision"
        state.es.pending_draft_prompt = (
            "The previous draft attempt stopped before a safe complete revision was saved.\n"
            f"User request:\n{str(ctx.message or '')[:500]}\n\n"
            f"Reason:\n{loop_blocker}"
        )
        state.es.draft_edit_mode = state.edit_mode
        _log_draft_workspace_outcome(
            ctx,
            state=state,
            tool_policy=tool_policy,
            outcome="interrupted",
            reason=loop_blocker,
        )
        _replace_last_assistant_message(ctx._runtime, loop_blocker)
        return HandlerResult(
            response_text=loop_blocker,
            phase_transition="drafting",
            session_mutations=[{"type": "script_draft_generation_interrupted"}],
        )
    elif not made_draft and loop_blocker:
        ctx.log_event("diagnose_only_round_limit_converted_to_analysis", {
            "reason": loop_blocker[:300],
            "block_name": block_name,
        })

    extracted_code = extract_code_fences(text)
    raw_code = _raw_python_draft_candidate(text)
    leaked_candidate = extracted_code.strip() or raw_code.strip()
    if not made_draft and leaked_candidate:
        safe_code, reject_reason = _validate_agent_loop_code_fence(leaked_candidate, state.content)
        if safe_code:
            try:
                raw_write = ctx.execute_tool(
                    "write_script_draft",
                    {
                        "block_name": block_name,
                        "code": leaked_candidate,
                        "description": "Draft atualizado a partir de resposta de codigo no chat.",
                        "tree_name": state.tree_name_hint,
                        "allow_capability_regression": state.edit_mode == "intentional_rebuild",
                    },
                )
                try:
                    parsed_write = json.loads(raw_write)
                except Exception:
                    parsed_write = {}
                if isinstance(parsed_write, dict) and str(parsed_write.get("status") or "") == "success":
                    made_draft = True
                    draft_desc = "Draft atualizado a partir de resposta de codigo no chat."
            except Exception:
                pass
        else:
            ctx.log_event("script_draft_code_leak_blocked", {
                "block_name": block_name,
                "reason": reject_reason,
                "candidate_chars": len(leaked_candidate),
                "candidate_lines": _line_count(leaked_candidate),
            })

    if made_draft:
        new_info = _read_draft_info(ctx, block_name)
        new_draft_obj = _sync_draft_metadata_from_read(ctx, block_name, new_info)
        if not new_draft_obj or int(getattr(new_draft_obj, "last_written_chars", 0) or 0) <= 0:
            ctx.log_event("script_draft_write_inconsistent", {
                "block_name": block_name,
                "reason": "write_marked_success_but_read_empty",
            })
        else:
            state.es.pending_draft_action = ""
            state.es.pending_draft_prompt = ""
            state.es.retry_requires_draft_change = False
            state.es.scene_reverted_by_user = False
            state.es.draft_edit_mode = "preserve_and_refine"
            state.es.post_failure_state = ""
            state.es.proposed_strategy_count = 0
            state.es.proposed_strategy_revision = 0
            state.es.approved_strategy_label = ""
            state.es.approved_strategy_prompt = ""
            state.es.pending_user_decision = None
            response_text = _draft_summary(
                action="Draft atual atualizado",
                block_name=block_name,
                revision=getattr(new_draft_obj, "version", 0) if new_draft_obj else 0,
                char_count=getattr(new_draft_obj, "last_written_chars", 0) if new_draft_obj else 0,
                description=draft_desc,
            )
            _log_draft_workspace_outcome(
                ctx,
                state=state,
                tool_policy=tool_policy,
                outcome="written",
            )
            _replace_last_assistant_message(ctx._runtime, response_text)
            return HandlerResult(
                response_text=response_text,
                phase_transition="drafting",
                session_mutations=[{"type": "script_draft_refined"}],
            )

    failed_write_input, failed_write_result, failed_write_payload = _last_failed_write(ctx._runtime)
    if failed_write_input and state.goal_mode != "diagnose_only":
        diagnostics = _failed_write_diagnostics(failed_write_result, failed_write_payload)
        reject_reason = str(diagnostics.get("reject_reason") or "")
        semantic_regression = reject_reason.startswith((
            "regression_lost_live_node_refs",
            "regression_replaced_live_node_refs",
            "regression_lost_expected_parameters",
            "regression_replaced_expected_parameters",
            "regression_lost_focus_regions",
            "regression_replaced_focus_regions",
            "target_tree_changed:",
            "regression_candidate_too_small_vs_existing:",
        ))
        retry_guidance = _semantic_regression_retry_guidance(diagnostics) if semantic_regression else ""
        state.es.pending_draft_action = "write_confirmed_draft_revision"
        state.es.pending_draft_prompt = (
            (
                retry_guidance + "\n\n"
                if retry_guidance
                else "Previous write_script_draft failed; retry should generate one complete corrected script and save it in the Text Editor.\n"
            )
            + (
                "Treat this as a living-draft preservation fix: evolve the current script instead of replacing its anchors/capabilities.\n"
                if semantic_regression else ""
            )
            +
            f"User request:\n{str(ctx.message or '')[:500]}\n\n"
            f"Technical blocker:\n{str(diagnostics.get('error_text') or failed_write_result or '')[:800]}"
        )
        state.es.retry_requires_draft_change = True
        state.es.draft_edit_mode = state.edit_mode
        if semantic_regression:
            response = (
                "Tentei salvar o draft, mas a escrita foi bloqueada porque a nova versao regrediu capacidades que o `GN_Agent_Draft` atual ja tinha. "
                "Eu nao sobrescrevi o script vivo. Mantive a correcao como acao pendente e, no proximo retry, vou orientar a revisao a preservar "
                "a mesma arvore alvo e os anchors vivos que ja estavam funcionando."
            )
        else:
            response = (
                "Tentei salvar o draft, mas a escrita foi bloqueada porque o candidato nao era uma revisao completa valida. "
                "O `GN_Agent_Draft` nao foi sobrescrito. Mantive essa correcao como acao pendente; se voce pedir para tentar de novo, "
                "vou usar modo economico e escrever uma revisao completa sem ficar investigando a arvore de novo."
            )
        if diagnostics.get("error_text") or failed_write_result:
            response += "\n\nMotivo tecnico: " + str(diagnostics.get("error_text") or failed_write_result)[:500]
        _log_draft_workspace_outcome(
            ctx,
            state=state,
            tool_policy=tool_policy,
            outcome="write_blocked",
            reason=str(diagnostics.get("error_text") or failed_write_result or reject_reason)[:500],
        )
        _replace_last_assistant_message(ctx._runtime, response)
        return HandlerResult(
            response_text=response,
            phase_transition="drafting",
            session_mutations=[{"type": "script_draft_write_blocked"}],
        )

    response = _finalize_round_limit_text(_sanitize_draft_chat_response(text) or "Terminei a anÃ¡lise no workspace.")
    if (
        state.goal_mode == "diagnose_only"
        and not _analysis_is_useful(response)
        and state.content.strip()
    ):
        outcome = str(getattr(state.es, "last_execution_outcome", "") or "")
        notes = str(getattr(state.es, "last_execution_notes", "") or "")
        version = int(state.info.get("version") or getattr(state.draft_obj, "version", 0) or 0)
        response = _minimum_useful_analysis_response(
            block_name=block_name,
            revision=version,
            content=state.content,
            outcome=outcome,
            notes=notes,
            structural_memory=structural_memory,
        )
    elif not made_draft:
        reason_key, fallback_response = _draft_no_write_reason(
            state,
            tool_policy=tool_policy,
            runtime=ctx._runtime,
        )
        response = fallback_response
    reason = ""
    if not made_draft:
        reason_key, _ = _draft_no_write_reason(
            state,
            tool_policy=tool_policy,
            runtime=ctx._runtime,
        )
        reason = reason_key
    _log_draft_workspace_outcome(
        ctx,
        state=state,
        tool_policy=tool_policy,
        outcome="analyzed_only" if not made_draft else "written",
        reason=reason,
    )
    _store_pending_action_from_response(state.es, ctx.message, response)
    _replace_last_assistant_message(ctx._runtime, response)
    return HandlerResult(
        response_text=response,
        phase_transition="drafting",
        session_mutations=[{"type": "script_draft_workspace_analyzed"}],
    )


def _classify_execution_feedback(message: str) -> tuple[str, bool]:
    msg = (message or "").lower()
    reverted = bool(re.search(r"\b(desfiz|undo|ctrl\s*\+?\s*z|control\s*\+?\s*z|voltei\s+atr[aÃ¡]s|reverti|revertido|reverted)\b", msg))
    if reverted:
        return "reverted_by_user", True
    if re.search(r"\b(nada\s+aconteceu|sem\s+efeito|no\s+effect)\b", msg):
        return "executed_no_effect", False
    if re.search(r"\b(nenhum|nenhuma|none)\b.*\b(slider|sliders|controle|controles)\b.*\b(funcion|mex|move|alter|respond)", msg):
        return "executed_no_effect", False
    if re.search(r"\b(slider|sliders|controle|controles)\b.*\b(nao|n[aã]o)\b.*\b(funcion|mex|move|alter|respond)", msg):
        return "executed_no_effect", False
    if re.search(r"\b(nao|n[aã]o)\b.*\b(slider|sliders|controle|controles)\b.*\b(funcion|mex|move|alter|respond)", msg):
        return "executed_no_effect", False
    if re.search(r"\b(deu\s+errado|(nao|n[aã]o)\s+deu\s+certo|n[aÃ£]o\s+funcionou|falhou|erro|failed|wrong|sumiu|sumiram|sumindo|desapareceu|desapareceram|apagou)\b", msg):
        return "executed_failed", False
    if re.search(r"\b(parcial|partial|metade|incomplet[oa])\b", msg):
        return "executed_partial_failure", False
    return "executed", False


def handle_draft_workspace(ctx: TurnContext) -> HandlerResult:
    """Unified user-facing copilot entry point for active draft work.
    
    Flow:
    1. Read current draft content.
    2. Sync metadata from the read text block.
    3. Recover structural memory if target tree is known.
    4. Call the agent loop explicitly allowing both read and write tools.
    """
    state = _load_draft_workspace_state(ctx)
    missing_source = _handle_missing_retry_draft_source(ctx, state)
    if missing_source is not None:
        return missing_source
    system, structural_memory, prepared_context = _build_draft_workspace_system(ctx, state)
    tool_policy = _draft_workspace_tool_policy(
        tree_name_hint=state.tree_name_hint,
        structural_memory=structural_memory,
        relevant_nodes=state.relevant_nodes,
        economy_retry=state.economy_retry,
        has_existing_draft_content=bool(state.content.strip()),
        prepared_context=prepared_context,
        edit_mode=state.edit_mode,
        goal_mode=state.goal_mode,
        stored_goal_guidance=state.goal_guidance,
        stored_expected_parameter_refs=state.stored_expected_parameter_refs,
        stored_expected_focus_regions=state.stored_expected_focus_regions,
        stored_live_node_refs=state.stored_live_node_refs,
    )
    text = _run_draft_workspace_agent_loop(
        ctx,
        system=system,
        economy_retry=state.economy_retry,
        tool_policy=tool_policy,
    )
    return _finalize_draft_workspace_attempt(
        ctx,
        state,
        text=text,
        structural_memory=structural_memory,
        tool_policy=tool_policy,
    )


def handle_execution_feedback(ctx: TurnContext) -> HandlerResult:
    """Compatibility wrapper for the post-execution feedback module."""
    from .feedback import handle

    return handle(ctx)


def handle_state_control(ctx: TurnContext) -> HandlerResult:
    """Handle lightweight draft-first control messages.

    There is no approval denial path anymore. A cancel/stop style message only
    closes the current draft workflow in session state; it never clears or
    executes the Text Editor draft itself.
    """
    es = ctx.session.execution_state
    block_name = str(getattr(es, "draft_block_name", "") or "GN_Agent_Draft")
    es.current_draft = None
    es.retry_requires_draft_change = False
    es.scene_reverted_by_user = False
    es.post_failure_state = ""
    es.proposed_strategy_count = 0
    es.proposed_strategy_revision = 0
    es.approved_strategy_label = ""
    es.approved_strategy_prompt = ""
    try:
        es.set_phase("idle")
    except Exception:
        pass
    response = (
        f"Ok, parei o fluxo de draft por aqui. O texto **{block_name}** continua no Text Editor; "
        "nÃ£o executei nada."
    )
    _replace_last_assistant_message(ctx._runtime, response)
    return HandlerResult(
        response_text=response,
        phase_transition="idle",
        session_mutations=[{"type": "draft_state_control", "action": "stopped"}],
    )






