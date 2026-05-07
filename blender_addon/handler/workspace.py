"""Unified workspace handler for read/write Geometry Nodes work.

Onda 4c migrates the old split handlers incrementally.  This module is the
new dispatcher-facing surface: callers pass an explicit ``goal_mode`` and the
handler selects a goal configuration instead of inferring intent internally.
Write modes still delegate to the current draft implementation during the
transition; read-only inquiry is handled here first.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

from . import HandlerResult, TurnContext
from ..runtime_planning import is_scene_wide_gn_inspection_request
from .draft_context import (
    _refresh_baseline_from_structural_memory,
    _tree_render_block,
    _tree_render_observability,
)
from .draft_runtime import _with_draft_streaming_disabled
from .prompt import build_system_prompt


@dataclass(frozen=True)
class GoalConfig:
    name: str
    turn_class: str
    read_only: bool
    max_rounds: int
    knowledge_budget: int | None = None
    excluded_tools: frozenset[str] = frozenset()
    focal_budget_min: int = 0
    legacy_handler: str = ""


GOAL_CONFIGS: dict[str, GoalConfig] = {
    "inquiry": GoalConfig(
        name="inquiry",
        turn_class="context_inquiry",
        read_only=True,
        max_rounds=4,
        knowledge_budget=450,
        excluded_tools=frozenset({"execute_code", "make_plan", "write_script_draft"}),
    ),
    "diagnose_only": GoalConfig(
        name="diagnose_only",
        turn_class="draft_workspace",
        read_only=True,
        max_rounds=8,
        knowledge_budget=800,
        excluded_tools=frozenset({"execute_code", "make_plan", "write_script_draft"}),
    ),
    "focal_correction": GoalConfig(
        name="focal_correction",
        turn_class="draft_workspace",
        read_only=False,
        max_rounds=8,
        knowledge_budget=800,
        excluded_tools=frozenset({"execute_code", "make_plan"}),
    ),
    "functional_expansion": GoalConfig(
        name="functional_expansion",
        turn_class="draft_workspace",
        read_only=False,
        max_rounds=10,
        knowledge_budget=800,
        excluded_tools=frozenset({"execute_code", "make_plan"}),
    ),
    "feedback_fix": GoalConfig(
        name="feedback_fix",
        turn_class="draft_workspace",
        read_only=True,
        max_rounds=3,
        knowledge_budget=800,
        excluded_tools=frozenset({"execute_code", "make_plan", "write_script_draft"}),
        focal_budget_min=3,
    ),
}


def handle(ctx: TurnContext, goal_mode: str) -> HandlerResult:
    """Handle a workspace turn with an explicit goal mode."""
    config = GOAL_CONFIGS.get(str(goal_mode or "").strip()) or GOAL_CONFIGS["inquiry"]
    ctx.log_event("workspace_goal_selected", {
        "goal_mode": config.name,
        "turn_class": config.turn_class,
        "read_only": config.read_only,
        "max_rounds": config.max_rounds,
        "legacy_handler": config.legacy_handler,
    })
    if config.name == "feedback_fix":
        from . import feedback

        setattr(ctx.meta, "goal_mode", config.name)
        return feedback.handle(ctx)
    if config.name in {"diagnose_only", "focal_correction", "functional_expansion"}:
        return _handle_draft_goal(ctx, config)
    return _handle_inquiry(ctx, config)


def _handle_inquiry(ctx: TurnContext, config: GoalConfig) -> HandlerResult:
    scene_wide_inspection = is_scene_wide_gn_inspection_request(ctx.message)
    if ctx.meta.needs_baseline_refresh and not scene_wide_inspection:
        _refresh_baseline(ctx, "build_tree_structural_memory")

    discovery_brief = _maybe_run_discovery(ctx, config)
    knowledge = ctx.retrieve_knowledge(budget_tokens=config.knowledge_budget)
    system = build_system_prompt(ctx.session, config.name, knowledge=knowledge)
    if discovery_brief:
        system += "\n\n" + discovery_brief

    # Always inject the full tree render when structural memory is available.
    # Narrow factual questions and post-failure inquiry both benefit: the agent
    # sees all node names, frame membership and every link in one shot instead
    # of reconstructing the graph via repeated focal reads.
    tree_render = _full_tree_render_for_inquiry(ctx) or _maybe_tree_render_for_factual_inquiry(ctx)
    if tree_render:
        system += tree_render

    effective_max_rounds = _inquiry_max_rounds_for_state(ctx, config)

    text = ctx.call_agent_loop(
        system,
        ctx.build_messages(),
        excluded_tools=config.excluded_tools,
        max_rounds=effective_max_rounds,
    )
    return HandlerResult(response_text=text)


def _full_tree_render_for_inquiry(ctx: TurnContext) -> str:
    """Inject the complete tree render into every inquiry system prompt.

    Returns an empty string when structural memory is unavailable so the caller
    falls back to the narrower factual-inquiry render.  The render now includes
    all nodes per frame and up to 200 links, giving the agent a complete wiring
    picture without needing focal reads.
    """
    runtime = ctx._runtime
    state = getattr(runtime, "_session_state", {}) or {}
    memory_store = state.get("tree_structural_memory") if isinstance(state, dict) else {}
    if not isinstance(memory_store, dict) or not memory_store:
        op_state = getattr(getattr(ctx, "session", None), "operational_state", None)
        candidate = getattr(op_state, "tree_structural_memory", {}) if op_state is not None else {}
        memory_store = candidate if isinstance(candidate, dict) else {}

    if not memory_store:
        return ""

    # Pick the first (typically only) non-stale tree entry.
    memory: dict = {}
    for entry in memory_store.values():
        if isinstance(entry, dict) and not entry.get("stale") and int(entry.get("node_count", 0) or 0) >= 1:
            memory = entry
            break

    if not memory:
        return ""

    block = _tree_render_block(memory)
    if block:
        ctx.log_event("tree_prompt_render_injected", {
            "turn_class": "context_inquiry",
            "source": "full_tree_render_for_inquiry",
            "node_count": int(memory.get("node_count", 0) or 0),
            "render_chars": len(block),
        })
    return block


def _inquiry_max_rounds_for_state(ctx: TurnContext, config: GoalConfig) -> int:
    """Bump rounds for read-only inquiry while we are still repairing a failed draft.

    Mapping links across a 99-node tree to explain a regression does not fit in
    4 rounds; the agent ends up muting on `agent_loop_round_limit`. In REPAIRING
    or STRATEGY_PROPOSED we let inquiry use up to the diagnose_only budget so it
    can both explore and produce a final synthesis.

    Uses infer_session_state (same source as the router) to avoid reading stale
    cached fields that may not be hydrated by the time this handler runs.
    """
    base = int(config.max_rounds or 4)
    state = ""
    try:
        from ..runtime.routing_obs import infer_session_state
        state = infer_session_state(ctx.session)
    except Exception:
        state = str(getattr(getattr(getattr(ctx, "session", None), "execution_state", None), "session_state", "") or "")
    if state in {"REPAIRING", "STRATEGY_PROPOSED"}:
        effective = max(base, 7)
        ctx.log_event("inquiry_rounds_bumped", {
            "session_state": state,
            "base_rounds": base,
            "effective_rounds": effective,
        })
        return effective
    return base


def _maybe_tree_render_for_factual_inquiry(ctx: TurnContext) -> str:
    """Inject structural tree render for narrow factual tree questions.

    These questions can route through context_inquiry even while a draft is
    active. They still need the same tree snapshot marker used by draft turns,
    so the journal validation and the model both see exact node names.
    """
    signals = set(getattr(ctx.meta, "signals", []) or [])
    if not (signals & {"factual_tree_inquiry_in_drafting", "answer_correction_in_drafting"}):
        return ""

    tree_name = _target_tree_hint(ctx)
    if not tree_name:
        ctx.log_event("structural_memory_missing", {
            "turn_class": "context_inquiry",
            "tree_name": "",
            "reason": "factual_tree_inquiry_no_target_tree",
        })
        return ""

    try:
        raw = ctx.execute_tool("build_tree_structural_memory", {"tree_name": tree_name})
        raw_text = str(raw or "")
        if raw_text.startswith(("ERROR:", "BLOCKED:")):
            ctx.log_event("structural_memory_recovery_failed", {
                "tree_name": tree_name,
                "reason": raw_text[:300],
            })
            return ""
        parsed = json.loads(raw_text or "{}")
        if not isinstance(parsed, dict):
            parsed = {}
        result = parsed.get("result") if isinstance(parsed.get("result"), dict) else parsed
        memory = result.get("memory", result) if isinstance(result, dict) else {}
        if not isinstance(memory, dict) or int(memory.get("node_count", 0) or 0) <= 0:
            ctx.log_event("structural_memory_missing", {
                "turn_class": "context_inquiry",
                "tree_name": tree_name,
                "reason": "factual_tree_inquiry_empty_structural_memory",
            })
            return ""
        rendered = _tree_render_block(memory)
        if not rendered:
            return ""
        ctx.log_event(
            "tree_prompt_render_injected",
            _tree_render_observability(memory, rendered),
        )
        _refresh_baseline_from_structural_memory(ctx, memory)
        return rendered
    except Exception as exc:
        ctx.log_event("structural_memory_recovery_failed", {
            "tree_name": tree_name,
            "reason": str(exc)[:300],
        })
        return ""


def _target_tree_hint(ctx: TurnContext) -> str:
    es = getattr(getattr(ctx, "session", None), "execution_state", None)
    draft = getattr(es, "current_draft", None) if es is not None else None
    for value in (
        getattr(draft, "tree_name", "") if draft is not None else "",
        getattr(es, "draft_target_tree", "") if es is not None else "",
        getattr(getattr(ctx.session, "focus", None), "tree_name", ""),
        (getattr(ctx._runtime, "_session_memory", {}) or {}).get("target_tree", "")
        if isinstance(getattr(ctx._runtime, "_session_memory", {}), dict) else "",
    ):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _handle_draft_goal(ctx: TurnContext, config: GoalConfig) -> HandlerResult:
    """Draft workspace goal migrated from the old draft workspace path."""
    from . import _drafting_support as drafting

    setattr(ctx.meta, "goal_mode", config.name)
    state = drafting._load_draft_workspace_state(ctx)
    state.goal_mode = config.name
    missing_source = drafting._handle_missing_retry_draft_source(ctx, state)
    if missing_source is not None:
        return missing_source

    # Aquecer baseline antes de montar o system prompt. Em REPAIRING (economy_retry)
    # broad reads são bloqueados por design — não forçar refresh nesses casos.
    if ctx.meta.needs_baseline_refresh and not state.economy_retry:
        _refresh_baseline(ctx, "build_tree_structural_memory")

    system, structural_memory, prepared_context = drafting._build_draft_workspace_system(ctx, state)
    tool_policy = drafting._draft_workspace_tool_policy(
        tree_name_hint=state.tree_name_hint,
        structural_memory=structural_memory,
        relevant_nodes=state.relevant_nodes,
        economy_retry=state.economy_retry,
        has_existing_draft_content=bool(state.content.strip()),
        prepared_context=prepared_context,
        edit_mode=state.edit_mode,
        goal_mode=config.name,
        stored_goal_guidance=state.goal_guidance,
        stored_expected_parameter_refs=state.stored_expected_parameter_refs,
        stored_expected_focus_regions=state.stored_expected_focus_regions,
        stored_live_node_refs=state.stored_live_node_refs,
    )

    previous_policy = getattr(ctx._runtime, "_draft_tool_policy", {}) if ctx._runtime is not None else {}
    if ctx._runtime is not None:
        ctx._runtime._draft_tool_policy = tool_policy
    try:
        text = _with_draft_streaming_disabled(
            ctx,
            lambda: ctx.call_agent_loop(
                system,
                ctx.build_messages(),
                excluded_tools=config.excluded_tools,
                max_rounds=config.max_rounds,
            ),
        )
    finally:
        if ctx._runtime is not None:
            ctx._runtime._draft_tool_policy = previous_policy if isinstance(previous_policy, dict) else {}

    ctx.log_event("workspace_draft_goal_handled", {
        "goal_mode": config.name,
        "tree_name": state.tree_name_hint,
        "has_existing_draft_content": bool(state.content.strip()),
        "used_structural_memory": bool(structural_memory),
        "write_allowed": bool(tool_policy.get("write_allowed", False)),
        "max_rounds": config.max_rounds,
    })
    return drafting._finalize_draft_workspace_attempt(
        ctx,
        state,
        text=text,
        structural_memory=structural_memory,
        tool_policy=tool_policy,
    )


_DISCOVERY_BIG_TREE_THRESHOLD = 100
_DISCOVERY_MAX_READS = 2


def _brief_from_structural_memory(target_tree: str, memory: dict, *, reused: bool) -> str:
    frames = memory.get("major_regions") or memory.get("frames") or []
    groups = memory.get("node_groups") or memory.get("groups") or []
    parameters = memory.get("parameters") if isinstance(memory.get("parameters"), dict) else {}
    parameter_count = int(parameters.get("parameter_count", 0) or len(parameters.get("inputs", []) or []))
    source = "reused" if reused else "built"
    return (
        f"[Discovery {source}: {target_tree} | "
        f"{int(memory.get('node_count', 0) or 0)} nodes | "
        f"{int(memory.get('frame_count', 0) or len(frames))} frames | "
        f"{int(memory.get('group_count', 0) or len(groups))} node groups | "
        f"{parameter_count} parameters | "
        f"phase={memory.get('phase_dominant', 'unknown')}]"
    )


def _maybe_run_discovery(ctx: TurnContext, config: GoalConfig) -> str:
    if config.name != "inquiry":
        return ""
    if is_scene_wide_gn_inspection_request(ctx.message):
        ctx.log_event("discovery_phase_skipped", {"turn_class": config.turn_class, "reason": "scene_wide_gn_inspection"})
        return ""

    runtime = ctx._runtime
    target_tree = ""
    canonical_target = getattr(runtime, "_canonical_gn_target", None)
    if isinstance(canonical_target, dict):
        target_tree = str(canonical_target.get("tree_name") or "").strip()
    if not target_tree:
        session_memory = getattr(runtime, "_session_memory", {}) or {}
        target_tree = str(session_memory.get("target_tree") or "").strip()
    if not target_tree:
        focus = getattr(ctx.session, "focus", None)
        target_tree = str(getattr(focus, "tree_name", "") or "").strip()

    if not target_tree:
        ctx.log_event("discovery_phase_skipped", {"turn_class": config.turn_class, "reason": "no_target_tree_resolved"})
        return ""

    if bool((getattr(runtime, "_session_state", {}) or {}).get("simulate_bridge_failure", False)):
        ctx.log_event("structural_memory_recovery_failed", {
            "tree_name": target_tree,
            "reason": "Simulated bridge failure: debug flag simulate_bridge_failure is enabled.",
            "source": "discovery_freshness_gate",
        })
        return ""

    state = getattr(runtime, "_session_state", {}) or {}
    memory_store = state.get("tree_structural_memory") if isinstance(state, dict) else {}
    if not isinstance(memory_store, dict) or not memory_store:
        op_state = getattr(ctx.session, "operational_state", None)
        candidate_store = getattr(op_state, "tree_structural_memory", {}) if op_state is not None else {}
        memory_store = candidate_store if isinstance(candidate_store, dict) else {}
    memory_entry = memory_store.get(target_tree) if isinstance(memory_store, dict) else None
    memory_fresh = (
        isinstance(memory_entry, dict)
        and not bool(memory_entry.get("stale", False))
        and int(memory_entry.get("node_count", 0) or 0) >= 1
    )

    if memory_fresh:
        ctx.log_event("discovery_phase_skipped", {
            "turn_class": config.turn_class, "target_tree": target_tree,
            "reason": "fresh_tree_structural_memory", "node_count": memory_entry.get("node_count"),
        })
        ctx.log_event("tree_structural_memory_used", {
            "tree_name": target_tree, "node_count": memory_entry.get("node_count"),
            "source": "discovery_freshness_gate",
        })
        return _brief_from_structural_memory(target_tree, memory_entry, reused=True)

    t0 = time.monotonic()
    ctx.log_event("discovery_phase_start", {
        "turn_class": config.turn_class, "target_tree": target_tree,
        "reason": "stale_or_missing_tree_structural_memory",
    })

    reads_made = 0
    node_count = 0
    snapshot_truncated = False
    brief_lines: list[str] = []

    try:
        raw = ctx.execute_tool("build_tree_structural_memory", {"tree_name": target_tree})
        reads_made += 1
        if str(raw).startswith(("ERROR:", "BLOCKED:")):
            raise ValueError(str(raw)[:200])
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            result = parsed.get("result", parsed)
            if isinstance(result, dict) and isinstance(result.get("memory"), dict):
                result = result.get("memory", {})
            node_count = int(result.get("node_count") or result.get("total_nodes") or 0)
            snapshot_truncated = bool(result.get("snapshot_truncated", False))
            frames = result.get("major_regions") or result.get("frames") or []
            group_nodes = result.get("node_groups") or result.get("group_nodes") or []
            brief_lines.append(
                f"[Discovery: {target_tree} | {node_count} nós"
                + (f" | {len(frames)} frames" if frames else "")
                + (f" | {len(group_nodes)} node groups" if group_nodes else "")
                + (" | snapshot_truncated=True" if snapshot_truncated else "")
                + "]"
            )
    except Exception as _e:
        ctx.log_event("discovery_read_error", {"tool": "build_tree_structural_memory", "error": str(_e)[:200]})

    if reads_made < _DISCOVERY_MAX_READS and (snapshot_truncated or node_count > _DISCOVERY_BIG_TREE_THRESHOLD):
        try:
            raw2 = ctx.execute_tool("list_tree_nodes", {"tree_name": target_tree})
            reads_made += 1
            parsed2 = json.loads(raw2)
            if isinstance(parsed2, dict):
                result2 = parsed2.get("result", parsed2)
                full_count = int(result2.get("node_count") or 0)
                if full_count and full_count != node_count:
                    brief_lines.append(f"[Inventário completo via bpy: {full_count} nós confirmados]")
                    node_count = full_count
        except Exception as _e2:
            ctx.log_event("discovery_read_error", {"tool": "list_tree_nodes", "error": str(_e2)[:200]})

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    if not brief_lines:
        ctx.log_event("discovery_phase_done", {
            "turn_class": config.turn_class, "target_tree": target_tree,
            "reads_made": reads_made, "node_count": 0,
            "elapsed_ms": elapsed_ms, "status": "degraded",
        })
        return f"[Discovery degraded: structural memory for '{target_tree}' could not be built]"

    session_memory = getattr(runtime, "_session_memory", {}) or {}
    relevant_nodes = session_memory.get("relevant_nodes") or []
    if relevant_nodes:
        brief_lines.append(f"[Nós relevantes na memória: {', '.join(str(n) for n in relevant_nodes[:8])}]")

    ctx.log_event("discovery_phase_done", {
        "turn_class": config.turn_class, "target_tree": target_tree,
        "reads_made": reads_made, "node_count": node_count,
        "snapshot_truncated": snapshot_truncated, "elapsed_ms": elapsed_ms,
        "brief_lines": len(brief_lines),
    })
    return "\n".join(brief_lines) if brief_lines else ""


def _refresh_baseline(ctx: TurnContext, tool_name: str) -> None:
    runtime_target = getattr(ctx._runtime, "_canonical_gn_target", None)
    tree_name = ""
    if isinstance(runtime_target, dict):
        tree_name = str(runtime_target.get("tree_name") or "").strip()
    if not tree_name:
        focus = getattr(ctx.session, "focus", None)
        tree_name = getattr(focus, "tree_name", "") if focus else ""
    if not tree_name:
        return
    try:
        result = ctx.execute_tool(tool_name, {"tree_name": tree_name})
        result_text = str(result or "")
        if result_text.startswith(("ERROR:", "BLOCKED:")):
            ctx.log_event("structural_memory_recovery_failed", {
                "tree_name": tree_name, "reason": result_text[:300], "source": "baseline_refresh",
            })
            return
        baseline = getattr(ctx.session, "baseline_workspace", None)
        if baseline and result:
            try:
                parsed = json.loads(result)
                baseline.structural_summary = (
                    parsed if isinstance(parsed, dict) else {"summary": str(result)[:500]}
                )
            except (json.JSONDecodeError, ValueError, TypeError):
                baseline.structural_summary = {"summary": str(result)[:500]}
            baseline.stale = False
    except Exception as exc:
        ctx.log_event("structural_memory_recovery_failed", {
            "tree_name": tree_name, "reason": str(exc)[:300], "source": "baseline_refresh",
        })
