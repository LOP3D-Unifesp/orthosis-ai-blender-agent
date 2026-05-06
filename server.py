"""Alternate MCP adapter for the Blender copilot runtime bridge.

Primary product path:
- Blender sidebar copilot UI for day-to-day use.

Alternate path:
- MCP tools for Claude and external technical automation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from blender_connection import BlenderConnection, BlenderConnectionError
from blender_addon.operation_journal import OperationJournal
from mcp_policy import resolve_user_confirmation


mcp = FastMCP("Orthosis MCP Server")
_blender = BlenderConnection()
_journal = OperationJournal(project_root=PROJECT_ROOT)

def _ok(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


def _runtime_tool(
    tool_name: str,
    tool_input: dict | None = None,
    *,
    output_mode: str = "compact",
    user_confirmed: bool | None = None,
) -> str:
    try:
        confirmed = resolve_user_confirmation(tool_name, user_confirmed)
        result = _blender.runtime_tool_call(
            tool_name=tool_name,
            tool_input=tool_input or {},
            route="mcp",
            output_mode=output_mode,
            user_confirmed=confirmed,
        )
        return _ok(result)
    except BlenderConnectionError as exc:
        return _ok({"status": "error", "error": str(exc)})


def _runtime_session_state() -> dict:
    try:
        return _blender.runtime_get_session()
    except BlenderConnectionError as exc:
        return {"status": "error", "error": str(exc)}


def _compact_runtime_overview(state: dict) -> dict:
    """Compact session snapshot for MCP callers.

    Phase 9: removed dead approval/plan fields (approval_token, current_plan_id,
    presented_plan_*, approval_required, approval_status) — all deleted in Phases 3-5.
    """
    session = state.get("result", {}) if state.get("status") == "success" else {}
    if not isinstance(session, dict):
        session = {}
    return {
        "status": state.get("status", "error"),
        "error": state.get("error", ""),
        "session_id": session.get("session_id", ""),
        "session_state": session.get("session_state", "no_session"),
        "blend_path": session.get("blend_path", ""),
        "runtime_phase": session.get("runtime_phase", "idle"),
        "agent_session_active": bool(session.get("agent_session_active", False)),
        "turn_counter": session.get("turn_counter", 0),
        "last_task_class": session.get("last_task_class", ""),
        "last_routing_reason": session.get("last_routing_reason", ""),
        "target_tree": session.get("last_target_tree", "") or session.get("target_tree", ""),
        "journal_base_dir": session.get("_runtime_journal_base_dir", ""),
        "journal_session_file": session.get("_runtime_journal_session_file", ""),
        "journal_index_file": session.get("_runtime_journal_index_file", ""),
    }


def _compact_modes_response(state: dict, *, action: str) -> dict:
    overview = _compact_runtime_overview(state)
    session = state.get("result", {}) if state.get("status") == "success" else {}
    if not isinstance(session, dict):
        session = {}
    overview.update(
        {
            "action": action,
            "control_update_blocked": bool(session.get("control_update_blocked", False)),
            "control_update_blocked_by": session.get("control_update_blocked_by", ""),
            "control_update_source": session.get("control_update_source", ""),
            "approval_source": session.get("approval_source", ""),
            "last_failure": session.get("last_failure", ""),
            "current_stage_id": session.get("current_stage_id", ""),
            "current_stage_index": session.get("current_stage_index", -1),
        }
    )
    return overview


def _runtime_set_modes_compact(*, action: str, **kwargs) -> str:
    try:
        result = _blender.runtime_set_modes(**kwargs)
        return _ok(_compact_modes_response(result, action=action))
    except BlenderConnectionError as exc:
        return _ok({"status": "error", "action": action, "error": str(exc)})




# ---------------------------------------------------------------------------
# Read / diagnostics
# ---------------------------------------------------------------------------


@mcp.tool()
def get_scene_summary() -> str:
    return _runtime_tool("get_scene_summary", {})


@mcp.tool()
def get_gn_hosts() -> str:
    return _runtime_tool("get_gn_hosts", {})


@mcp.tool()
def get_tree_parameters(tree_name: str) -> str:
    return _runtime_tool("get_tree_parameters", {"tree_name": tree_name})


@mcp.tool()
def resolve_gn_workspace(
    user_message: str = "",
    tree_name: str = "",
    object_name: str = "",
    modifier_name: str = "",
) -> str:
    payload: dict = {}
    if user_message:
        payload["user_message"] = user_message
    if tree_name:
        payload["tree_name"] = tree_name
    if object_name:
        payload["object_name"] = object_name
    if modifier_name:
        payload["modifier_name"] = modifier_name
    return _runtime_tool("resolve_gn_workspace", payload)


@mcp.tool()
def build_tree_structural_memory(
    tree_name: str = "",
    user_message: str = "",
    force_refresh: bool = False,
) -> str:
    payload: dict = {"force_refresh": force_refresh}
    if tree_name:
        payload["tree_name"] = tree_name
    if user_message:
        payload["user_message"] = user_message
    return _runtime_tool("build_tree_structural_memory", payload)


@mcp.tool()
def classify_tree_phases(
    tree_name: str = "",
    user_message: str = "",
    force_refresh: bool = False,
) -> str:
    payload: dict = {"force_refresh": force_refresh}
    if tree_name:
        payload["tree_name"] = tree_name
    if user_message:
        payload["user_message"] = user_message
    return _runtime_tool("classify_tree_phases", payload)


@mcp.tool()
def map_clinical_parameter_roles(
    tree_name: str = "",
    user_message: str = "",
    force_refresh: bool = False,
) -> str:
    payload: dict = {"force_refresh": force_refresh}
    if tree_name:
        payload["tree_name"] = tree_name
    if user_message:
        payload["user_message"] = user_message
    return _runtime_tool("map_clinical_parameter_roles", payload)


@mcp.tool()
def interpret_orthosis_tree_logic(
    tree_name: str = "",
    user_message: str = "",
    force_refresh: bool = False,
) -> str:
    payload: dict = {"force_refresh": force_refresh}
    if tree_name:
        payload["tree_name"] = tree_name
    if user_message:
        payload["user_message"] = user_message
    return _runtime_tool("interpret_orthosis_tree_logic", payload)


@mcp.tool()
def get_node_context(
    tree_name: str,
    node_name: str = "",
    label: str = "",
    radius: int = 1,
) -> str:
    return _runtime_tool(
        "get_node_context",
        {
            "tree_name": tree_name,
            "node_name": node_name,
            "label": label,
            "radius": radius,
        },
    )


@mcp.tool()
def get_selected_nodes_context(tree_name: str, include_neighbors: bool = True, radius: int = 1) -> str:
    return _runtime_tool(
        "get_selected_nodes_context",
        {
            "tree_name": tree_name,
            "include_neighbors": include_neighbors,
            "radius": radius,
        },
    )


@mcp.tool()
def get_active_frame_context(
    tree_name: str,
    frame_name: str = "",
    include_neighbors: bool = False,
    radius: int = 1,
) -> str:
    return _runtime_tool(
        "get_active_frame_context",
        {
            "tree_name": tree_name,
            "frame_name": frame_name,
            "include_neighbors": include_neighbors,
            "radius": radius,
        },
    )


@mcp.tool()
def get_local_subgraph_context(
    tree_name: str,
    scope_mode: str,
    node_names: list[str] | None = None,
    center_node: str = "",
    hops: int = 1,
    direction: str = "both",
    max_nodes: int = 80,
) -> str:
    payload: dict = {
        "tree_name": tree_name,
        "scope_mode": scope_mode,
        "hops": hops,
        "direction": direction,
        "max_nodes": max_nodes,
    }
    if node_names:
        payload["node_names"] = node_names
    if center_node:
        payload["center_node"] = center_node
    return _runtime_tool("get_local_subgraph_context", payload)


@mcp.tool()
def get_changes_since_last_turn(tree_name: str = "", update_marker: bool = True, limit: int = 25) -> str:
    payload = {"update_marker": update_marker, "limit": limit}
    if tree_name:
        payload["tree_name"] = tree_name
    return _runtime_tool("get_changes_since_last_turn", payload)


@mcp.tool()
def analyze_scene(current_goal: str = "", query: str = "summarize_scene_for_current_round") -> str:
    return _runtime_tool("analyze_scene", {"current_goal": current_goal, "query": query, "output_mode": "compact"})


@mcp.tool()
def analyze_gn_state(tree_name: str = "", current_goal: str = "", query: str = "inspect_deep_structure") -> str:
    payload = {"current_goal": current_goal, "query": query, "output_mode": "compact"}
    if tree_name:
        payload["tree_name"] = tree_name
    return _runtime_tool("analyze_gn_state", payload)


@mcp.tool()
def capture_screenshot(max_size: int = 900) -> str:
    return _runtime_tool("capture_screenshot", {"max_size": max_size})


@mcp.tool()
def get_runtime_overview() -> str:
    """Return a compact MCP-first snapshot of the backend technical session."""
    return _ok(_compact_runtime_overview(_runtime_session_state()))


@mcp.tool()
def get_current_session_journal_summary(max_goals: int = 5) -> str:
    """Return a compact summary of the latest session journal for MCP-side diagnosis."""
    try:
        summary = _journal.get_last_session_summary(max_goals=max_goals)
        overview = _compact_runtime_overview(_runtime_session_state())
        return _ok(
            {
                "status": "success",
                "session_id": overview.get("session_id", ""),
                "journal_session_file": overview.get("journal_session_file", ""),
                "summary": summary,
            }
        )
    except Exception as exc:
        return _ok({"status": "error", "error": str(exc)})


@mcp.tool()
def get_previous_session_journal_summary(max_goals: int = 5) -> str:
    """Return a compact summary of the journal immediately before the current session."""
    try:
        summary = _journal.get_previous_session_summary(max_goals=max_goals)
        return _ok({"status": "success", "summary": summary})
    except Exception as exc:
        return _ok({"status": "error", "error": str(exc)})


# ---------------------------------------------------------------------------
# Structured GN mutations (blocked until MCP writes are enabled)
# ---------------------------------------------------------------------------


@mcp.tool()
def apply_simulator_payload(
    tree_name: str,
    payload: dict,
    mapping: dict | None = None,
    strict: bool = False,
    transactional: bool = True,
) -> str:
    body = {
        "tree_name": tree_name,
        "payload": payload,
        "strict": strict,
        "transactional": transactional,
    }
    if mapping is not None:
        body["mapping"] = mapping
    return _runtime_tool("apply_simulator_payload", body)


@mcp.tool()
def execute_code(code: str, user_confirmed: bool = False) -> str:
    return _runtime_tool("execute_code", {"code": code}, user_confirmed=user_confirmed)


@mcp.tool()
def undo_last_action() -> str:
    return _runtime_tool("undo", {})


# ---------------------------------------------------------------------------
# Runtime mode controls
# ---------------------------------------------------------------------------


@mcp.tool()
def enable_mcp_writes() -> str:
    return _runtime_set_modes_compact(
        action="enable_mcp_writes",
        mcp_write_enabled=True,
        control_source="mcp",
    )


@mcp.tool()
def set_mcp_read_only() -> str:
    return _runtime_set_modes_compact(
        action="set_mcp_read_only",
        mcp_write_enabled=False,
        control_source="mcp",
    )


@mcp.tool()
def set_runtime_debug_mode(enabled: bool) -> str:
    return _runtime_set_modes_compact(
        action="set_runtime_debug_mode",
        debug_mode=enabled,
        control_source="mcp",
    )


@mcp.tool()
def set_runtime_override_mode(enabled: bool) -> str:
    return _runtime_set_modes_compact(
        action="set_runtime_override_mode",
        explicit_override_mode=enabled,
        control_source="mcp",
    )


@mcp.tool()
def get_runtime_session_state() -> str:
    try:
        return _ok(_blender.runtime_get_session())
    except BlenderConnectionError as exc:
        return _ok({"status": "error", "error": str(exc)})


@mcp.tool()
def start_agent_session(reset_session_memory: bool = True) -> str:
    return _runtime_set_modes_compact(
        action="start_agent_session",
        agent_session_active=True,
        reset_session_memory=reset_session_memory,
        start_new_session=reset_session_memory,
        control_source="mcp",
    )


@mcp.tool()
def start_new_session() -> str:
    """Rotate session_id, create a new journal file, and activate a fresh technical session."""
    return _runtime_set_modes_compact(
        action="start_new_session",
        agent_session_active=True,
        reset_session_memory=True,
        start_new_session=True,
        control_source="mcp",
    )


@mcp.tool()
def continue_agent_session() -> str:
    """Resume the current technical session without rotating session_id or clearing memory."""
    return _runtime_set_modes_compact(
        action="continue_agent_session",
        agent_session_active=True,
        reset_session_memory=False,
        control_source="mcp",
    )


@mcp.tool()
def continue_current_session() -> str:
    """Alias for continue_agent_session with a more MCP-first name."""
    return continue_agent_session()


@mcp.tool()
def end_agent_session(reset_session_memory: bool = True) -> str:
    return _runtime_set_modes_compact(
        action="end_agent_session",
        agent_session_active=False,
        reset_session_memory=reset_session_memory,
        control_source="mcp",
    )


@mcp.tool()
def end_current_session() -> str:
    """End the active technical session and clear pending runtime state."""
    return _runtime_set_modes_compact(
        action="end_current_session",
        agent_session_active=False,
        reset_session_memory=True,
        control_source="mcp",
    )


if __name__ == "__main__":
    mcp.run()
