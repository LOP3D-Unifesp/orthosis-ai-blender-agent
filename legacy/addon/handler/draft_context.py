"""Draft workspace context and structural-memory helpers."""

from __future__ import annotations

import json
import re
from typing import Any

from . import TurnContext
from ..runtime.tree_renderer import compact_tree_summary_for_baseline, render_compact_tree
from ..session.baseline import BaselineBuilder


_TREE_CHANGED_BY_USER_RE = re.compile(
    r"\b("
    r"mudei|mudou|alterei|alterou|editei|mexi|modifiquei|"
    r"voltei|reverti|desfiz|undo|ctrl\s*\+?\s*z|restaurei|resetei|"
    r"arvor[ea]\s+(mudou|alterada|diferente|revertida|voltou)"
    r")\b",
    re.IGNORECASE,
)


def _read_prepare_draft_context(ctx: TurnContext, state: Any) -> dict[str, Any]:
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
    """Fetch or recover structural memory and format it for the draft prompt."""
    if not tree_name:
        return "", {}

    memory, source = ({}, "") if force_refresh else _fresh_tree_structural_memory(ctx, tree_name)

    if memory:
        ctx.log_event("tree_structural_memory_used", {
            "tree_name": tree_name,
            "node_count": memory.get("node_count", memory.get("total_nodes", 0)),
            "source": source,
            "turn_class": "draft_workspace",
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
        except Exception as exc:
            ctx.log_event("structural_memory_recovery_failed", {
                "tree_name": tree_name,
                "reason": str(exc)[:300],
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

    compact = render_compact_tree(memory, max_chars=7000) or _compact_structural_memory(memory)
    if not compact:
        return "", {}

    return (
        "\n\n[Structural Memory]\n"
        "Fresh tree_structural_memory is available. Use exact node names from this block "
        "before doing focal reads:\n"
        f"{compact}"
    ), memory


def _tree_render_block(memory: dict[str, Any]) -> str:
    rendered = render_compact_tree(memory, max_chars=7000)
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
            "reason": str(exc)[:300],
            "tree_name": str(summary.get("tree_name") or ""),
        })
