"""Handlers for the unified draft workspace flow."""

from __future__ import annotations

import json
import re
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
from .draft_prompt import _build_draft_workspace_system
from .draft_context import _read_prepare_draft_context
from .draft_runtime import _replace_last_assistant_message, _with_draft_streaming_disabled
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
from .feedback_classifier import _classify_execution_feedback

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
_VALID_DRAFT_GOAL_MODES = {"diagnose_only", "focal_correction", "functional_expansion", "feedback_fix"}

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
                max_rounds=8,
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

    extracted_code = extract_code_fences(text)
    raw_code = _raw_python_draft_candidate(text)
    leaked_candidate = extracted_code.strip() or raw_code.strip()
    response_was_truncated = bool(getattr(ctx._runtime, "_last_agent_loop_truncated", False))
    if not made_draft and leaked_candidate and not response_was_truncated:
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
    if state.goal_mode == "diagnose_only":
        outcome = str(getattr(state.es, "last_execution_outcome", "") or "")
        notes = str(getattr(state.es, "last_execution_notes", "") or "")
        version = int(state.info.get("version") or getattr(state.draft_obj, "version", 0) or 0)
        generic_no_save = bool(re.search(r"\bn[aã]o\s+salvei\s+o\s+draft\b", response, re.IGNORECASE))
        if generic_no_save or not _analysis_is_useful(response):
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






