"""MCP adapter policy helpers (pure module, no MCP dependency)."""

from __future__ import annotations


MCP_STRUCTURED_MUTATION_TOOLS = {
    "apply_simulator_payload",
    "rename_object",
    "move_to_collection",
}


def resolve_user_confirmation(tool_name: str, user_confirmed: bool | None) -> bool:
    """Resolve MCP confirmation semantics.

    Structured mutation calls are treated as explicit confirmation when invoked
    directly through MCP tool methods. execute_code remains explicit.
    """
    if user_confirmed is not None:
        return bool(user_confirmed)
    if tool_name in MCP_STRUCTURED_MUTATION_TOOLS:
        return True
    return False

