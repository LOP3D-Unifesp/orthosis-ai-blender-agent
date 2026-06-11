"""Advanced / Debug panel and operators.

Collapsible sub-panel (DEFAULT_CLOSED) that surfaces technical controls
and diagnostics without cluttering the default conversation surface.

Phase 8: removed dead approval-token/plan-token operators and fields.
Surviving controls: debug flags, Apply Flags, Clear Chat UI, phase info,
journal info, model, last tool activity.
"""

from __future__ import annotations

import bpy


# ---------------------------------------------------------------------------
# Operator — apply runtime permission flags
# ---------------------------------------------------------------------------

class CHAT_OT_ApplyModes(bpy.types.Operator):
    bl_idname = "chat.apply_modes"
    bl_label = "Apply Flags"
    bl_description = "Apply runtime permission flags (debug, override, MCP writes)"

    def execute(self, context):
        from .panel import _runtime_set_modes, _session_cache
        blend_path = bpy.data.filepath or ""
        scene = context.scene
        try:
            resp = _runtime_set_modes(
                blend_path=blend_path,
                debug_mode=bool(getattr(scene, "chat_debug_mode", False)),
                explicit_override_mode=bool(getattr(scene, "chat_explicit_override_mode", False)),
                mcp_write_enabled=bool(getattr(scene, "chat_mcp_write_enabled", False)),
                drafting_mode=bool(getattr(scene, "chat_drafting_mode", False)),
                simulate_bridge_failure=bool(getattr(scene, "chat_simulate_bridge_failure", False)),
            )
            if resp.get("status") == "blocked":
                self.report({"WARNING"}, "Blocked by control owner policy.")
                return {"CANCELLED"}
            if resp.get("status") != "success":
                self.report({"ERROR"}, str(resp.get("error", "Failed to apply flags.")))
                return {"CANCELLED"}
            self.report({"INFO"}, "Flags applied.")
            _session_cache["ts"] = 0.0
            from .panel import _trigger_redraw
            _trigger_redraw()
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Apply flags failed: {exc}")
            return {"CANCELLED"}


# ---------------------------------------------------------------------------
# Advanced / Debug sub-panel
# ---------------------------------------------------------------------------

class CHAT_PT_RuntimeDebug(bpy.types.Panel):
    bl_label = "Advanced / Debug"
    bl_idname = "CHAT_PT_RuntimeDebug"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Orthosis"
    bl_parent_id = "CHAT_PT_Panel"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        from .panel import (
            _get_runtime_ui_state,
            _get_bridge_endpoint,
            _get_runtime,
        )
        layout = self.layout
        host, port = _get_bridge_endpoint()
        layout.label(text=f"Bridge: {host}:{port}")
        layout.separator()

        scene = context.scene
        controls = layout.box()
        controls.label(text="Runtime Flags", icon="PREFERENCES")
        flags = controls.row(align=True)
        flags.prop(scene, "chat_mcp_write_enabled", text="MCP Writes")
        flags.prop(scene, "chat_debug_mode", text="Debug")
        flags.prop(scene, "chat_explicit_override_mode", text="Override")
        draft_row = controls.row(align=True)
        draft_row.prop(scene, "chat_drafting_mode", text="Drafting Mode", icon="TEXT")
        bridge_row = controls.row(align=True)
        bridge_row.prop(scene, "chat_simulate_bridge_failure", text="Simulate Bridge Failure", icon="ERROR")
        apply_row = controls.row(align=True)
        apply_row.operator("chat.apply_modes", text="Apply Flags", icon="CHECKMARK")

        tools_row = controls.row(align=True)
        tools_row.operator("chat.clear_history", text="Clear Chat UI", icon="TRASH")

        try:
            runtime_info = _get_runtime_ui_state(context.scene)
            runtime = _get_runtime()
            layout.separator()
            layout.label(text=f"Project: {runtime_info.get('project_root', runtime.project_root)}")
            layout.label(text=f"Session: {runtime_info.get('session_id', 'n/a')}")
            layout.label(text=f"Phase: {runtime_info.get('execution_phase', 'n/a')}")
            layout.label(text=f"Model: {runtime.model}")
            layout.label(text=f"Task Class: {runtime_info.get('task_class') or 'n/a'}")
            layout.label(text=f"Target Tree: {runtime_info.get('target_tree') or 'n/a'}")

            turn_tools = runtime_info.get("turn_tools", [])
            if turn_tools:
                layout.separator()
                layout.label(text="Last Turn Tools:")
                for tool in turn_tools[-5:]:
                    if not isinstance(tool, dict):
                        continue
                    layout.label(
                        text=f"  {tool.get('tool_name', 'tool')} [{tool.get('status', 'unknown')}]"
                    )

            last_action = runtime_info.get("last_action", {})
            if isinstance(last_action, dict) and last_action:
                layout.separator()
                layout.label(text=f"Last Tool: {last_action.get('tool_name', 'n/a')}")
                layout.label(text=f"Last Status: {last_action.get('status', 'n/a')}")
                layout.label(text=f"Last Safety: {last_action.get('safety_level', 'n/a')}")
        except Exception as exc:
            layout.label(text=f"Runtime unavailable: {exc}", icon="ERROR")


# Exported for registration in panel.py
ADVANCED_CLASSES = (
    CHAT_OT_ApplyModes,
    CHAT_PT_RuntimeDebug,
)
