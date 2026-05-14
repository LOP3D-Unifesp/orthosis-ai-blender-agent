"""System prompt builder for draft workspace turns."""

from __future__ import annotations

from . import TurnContext
from .draft_context import (
    _prepared_draft_context_prompt,
    _prepare_structural_memory,
    _read_prepare_draft_context,
    _refresh_baseline_from_structural_memory,
    _tree_render_block,
    _tree_render_observability,
)
from .draft_policy import _draft_coverage_refresh_status
from .draft_response import _draft_source_note
from .draft_state import DraftWorkspacePipelineState, _pending_action_instruction
from .prompt import build_system_prompt


def _build_draft_workspace_system(
    ctx: TurnContext,
    state: DraftWorkspacePipelineState,
) -> tuple[str, dict, dict]:
    knowledge = ctx.retrieve_knowledge(budget_tokens=0 if state.economy_retry else 120)
    system = build_system_prompt(ctx.session, "draft_workspace", knowledge=knowledge)
    system += (
        "\n\n[DRAFT WORKSPACE]\n"
        "You are in the unified draft workspace. Read the current draft, inspect the necessary context, "
        "and update the draft using `write_script_draft` when the turn asks for a write. "
        "Never put Python code, imports, code fences, or raw scripts in the assistant chat message. "
        "All draft code must be saved through `write_script_draft`; chat text is only for diagnosis, status, and saved revision summaries. "
        "If writing is blocked, report the blocker in one sentence.\n"
        "IMPORTANT: Never ask the user to confirm node names, socket identifiers, connections, or parameters. "
        "If the structural memory in this context does not answer your question, call a read tool directly — "
        "`get_node_context`, `find_tree_nodes`, or `build_tree_structural_memory`."
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
            "- Write the next full draft according to this approved strategy.\n"
            "- IMPORTANT: pass `allow_capability_regression: true` in the write_script_draft call "
            "because this is an explicitly approved rewrite — the regression safety check must not block it."
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
