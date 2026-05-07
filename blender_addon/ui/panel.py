"""Blender sidebar copilot UI — Phase 8 layered surface.

Primary surface: prose-first conversation panel in the 3D Viewport N panel
(Orthosis tab).  Advanced / debug controls live in the collapsed sub-panel.

Phase 8 changes vs Phase 7:
- Removed dead operators: ApprovePlan, DenyPlan, ResetPendingPlan,
  ClearApprovalState, ResetTransientState, RebuildPlan, TakeControl,
  ContinueSession (all referenced the pre-Phase-4 approval-token system).
- Removed dead session fields from _get_runtime_ui_state().
- Main panel shows only: session controls, phase badge, conversation,
  input/send/attach.  No plan dumps.  No token metadata.
- Advanced/debug controls stay in CHAT_PT_RuntimeDebug (DEFAULT_CLOSED).
- Added execution_phase from the V1 structured session when available.
"""

from __future__ import annotations

import os
import re
import site
import sys
import threading
import time
import traceback
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import bpy

try:
    import anthropic
except ImportError:
    anthropic = None

from ..core.runtime import AgentRuntime
from ..project_paths import resolve_project_root
from ..tools import call_blender_socket
from .. import get_effective_blend_path as _get_effective_blend_path
from .chat_session import SESSION
from .screenshot import CHAT_OT_AttachScreenshot
from .advanced import ADVANCED_CLASSES
from ._helpers import (
    _estimate_wrap_width,
    _wrap_text,
    _normalize_multiline_text,
    _PHASE_LABELS,
    _get_execution_phase as _get_execution_phase_helper,
)


# ---------------------------------------------------------------------------
# Runtime/chat support
# ---------------------------------------------------------------------------
from .panel_runtime import *  # noqa: F401,F403 - Blender panel glue intentionally re-exports helper names
from .panel_workspace import _get_prompt_buffer

from .operators import OPERATOR_CLASSES

# Phase badge helper
# ---------------------------------------------------------------------------

def _draw_phase_badge(layout, phase: str) -> None:
    """Render a phase status badge if the current phase is non-idle."""
    if not phase or phase == "idle":
        return
    label, icon = _PHASE_LABELS.get(phase, (f"Phase: {phase}", "INFO"))
    row = layout.row()
    row.alert = phase in {"failed", "halted"}
    row.scale_y = 0.9
    row.label(text=label, icon=icon)


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------

class CHAT_PT_Panel(bpy.types.Panel):
    bl_label = "GN Copilot"
    bl_idname = "CHAT_PT_Panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Orthosis"

    def draw(self, context):
        layout = self.layout

        # --- SDK check ---
        try:
            import anthropic  # noqa: F401
            sdk_ok = True
        except ImportError:
            sdk_ok = False

        if not sdk_ok:
            layout.label(text="Anthropic SDK not installed.", icon="ERROR")
            layout.operator("chat.install_sdk", icon="IMPORT")
            return

        # --- API key check ---
        api_key = _get_api_key()
        if not api_key:
            layout.label(text="No API key configured.", icon="ERROR")
            layout.label(text="Edit > Preferences > Add-ons")
            layout.label(text="> Orthosis AI Agent > Claude API Key")
            return

        runtime_info: dict = {}
        execution_phase = ""

        work_cycle_phase = "idle"
        current_revision = 0
        draft_revision_count = 0

        try:
            runtime_info = _get_runtime_ui_state(context.scene)
            _sync_scene_controls_from_runtime(context.scene, runtime_info)
            _sync_ui_messages_from_session(runtime_info)
            execution_phase = str(runtime_info.get("execution_phase", "") or "")
            work_cycle_phase = str(runtime_info.get("work_cycle_phase", "idle") or "idle")
            current_revision = int(runtime_info.get("current_revision", 0) or 0)
            draft_revision_count = int(runtime_info.get("draft_revision_count", 0) or 0)

            # --- Phase badge for internal runtime phases (non-idle, not work-cycle phases) ---
            if execution_phase and execution_phase not in ("idle", "pending_user_execution", "awaiting_feedback"):
                _draw_phase_badge(layout, execution_phase)

        except Exception as exc:
            warn = layout.box()
            warn.alert = True
            warn.label(text=f"Runtime unavailable: {exc}", icon="ERROR")

        layout.separator(factor=0.4)

        # --- Chat history ---
        messages = SESSION.get_messages()
        visible_cap = max(
            _DEFAULT_VISIBLE_MESSAGES,
            int(
                getattr(
                    context.scene,
                    "chat_visible_message_count",
                    _DEFAULT_VISIBLE_MESSAGES,
                )
                or _DEFAULT_VISIBLE_MESSAGES
            ),
        )
        visible = messages[-visible_cap:] if len(messages) > visible_cap else messages
        hidden_count = max(len(messages) - len(visible), 0)
        message_wrap_width = _message_wrap_width(context, chrome_px=96)
        compact_wrap_width = _message_wrap_width(context, chrome_px=60)

        if not visible and not SESSION.running:
            empty = layout.row()
            empty.scale_y = 0.8
            empty.label(text="No messages yet.", icon="INFO")
        else:
            if hidden_count or visible_cap > _DEFAULT_VISIBLE_MESSAGES:
                history_controls = layout.row(align=True)
                history_controls.scale_y = 0.8
                history_controls.label(
                    text=f"Showing {len(visible)} of {len(messages)} messages",
                    icon="TIME",
                )
                if hidden_count:
                    show_more = history_controls.operator(
                        "chat.show_more_messages",
                        text=f"Show {_VISIBLE_MESSAGES_STEP} More",
                        icon="ADD",
                    )
                    show_more.step = _VISIBLE_MESSAGES_STEP
                if visible_cap > _DEFAULT_VISIBLE_MESSAGES:
                    history_controls.operator(
                        "chat.collapse_messages",
                        text="Recent Only",
                        icon="REMOVE",
                    )
            box = layout.box()
            start_idx = len(messages) - len(visible)

            for vi, msg in enumerate(visible):
                role = msg["role"]
                text = msg["text"]
                is_user = role == "user"

                # Header row — icon + role label + copy button
                header = box.row(align=True)
                header.scale_y = 0.75
                if is_user:
                    header.label(text="You", icon="USER")
                else:
                    header.label(text="Agent", icon="OUTLINER_OB_LIGHT")
                copy_op = header.operator("chat.copy_message", text="", icon="COPYDOWN")
                copy_op.index = start_idx + vi

                # Message body — prose-first: first wrapped line is slightly taller
                lines = _wrap_text(text, width=message_wrap_width)
                for li, line in enumerate(lines):
                    r = box.row()
                    r.scale_y = 0.85 if (li == 0 and not is_user) else 0.72
                    r.label(text=line, icon="NONE")

                if vi < len(visible) - 1:
                    box.separator(factor=0.25)

        # --- Running / streaming indicator ---
        if SESSION.running:
            layout.separator(factor=0.4)
            reasoning = SESSION.reasoning_text
            stream_text = SESSION.streaming_text
            tool_name = SESSION.current_tool

            if reasoning.strip():
                reason_box = layout.box()
                rh = reason_box.row(align=True)
                rh.label(text="Reasoning:", icon="TEXT")
                rh.operator("chat.copy_reasoning", text="", icon="COPYDOWN")
                for line in _wrap_text(reasoning.strip(), width=compact_wrap_width)[-_STREAM_PREVIEW_LINES:]:
                    r = reason_box.row()
                    r.scale_y = 0.7
                    r.label(text=line)

            if stream_text:
                stream_box = layout.box()
                stream_box.label(text="Generating...", icon="TEMP")
                for line in _wrap_text(stream_text, width=compact_wrap_width)[-_STREAM_PREVIEW_LINES:]:
                    r = stream_box.row()
                    r.scale_y = 0.7
                    r.label(text=line)
            elif tool_name:
                row = layout.row()
                row.alert = True
                row.label(text=tool_name, icon="CONSOLE")
            else:
                row = layout.row()
                row.alert = True
                row.label(text="Thinking...", icon="TEMP")

        # --- Error display ---
        if SESSION.error and not SESSION.running:
            layout.separator(factor=0.3)
            err_box = layout.box()
            err_box.label(text="Error:", icon="CANCEL")
            for line in _wrap_text(SESSION.error[:300], width=compact_wrap_width):
                r = err_box.row()
                r.scale_y = 0.7
                r.label(text=line)

        layout.separator(factor=0.3)

        # ================================================================
        # Onda 5 (Item 5.4): 4-state panel layout
        # ================================================================

        if work_cycle_phase == "pending_user_execution":
            # ---- PRONTO: draft ready, awaiting user execution ----
            pronto_box = layout.box()
            rev_row = pronto_box.row()
            rev_row.label(text=f"Draft pronto — Revisão v{current_revision}", icon="CHECKMARK")

            btn_row = pronto_box.row(align=True)
            btn_row.scale_y = 1.4
            btn_row.operator("blend.execute_draft", text="Abrir p/ Executar", icon="PLAY")
            btn_row.operator("blend.discard_draft", text="Descartar", icon="X")

        elif work_cycle_phase == "executing":
            # ---- EXECUTANDO: waiting for user to run script ----
            exec_box = layout.box()
            exec_box.label(text="Execute o script no Text Editor:", icon="SCRIPT")
            exec_box.label(text="Text Editor → GN_Agent_Draft → Run Script")
            open_row = exec_box.row()
            open_row.operator("blend.open_draft", text="Abrir Draft", icon="TEXT")
            run_row = exec_box.row()
            run_row.scale_y = 1.4
            run_row.alert = True
            run_row.operator("blend.run_draft", text="Rodar Draft", icon="PLAY")
            exec_row = exec_box.row()
            exec_row.scale_y = 1.5
            exec_row.alert = True
            exec_row.operator("blend.report_result", text="Reportar resultado", icon="CHECKMARK")

        elif work_cycle_phase == "awaiting_feedback":
            # ---- RESULTADO: user reports what happened ----
            result_box = layout.box()
            result_box.label(text="O que aconteceu?", icon="QUESTION")

            result_failed_mode = bool(getattr(context.scene, "chat_result_failed_mode", False))

            if not result_failed_mode:
                btn_row = result_box.row(align=True)
                btn_row.scale_y = 1.3
                btn_row.operator("blend.result_success", text="Funcionou", icon="CHECKMARK")
                btn_row.operator("blend.result_failed", text="Nao funcionou", icon="ERROR")
            else:
                result_box.label(text="Descreva o que aconteceu visualmente:")
                desc_col = result_box.column(align=True)
                desc_col.prop(context.scene, "chat_result_description", text="")

                action_row = result_box.row(align=True)
                action_row.scale_y = 1.2
                action_row.operator("chat.attach_screenshot", text="Screenshot", icon="IMAGE_DATA")
                action_row.operator("blend.revert_snapshot", text="So Reverter", icon="RECOVER_LAST")

                # Primary action: send feedback AND revert together (recommended flow)
                combo_row = result_box.row()
                combo_row.scale_y = 1.4
                combo_row.alert = True
                combo_row.operator("blend.send_and_revert", text="Enviar e Reverter", icon="FILE_REFRESH")

                # Secondary: send feedback only (keep current Blender state)
                send_row = result_box.row()
                send_row.scale_y = 1.2
                send_row.operator("blend.send_result_report", text="So Enviar relatorio", icon="EXPORT")

        else:
            # ---- CONVERSA (idle): normal chat input ----
            input_col = layout.column(align=True)
            input_col.enabled = not SESSION.running
            input_col.scale_y = 1.3
            input_col.prop(context.scene, "chat_input", text="")

            action_row = layout.row(align=True)
            action_row.enabled = (not SESSION.running) and (not SESSION.screenshot_running)
            action_row.scale_y = 1.2
            action_row.operator("chat.send_message", text="Enviar", icon="PLAY")
            action_row.operator("chat.attach_screenshot", text="", icon="IMAGE_DATA")
            action_row.operator("chat.attach_file", text="", icon="FILEBROWSER")

            buffer_row = layout.row(align=True)
            buffer_row.enabled = (not SESSION.running) and (not SESSION.screenshot_running)
            buffer_row.scale_y = 1.0
            buffer_row.operator("chat.open_prompt_buffer", text="Open Buffer", icon="TEXT")
            buffer_row.operator("chat.send_prompt_buffer", text="Send Buffer", icon="FILE_TEXT")
            buffer_row.operator("chat.load_clipboard_to_prompt_buffer", text="", icon="PASTEDOWN")

            prompt_buffer = _get_prompt_buffer(context.scene, create=False)
            helper = layout.row()
            helper.scale_y = 0.75
            if prompt_buffer is not None:
                helper.label(text=f"Buffer: {prompt_buffer.name}", icon="TEXT")
            else:
                helper.label(text="Open Buffer to edit multi-line prompts.", icon="INFO")

            if SESSION.screenshot_running:
                cap = layout.row()
                cap.alert = True
                cap.label(text="Capturando screenshot...", icon="IMAGE_DATA")

            if SESSION.screenshot_notice:
                layout.row().label(text=SESSION.screenshot_notice, icon="INFO")

            if SESSION.session_notice:
                note = layout.row()
                note.alert = True
                note.label(text=SESSION.session_notice, icon="INFO")

            pending_count = SESSION.pending_screenshot_count()
            if pending_count:
                ind = layout.row()
                ind.alert = True
                with SESSION._lock:
                    total_kb = sum(len(b) for b in SESSION.pending_screenshots) // 1024
                suffix = "screenshot" if pending_count == 1 else "screenshots"
                ind.label(text=f"{pending_count} {suffix} ({total_kb}KB) — sent with next message", icon="IMAGE_DATA")

            pending_file_count = SESSION.pending_file_count()
            if pending_file_count:
                ind = layout.row()
                ind.alert = True
                with SESSION._lock:
                    total_kb = sum(int(item.get("bytes", 0) or 0) for item in SESSION.pending_files) // 1024
                suffix = "file" if pending_file_count == 1 else "files"
                ind.label(text=f"{pending_file_count} {suffix} ({total_kb}KB) — sent with next message", icon="FILE_TEXT")

        # --- Token cost indicator (always visible) ---
        last_in = SESSION.last_turn_input_tokens
        last_out = SESSION.last_turn_output_tokens
        sess_in = SESSION.session_input_tokens
        sess_out = SESSION.session_output_tokens
        if last_in or last_out:
            tok_row = layout.row()
            tok_row.scale_y = 0.7
            last_total = last_in + last_out
            sess_total = sess_in + sess_out
            tok_row.label(
                text=f"Último turno: {last_total:,} tokens ({last_in:,}↑ {last_out:,}↓)  |  Sessão: {sess_total:,}",
                icon="TRACKING",
            )

        # --- Footer ---
        layout.separator(factor=0.3)
        footer = layout.row(align=True)
        footer.scale_y = 0.85
        footer.operator("chat.setup_workspace", text="GN Workspace", icon="NODETREE")
        footer.operator("chat.open_journal_folder", text="Journal", icon="FILE_FOLDER")
        layout.separator(factor=0.2)


# ---------------------------------------------------------------------------
# Addon preferences
# ---------------------------------------------------------------------------

class OrthosisAddonPreferences(bpy.types.AddonPreferences):
    bl_idname = "blender_addon"

    claude_api_key: bpy.props.StringProperty(
        name="Claude API Key",
        description="Anthropic API key (get one at console.anthropic.com)",
        subtype="PASSWORD",
        default="",
    )

    claude_model: bpy.props.StringProperty(
        name="Model",
        description="Claude model to use",
        default="claude-sonnet-4-6",
    )

    project_root_path: bpy.props.StringProperty(
        name="Project Root Path",
        description="Canonical root of blend_IA_ort_v2 (contains knowledge/, blender_addon/)",
        subtype="DIR_PATH",
        default="",
        update=_on_project_root_path_updated,
    )

    def draw(self, context):
        layout = self.layout
        host, port = _get_bridge_endpoint()
        resolved_root = str(resolve_project_root())
        layout.prop(self, "claude_api_key")
        layout.prop(self, "claude_model")
        layout.prop(self, "project_root_path")
        layout.separator()
        layout.label(text=f"Runtime Bridge: {host}:{port}")
        layout.separator()
        layout.label(text="Models: claude-sonnet-4-6, claude-opus-4-6, claude-haiku-4-5-20251001")
        layout.label(text=f"Active root: {resolved_root}")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_MAIN_CLASSES = (
    OrthosisAddonPreferences,
    CHAT_OT_AttachScreenshot,   # from screenshot.py
    *OPERATOR_CLASSES,
    CHAT_PT_Panel,
)

_ALL_CLASSES = _MAIN_CLASSES + ADVANCED_CLASSES


def _unregister_class_if_registered(cls) -> None:
    """Best-effort cleanup for Blender reload/install after a prior failed register."""
    candidates = []
    existing = getattr(bpy.types, getattr(cls, "__name__", ""), None)
    if existing is not None:
        candidates.append(existing)
    candidates.append(cls)
    seen: set[int] = set()
    for candidate in candidates:
        marker = id(candidate)
        if marker in seen:
            continue
        seen.add(marker)
        try:
            bpy.utils.unregister_class(candidate)
        except Exception:
            pass


def register() -> None:
    global _runtime_poll_registered
    for cls in _ALL_CLASSES:
        _unregister_class_if_registered(cls)
        bpy.utils.register_class(cls)

    bpy.types.Scene.chat_input = bpy.props.StringProperty(
        name="Message",
        description="Type your message here",
        options={"TEXTEDIT_UPDATE"},
        default="",
    )
    bpy.types.Scene.chat_prompt_buffer = bpy.props.PointerProperty(
        name="Prompt Buffer",
        description="Text datablock used for multi-line GN chat prompts",
        type=bpy.types.Text,
    )
    bpy.types.Scene.chat_debug_mode = bpy.props.BoolProperty(
        name="Debug",
        description="Enable debug mode for runtime policy context",
        default=False,
    )
    bpy.types.Scene.chat_explicit_override_mode = bpy.props.BoolProperty(
        name="Override",
        description="Enable explicit override mode for risky mutations",
        default=False,
    )
    bpy.types.Scene.chat_mcp_write_enabled = bpy.props.BoolProperty(
        name="MCP Writes",
        description="Allow mutating MCP calls",
        default=False,
    )
    bpy.types.Scene.chat_drafting_mode = bpy.props.BoolProperty(
        name="Drafting Mode",
        description="Agent writes scripts to Text Editor for manual execution instead of auto-executing",
        default=False,
    )
    bpy.types.Scene.chat_simulate_bridge_failure = bpy.props.BoolProperty(
        name="Simulate Bridge Failure",
        description="Debug validation: make structural-memory recovery fail while keeping the chat UI available",
        default=False,
    )
    bpy.types.Scene.chat_visible_message_count = bpy.props.IntProperty(
        name="Visible Messages",
        description="How many recent chat messages are shown in the panel",
        default=_DEFAULT_VISIBLE_MESSAGES,
        min=_DEFAULT_VISIBLE_MESSAGES,
    )
    bpy.types.Scene.chat_result_failed_mode = bpy.props.BoolProperty(
        name="Result Failed Mode",
        description="Shows the failure description field in RESULTADO state",
        default=False,
    )
    bpy.types.Scene.chat_result_description = bpy.props.StringProperty(
        name="Result Description",
        description="O que aconteceu visualmente ao executar o script",
        options={"TEXTEDIT_UPDATE"},
        default="",
    )
    if not _runtime_poll_registered:
        bpy.app.timers.register(_poll_runtime_redraw, first_interval=1.0, persistent=True)
        _runtime_poll_registered = True


def unregister() -> None:
    global _runtime_poll_registered
    for cls in reversed(_ALL_CLASSES):
        _unregister_class_if_registered(cls)

    for prop in ("chat_input", "chat_prompt_buffer", "chat_debug_mode",
                 "chat_explicit_override_mode", "chat_mcp_write_enabled",
                 "chat_visible_message_count", "chat_drafting_mode",
                 "chat_simulate_bridge_failure",
                 "chat_result_failed_mode", "chat_result_description"):
        if hasattr(bpy.types.Scene, prop):
            delattr(bpy.types.Scene, prop)

    if _runtime_poll_registered and bpy.app.timers.is_registered(_poll_runtime_redraw):
        bpy.app.timers.unregister(_poll_runtime_redraw)
        _runtime_poll_registered = False
