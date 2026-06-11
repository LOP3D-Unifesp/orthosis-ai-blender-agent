"""Chat and utility operators for the GN Copilot UI."""

from __future__ import annotations

import os
import sys

import bpy
from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper

from . import panel_runtime as _panel
from . import panel_workspace as _workspace
from .panel_chat_turn import _send_user_message

SESSION = _panel.SESSION
_DEFAULT_VISIBLE_MESSAGES = _panel._DEFAULT_VISIBLE_MESSAGES
_VISIBLE_MESSAGES_STEP = _panel._VISIBLE_MESSAGES_STEP
_ensure_sdk_path = _panel._ensure_sdk_path
_get_effective_blend_path = _panel._get_effective_blend_path
_get_runtime = _panel._get_runtime
_normalize_multiline_text = _panel._normalize_multiline_text
_get_prompt_buffer = _workspace._get_prompt_buffer
_open_prompt_buffer_in_workspace = _workspace._open_prompt_buffer_in_workspace
_read_text_attachment = _workspace._read_text_attachment
_replace_text_block_contents = _workspace._replace_text_block_contents
_schedule_redraw = _panel._schedule_redraw
_seed_prompt_buffer_from_input = _workspace._seed_prompt_buffer_from_input
_session_cache = _panel._session_cache
_trigger_redraw = _panel._trigger_redraw

class CHAT_OT_SendMessage(bpy.types.Operator):
    bl_idname = "chat.send_message"
    bl_label = "Send"
    bl_description = "Send message to Claude"

    def execute(self, context):
        result, message = _send_user_message(context, context.scene.chat_input)
        if "CANCELLED" in result:
            level = {"ERROR"} if "API key" in message else {"WARNING"}
            self.report(level, message)
        return result


class CHAT_OT_SendClipboard(bpy.types.Operator):
    bl_idname = "chat.send_clipboard"
    bl_label = "Send Clipboard"
    bl_description = "Send clipboard text directly (supports multi-line prompts)"

    def execute(self, context):
        raw = context.window_manager.clipboard or ""
        text = _normalize_multiline_text(raw)
        body = text.strip()
        display = f"[Clipboard]\n{body}" if body else "[Clipboard]"
        result, message = _send_user_message(context, text, display_text=display)
        if "CANCELLED" in result:
            level = {"ERROR"} if "API key" in message else {"WARNING"}
            self.report(level, message)
        else:
            self.report({"INFO"}, "Sent prompt from clipboard.")
        return result


class CHAT_OT_OpenPromptBuffer(bpy.types.Operator):
    bl_idname = "chat.open_prompt_buffer"
    bl_label = "Open Prompt Buffer"
    bl_description = "Open the GN chat prompt buffer in a real Blender Text Editor"

    def execute(self, context):
        text_block = _get_prompt_buffer(context.scene, create=True)
        if text_block is None:
            self.report({"ERROR"}, "Could not create the prompt buffer.")
            return {"CANCELLED"}
        _seed_prompt_buffer_from_input(context.scene, text_block)
        if _open_prompt_buffer_in_workspace(context, text_block):
            self.report({"INFO"}, f"Prompt buffer ready: {text_block.name}")
        else:
            self.report({"WARNING"}, "Prompt buffer created, but no Text Editor could be opened automatically.")
        _trigger_redraw()
        return {"FINISHED"}


class CHAT_OT_SendPromptBuffer(bpy.types.Operator):
    bl_idname = "chat.send_prompt_buffer"
    bl_label = "Send Prompt Buffer"
    bl_description = "Send the current multi-line prompt buffer"

    def execute(self, context):
        text_block = _get_prompt_buffer(context.scene, create=False)
        if text_block is None:
            self.report({"WARNING"}, "Prompt buffer is empty. Open it first.")
            return {"CANCELLED"}
        text = _normalize_multiline_text(text_block.as_string())
        if not text.strip():
            self.report({"WARNING"}, "Prompt buffer is empty.")
            return {"CANCELLED"}
        body = text.strip()
        display = f"[Prompt Buffer]\n{body}" if body else "[Prompt Buffer]"
        result, message = _send_user_message(context, text, display_text=display)
        if "CANCELLED" in result:
            level = {"ERROR"} if "API key" in message else {"WARNING"}
            self.report(level, message)
        else:
            self.report({"INFO"}, "Sent prompt from Prompt Buffer.")
        return result


class CHAT_OT_LoadClipboardToPromptBuffer(bpy.types.Operator):
    bl_idname = "chat.load_clipboard_to_prompt_buffer"
    bl_label = "Load Clipboard To Buffer"
    bl_description = "Replace the Prompt Buffer contents with clipboard text"

    def execute(self, context):
        raw = context.window_manager.clipboard or ""
        text = _normalize_multiline_text(raw)
        if not text.strip():
            self.report({"WARNING"}, "Clipboard is empty.")
            return {"CANCELLED"}
        text_block = _get_prompt_buffer(context.scene, create=True)
        if text_block is None:
            self.report({"ERROR"}, "Could not create the prompt buffer.")
            return {"CANCELLED"}
        _replace_text_block_contents(text_block, text)
        lines = len(text.split("\n"))
        self.report({"INFO"}, f"Prompt buffer loaded from clipboard ({len(text)} chars, {lines} lines).")
        _trigger_redraw()
        return {"FINISHED"}


class CHAT_OT_ClearHistory(bpy.types.Operator):
    bl_idname = "chat.clear_history"
    bl_label = "Clear"
    bl_description = "Clear chat history and start a new conversation"

    def execute(self, context):
        SESSION.clear()
        try:
            context.scene.chat_visible_message_count = _DEFAULT_VISIBLE_MESSAGES
        except Exception:
            pass
        runtime = _get_runtime()
        runtime.clear_history(blend_path=_get_effective_blend_path())
        _session_cache["ts"] = 0.0
        _session_cache["blend_path"] = ""
        _session_cache["state"] = None
        _trigger_redraw()
        return {"FINISHED"}


class CHAT_OT_ShowMoreMessages(bpy.types.Operator):
    bl_idname = "chat.show_more_messages"
    bl_label = "Show More"
    bl_description = "Show more chat messages"

    step: bpy.props.IntProperty(default=_VISIBLE_MESSAGES_STEP, min=1)

    def execute(self, context):
        scene = context.scene
        current = int(
            getattr(scene, "chat_visible_message_count", _DEFAULT_VISIBLE_MESSAGES)
            or _DEFAULT_VISIBLE_MESSAGES
        )
        scene.chat_visible_message_count = current + max(int(self.step or _VISIBLE_MESSAGES_STEP), 1)
        _trigger_redraw()
        return {"FINISHED"}


class CHAT_OT_CollapseMessages(bpy.types.Operator):
    bl_idname = "chat.collapse_messages"
    bl_label = "Recent Only"
    bl_description = "Show only the most recent chat messages"

    def execute(self, context):
        context.scene.chat_visible_message_count = _DEFAULT_VISIBLE_MESSAGES
        _trigger_redraw()
        return {"FINISHED"}


class CHAT_OT_CopyMessage(bpy.types.Operator):
    bl_idname = "chat.copy_message"
    bl_label = "Copy"
    bl_description = "Copy this message to clipboard"

    index: bpy.props.IntProperty(default=-1)

    def execute(self, context):
        messages = SESSION.get_messages()
        idx = self.index
        if idx < 0:
            idx = len(messages) + idx
        if 0 <= idx < len(messages):
            text = messages[idx]["text"]
            context.window_manager.clipboard = text
            self.report({"INFO"}, f"Copied ({len(text)} chars)")
        else:
            self.report({"WARNING"}, "No message to copy.")
        return {"FINISHED"}


class CHAT_OT_CopyReasoning(bpy.types.Operator):
    bl_idname = "chat.copy_reasoning"
    bl_label = "Copy Reasoning"
    bl_description = "Copy the agent's reasoning text to clipboard"

    def execute(self, context):
        text = SESSION.reasoning_text.strip()
        if text:
            context.window_manager.clipboard = text
            self.report({"INFO"}, f"Copied reasoning ({len(text)} chars)")
        else:
            self.report({"WARNING"}, "No reasoning text available.")
        return {"FINISHED"}


class CHAT_OT_InstallSdk(bpy.types.Operator):
    bl_idname = "chat.install_sdk"
    bl_label = "Install Anthropic SDK"
    bl_description = "Install the Anthropic Python SDK in Blender's Python"

    def execute(self, context):
        import subprocess
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "anthropic", "--no-warn-script-location"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                _ensure_sdk_path()
                self.report({"INFO"}, "Anthropic SDK installed. Reload addon or restart Blender.")
            else:
                self.report({"ERROR"}, f"Install failed: {result.stderr[-200:]}")
        except Exception as exc:
            self.report({"ERROR"}, f"Install failed: {exc}")
        return {"FINISHED"}


class CHAT_OT_AttachFile(bpy.types.Operator, ImportHelper):
    bl_idname = "chat.attach_file"
    bl_label = "Attach File"
    bl_description = "Attach a text or JSON file as context for the next message"

    filename_ext = ""
    filter_glob: StringProperty(
        default="*.json;*.txt;*.md;*.py;*.log;*.yaml;*.yml;*.csv",
        options={"HIDDEN"},
    )

    def execute(self, context):
        try:
            entry = _read_text_attachment(self.filepath)
            queue_size = SESSION.add_file_attachment(entry)
            size_kb = int(int(entry.get("bytes", 0) or 0) // 1024)
            truncated = bool(entry.get("truncated", False))
            suffix = " (truncated)" if truncated else ""
            self.report(
                {"INFO"},
                f"Attached '{entry.get('name', 'file')}' ({size_kb}KB, {queue_size} pending){suffix}.",
            )
            _trigger_redraw()
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Attach file failed: {exc}")
            return {"CANCELLED"}


class CHAT_OT_SetupWorkspace(bpy.types.Operator):
    bl_idname = "chat.setup_workspace"
    bl_label = "Open GN Workspace"
    bl_description = "Create a workspace with NODE_EDITOR + VIEW_3D for GN editing"

    def execute(self, context):
        ws_name = "GN Chat"
        existing = bpy.data.workspaces.get(ws_name)
        if existing:
            context.window.workspace = existing
            self.report({"INFO"}, "Switched to GN Chat workspace.")
            return {"FINISHED"}

        bpy.ops.workspace.duplicate()
        ws = context.window.workspace
        ws.name = ws_name
        screen = context.screen
        view3d = next((a for a in screen.areas if a.type == "VIEW_3D"), None)
        if view3d is None:
            self.report({"WARNING"}, "No VIEW_3D area found to split.")
            return {"FINISHED"}

        area_count_before = len(screen.areas)
        with context.temp_override(window=context.window, screen=screen, area=view3d):
            bpy.ops.screen.area_split(direction="HORIZONTAL", factor=0.45)

        if len(screen.areas) > area_count_before:
            view3d.type = "NODE_EDITOR"
            space = view3d.spaces.active
            if hasattr(space, "tree_type"):
                space.tree_type = "GeometryNodeTree"
            gn_groups = [ng for ng in bpy.data.node_groups if ng.bl_idname == "GeometryNodeTree"]
            if gn_groups and hasattr(space, "node_tree"):
                space.node_tree = gn_groups[0]

        self.report({"INFO"}, "GN Chat workspace ready. Press N in the viewport to open the chat panel.")
        return {"FINISHED"}


class CHAT_OT_OpenJournalFolder(bpy.types.Operator):
    bl_idname = "chat.open_journal_folder"
    bl_label = "Open Journal Folder"
    bl_description = "Open runtime journal folder in file explorer"

    def execute(self, context):
        try:
            runtime = _get_runtime()
            folder = runtime.journal.base_dir
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(str(folder))  # type: ignore[attr-defined]
            self.report({"INFO"}, f"Opened: {folder}")
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Open folder failed: {exc}")
            return {"CANCELLED"}


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Work-cycle operators
# ---------------------------------------------------------------------------



CHAT_OPERATOR_CLASSES = (
    CHAT_OT_SendMessage,
    CHAT_OT_SendClipboard,
    CHAT_OT_OpenPromptBuffer,
    CHAT_OT_SendPromptBuffer,
    CHAT_OT_LoadClipboardToPromptBuffer,
    CHAT_OT_ClearHistory,
    CHAT_OT_ShowMoreMessages,
    CHAT_OT_CollapseMessages,
    CHAT_OT_CopyMessage,
    CHAT_OT_CopyReasoning,
    CHAT_OT_InstallSdk,
    CHAT_OT_AttachFile,
    CHAT_OT_SetupWorkspace,
    CHAT_OT_OpenJournalFolder,
)
