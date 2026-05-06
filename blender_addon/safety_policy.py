"""Centralized runtime safety policy for product and MCP routes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal


SafetyLevel = Literal["auto_apply", "confirm_then_apply", "explicit_override"]
RouteType = Literal["product", "mcp"]


AUTO_APPLY_TOOLS = {
    "make_plan",
    "get_scene_summary",
    "get_gn_hosts",
    "get_tree_focus",
    "get_tree_parameters",
    "resolve_gn_workspace",
    "build_tree_structural_memory",
    "classify_tree_phases",
    "map_clinical_parameter_roles",
    "interpret_orthosis_tree_logic",
    "get_node_context",
    "get_selected_nodes_context",
    "get_active_frame_context",
    "get_local_subgraph_context",
    "get_changes_since_last_turn",
    "analyze_scene",
    "analyze_gn_state",
    "capture_screenshot",
    "query_node_types",
    "undo",
}


CONFIRM_THEN_APPLY_TOOLS = {
    "rename_object",
    "move_to_collection",
    "apply_simulator_payload",
    "execute_code",  # default level; risky patterns escalate to explicit_override
}


EXPLICIT_OVERRIDE_TOOLS = set()


_DANGEROUS_CODE_PATTERNS = [
    # File-level Blender operations
    re.compile(r"\bbpy\.ops\.wm\.(open_mainfile|save_mainfile|save_as_mainfile|quit_blender)\b"),
    # Shell / subprocess access
    re.compile(r"\bsubprocess\."),
    re.compile(r"\bos\.system\("),
    re.compile(r"\bshutil\."),
    # OS-level file mutations (not node/string operations)
    re.compile(r"\bos\.(remove|rename|rmdir|unlink)\("),
    re.compile(r"\brmtree\("),
    # Writing to arbitrary files
    re.compile(r"\bopen\(.+, *['\"](w|a|x)\+?['\"]\)"),
]
# Note: bpy.data.*.remove() and nodes.remove() are intentionally allowed —
# they are normal Geometry Nodes operations (removing old nodes before
# recreating them, etc.).  The broad \b(remove|replace|rename)\b pattern
# was removed because it falsely classified common GN code as risky.


@dataclass
class SafetyContext:
    route: RouteType
    debug_mode: bool = False
    explicit_override: bool = False
    user_confirmed: bool = False
    mcp_write_enabled: bool = False


@dataclass
class SafetyDecision:
    allowed: bool
    level: SafetyLevel
    reason: str
    requires_confirmation: bool = False
    requires_override: bool = False


def _is_risky_execute_code(tool_input: dict[str, Any] | None) -> bool:
    code = ""
    if isinstance(tool_input, dict):
        code = str(tool_input.get("code", "") or "")
    if not code.strip():
        return False  # Empty code is not dangerous; let the executor report the error.
    for pattern in _DANGEROUS_CODE_PATTERNS:
        if pattern.search(code):
            return True
    return False


def classify_safety_level(tool_name: str, tool_input: dict[str, Any] | None = None) -> SafetyLevel:
    if tool_name == "execute_code":
        return "explicit_override" if _is_risky_execute_code(tool_input) else "confirm_then_apply"
    if tool_name in EXPLICIT_OVERRIDE_TOOLS:
        return "explicit_override"
    if tool_name in CONFIRM_THEN_APPLY_TOOLS:
        return "confirm_then_apply"
    return "auto_apply"


def is_mutation_tool(tool_name: str) -> bool:
    return tool_name in CONFIRM_THEN_APPLY_TOOLS or tool_name in EXPLICIT_OVERRIDE_TOOLS


def evaluate_tool_call(
    tool_name: str,
    ctx: SafetyContext,
    tool_input: dict[str, Any] | None = None,
) -> SafetyDecision:
    """Return policy decision for a tool call."""
    level = classify_safety_level(tool_name, tool_input)

    if level == "auto_apply":
        return SafetyDecision(allowed=True, level=level, reason="auto_apply_safe_tool")

    if level == "confirm_then_apply":
        if ctx.route == "mcp" and not ctx.mcp_write_enabled:
            return SafetyDecision(
                allowed=False,
                level=level,
                reason="mcp_read_only_default_block",
                requires_confirmation=True,
            )
        return SafetyDecision(
            allowed=True,
            level=level,
            reason="confirm_level_mutation_allowed",
            requires_confirmation=not ctx.user_confirmed,
        )

    if ctx.route == "mcp" and not ctx.mcp_write_enabled:
        return SafetyDecision(
            allowed=False,
            level=level,
            reason="mcp_read_only_default_block",
            requires_override=True,
        )

    if ctx.debug_mode or ctx.explicit_override:
        return SafetyDecision(
            allowed=True,
            level=level,
            reason="explicit_override_granted",
            requires_override=False,
        )

    return SafetyDecision(
        allowed=False,
        level=level,
        reason="explicit_override_required",
        requires_override=True,
    )
