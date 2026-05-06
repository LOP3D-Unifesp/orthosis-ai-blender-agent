"""Operational state synchronization after tool execution."""

from __future__ import annotations

import time
from typing import Any

from .runtime_planning import MUTATION_TOOLS
from .runtime import state_ops


def update_operational_state_from_tool(
    runtime: Any,
    *,
    tool_name: str,
    tool_input: dict[str, Any],
    runtime_raw: dict[str, Any],
) -> None:
    if str(runtime_raw.get("status", "success")) != "success":
        return
    result = runtime_raw.get("result", {})
    if not isinstance(result, dict):
        result = {}
    tree_name = runtime._extract_tree_name(tool_input) or str(result.get("tree_name", "")).strip()
    node_name = runtime._extract_node_name(tool_input)
    updates: dict[str, Any] = {
        "target_tree": tree_name or runtime._session_memory.get("target_tree", ""),
    }
    if node_name:
        updates["relevant_nodes"] = [node_name]
    if tool_name in MUTATION_TOOLS:
        updates["decisions"] = [f"mutation:{tool_name}"]

    if tool_name == "get_selected_nodes_context":
        selected_nodes = []
        for node in result.get("nodes", []):
            if not isinstance(node, dict):
                continue
            if node.get("is_selected"):
                selected_nodes.append(str(node.get("name", "")).strip())
        runtime._local_scope = {
            "scope_type": "selected_nodes",
            "tree_name": tree_name,
            "node_names": [n for n in selected_nodes if n],
            "updated_at": int(time.time()),
        }
        updates["relevant_nodes"] = runtime._local_scope.get("node_names", [])
        runtime.journal.log_runtime_event(
            event_type="local_scope_used",
            payload={
                "local_scope_used": True,
                "scope_type": "selected_nodes",
                "selected_nodes_count": len(runtime._local_scope.get("node_names", [])),
            },
        )
    elif tool_name == "get_active_frame_context":
        frame_name = str(result.get("frame_name", "")).strip()
        node_names = [
            str(node.get("name", "")).strip()
            for node in result.get("nodes", [])
            if isinstance(node, dict)
        ]
        runtime._local_scope = {
            "scope_type": "active_frame",
            "tree_name": tree_name,
            "frame_name": frame_name,
            "node_names": [name for name in node_names if name],
            "updated_at": int(time.time()),
        }
        updates["active_frame"] = frame_name
        updates["relevant_nodes"] = runtime._local_scope.get("node_names", [])
        runtime.journal.log_runtime_event(
            event_type="local_scope_used",
            payload={
                "local_scope_used": True,
                "scope_type": "active_frame",
                "active_frame_name": frame_name,
            },
        )
    elif tool_name == "get_local_subgraph_context":
        node_names = [
            str(node.get("name", "")).strip()
            for node in result.get("nodes", [])
            if isinstance(node, dict)
        ]
        runtime._local_scope = {
            "scope_type": "subgraph",
            "tree_name": tree_name,
            "node_names": [name for name in node_names if name],
            "updated_at": int(time.time()),
        }
        updates["focus_subgraph"] = f"{tree_name}:{result.get('scope_mode', 'subgraph')}"
        updates["relevant_nodes"] = runtime._local_scope.get("node_names", [])
        runtime.journal.log_runtime_event(
            event_type="local_scope_used",
            payload={
                "local_scope_used": True,
                "scope_type": "subgraph",
                "selected_nodes_count": len(runtime._local_scope.get("node_names", [])),
            },
        )
    elif tool_name == "get_changes_since_last_turn":
        runtime.journal.log_runtime_event(
            event_type="changes_since_last_turn",
            payload={
                "tree_name": tree_name,
                "changes_since_last_turn_count": int(result.get("changes_count", 0) or 0),
            },
        )

    if tool_name == "get_tree_structure":
        structural_entry = runtime._build_structural_index_entry(result)
        state_ops.update_structural_index(
            runtime._session_state,
            tree_name=tree_name,
            index_entry=structural_entry,
        )
        runtime._structural_index = runtime._session_state.get("structural_index", {})
        runtime.journal.log_runtime_event(
            event_type="structural_index_updated",
            payload={
                "structural_index_updated": True,
                "tree_name": tree_name,
                "node_count": structural_entry.get("node_count", 0),
            },
        )
    if tool_name == "get_changes_since_last_turn":
        current_marker = result.get("current_marker", {}) if isinstance(result.get("current_marker"), dict) else {}
        if tree_name and current_marker and bool(tool_input.get("update_marker", True)):
            state_ops.update_tree_change_marker(
                runtime._session_state,
                tree_name=tree_name,
                marker=current_marker,
            )

    state_ops.set_local_scope(runtime._session_state, runtime._local_scope)
    runtime._session_memory = state_ops.update_session_memory(runtime._session_state, updates)
    runtime.journal.log_runtime_event(
        event_type="session_memory_updated",
        payload={
            "session_memory_updated": True,
            "target_tree": runtime._session_memory.get("target_tree", ""),
            "relevant_nodes_count": len(runtime._session_memory.get("relevant_nodes", [])),
        },
    )
