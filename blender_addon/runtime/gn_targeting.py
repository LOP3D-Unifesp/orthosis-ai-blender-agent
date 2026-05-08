"""Canonical GN tool-input normalization for one turn."""

from __future__ import annotations

from typing import Any

_CANONICAL_TREE_TOOLS = frozenset(
    {
        "build_tree_structural_memory",
        "classify_tree_phases",
        "map_clinical_parameter_roles",
        "get_node_context",
        "get_selected_nodes_context",
        "get_active_frame_context",
        "get_local_subgraph_context",
        "get_changes_since_last_turn",
        "get_tree_parameters",
        "apply_simulator_payload",
    }
)


def canonicalize_gn_tool_input(
    tool_name: str,
    tool_input: dict[str, Any] | None,
    canonical_target: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    normalized = dict(tool_input or {})
    if tool_name not in _CANONICAL_TREE_TOOLS or not isinstance(canonical_target, dict):
        return normalized, None

    canonical_tree = str(canonical_target.get("tree_name") or "").strip()
    if not canonical_tree:
        return normalized, None

    requested_tree = str(normalized.get("tree_name") or "").strip()
    if requested_tree and requested_tree != canonical_tree:
        return normalized, {
            "tool_name": tool_name,
            "requested_tree": requested_tree,
            "canonical_tree": canonical_tree,
        }

    normalized["tree_name"] = canonical_tree
    return normalized, None
