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
from bpy.props import BoolProperty, IntProperty, PointerProperty, StringProperty
from bpy_extras.io_utils import ImportHelper

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
# SDK path injection
# ---------------------------------------------------------------------------

def _ensure_sdk_path() -> None:
    candidates = []
    try:
        if hasattr(site, "getusersitepackages"):
            user_site = site.getusersitepackages()
            if isinstance(user_site, str):
                candidates.append(user_site)
            else:
                candidates.extend(user_site)
    except Exception:
        pass
    for path in candidates:
        if path and path not in sys.path:
            sys.path.insert(0, path)


_ensure_sdk_path()


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_DEFAULT_VISIBLE_MESSAGES = 6
_VISIBLE_MESSAGES_STEP = 6
_STREAM_PREVIEW_LINES = 12
_PROMPT_BUFFER_NAME = "GN Chat Prompt"

_MAIN_THREAD_ID = threading.get_ident()
_redraw_pending = False
_runtime_poll_registered = False
_session_cache: dict[str, object] = {"ts": 0.0, "blend_path": "", "state": None}

_runtime: AgentRuntime | None = None
_project_root_update_in_progress = False

# Onda 5: combined "send + revert" deferred reopen.
# After BLEND_OT_send_and_revert copies the snapshot to disk, the actual
# bpy.ops.wm.open_mainfile is deferred until the agent background thread
# finishes — so the user sees the agent's discussion response BEFORE Blender
# reloads.  Set to the blend file path when a deferred reopen is pending.
_deferred_reopen_path: str | None = None
_deferred_reopen_snapshot_path: str | None = None
_deferred_reopen_min_messages: int = 0
_last_chat_turn_failed: bool = False

# Gates live disk-hydration of the SESSION visible-message list when there is
# no persisted history for the current file yet. Starts False after Blender
# start / file open so empty sessions do not immediately ghost old data into
# the panel. If the current V1 session already has persisted history, the
# panel may still auto-hydrate it on draw without waiting for a new prompt.
#
# Why this is needed:
#   _on_blend_load_post clears SESSION, but the very next draw cycle calls
#   _sync_ui_messages_from_session. For brand-new sessions with no persisted
#   history yet, reloading immediately would just undo the clear in < 1 frame.
#   The flag breaks that cycle while still allowing real persisted V1 history
#   for the currently opened file to reappear automatically.
_history_hydration_enabled: bool = False


# ---------------------------------------------------------------------------
# Runtime singleton
# ---------------------------------------------------------------------------

def _get_addon_preferences():
    for addon_id in ("blender_addon", "orthosis_mcp_bridge"):
        addon = bpy.context.preferences.addons.get(addon_id)
        if addon and hasattr(addon, "preferences"):
            return addon.preferences
    return None


def _get_api_key() -> str:
    prefs = _get_addon_preferences()
    if prefs is not None:
        return getattr(prefs, "claude_api_key", "")
    return ""


def _get_model() -> str:
    prefs = _get_addon_preferences()
    if prefs is not None:
        return getattr(prefs, "claude_model", "claude-sonnet-4-6")
    return "claude-sonnet-4-6"


def _get_runtime() -> AgentRuntime:
    global _runtime
    if _runtime is None:
        api_key = _get_api_key()
        model = _get_model()
        project_root = str(resolve_project_root())
            # __file__ = .../blender_addon/ui/panel.py → parent.parent = project root
        _runtime = AgentRuntime(
            project_root=project_root,
            api_key=api_key,
            model=model,
        )
    return _runtime


def _reset_runtime() -> None:
    global _runtime
    _runtime = None


def _invalidate_runtime_binding(*, clear_messages: bool = False) -> None:
    global _history_hydration_enabled
    _reset_runtime()
    _session_cache["ts"] = 0.0
    _session_cache["blend_path"] = ""
    _session_cache["state"] = None
    if clear_messages:
        SESSION.clear()
    _history_hydration_enabled = True
    _schedule_redraw()


def _refresh_server_runtime_binding() -> None:
    try:
        from .. import server as _server_module

        _server_module.refresh_runtime_project_root()
    except Exception:
        pass


def _on_project_root_path_updated(self, context) -> None:
    global _project_root_update_in_progress
    if _project_root_update_in_progress:
        return

    raw_value = str(getattr(self, "project_root_path", "") or "").strip()
    normalized = raw_value
    if raw_value:
        try:
            normalized = str(Path(raw_value).expanduser().resolve())
        except Exception:
            normalized = raw_value
        if normalized != raw_value:
            try:
                _project_root_update_in_progress = True
                setattr(self, "project_root_path", normalized)
            finally:
                _project_root_update_in_progress = False
    _refresh_server_runtime_binding()
    _invalidate_runtime_binding(clear_messages=True)


def _get_bridge_endpoint() -> tuple[str, int]:
    try:
        from ..server import DEFAULT_HOST, DEFAULT_PORT
        return str(DEFAULT_HOST), int(DEFAULT_PORT)
    except Exception:
        return "localhost", 65432


# ---------------------------------------------------------------------------
# Redraw helpers
# ---------------------------------------------------------------------------

def _trigger_redraw() -> None:
    global _redraw_pending
    _redraw_pending = False
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type in ("VIEW_3D", "NODE_EDITOR"):
                    area.tag_redraw()
    except Exception:
        pass


def _schedule_redraw() -> None:
    global _redraw_pending
    _redraw_pending = True
    if threading.get_ident() != _MAIN_THREAD_ID:
        return
    try:
        if not bpy.app.timers.is_registered(_trigger_redraw):
            bpy.app.timers.register(_trigger_redraw, first_interval=0.05)
    except Exception:
        pass


def _deferred_reopen_ready() -> bool:
    if not _deferred_reopen_path or not _deferred_reopen_snapshot_path or SESSION.running:
        return False
    if _last_chat_turn_failed:
        return False
    messages = SESSION.get_messages()
    if len(messages) < _deferred_reopen_min_messages:
        return False
    if not messages:
        return False
    return str(messages[-1].get("role", "") or "").strip().lower() == "assistant"


def _poll_runtime_redraw() -> float:
    global _deferred_reopen_min_messages, _deferred_reopen_path, _deferred_reopen_snapshot_path
    if _deferred_reopen_path and not SESSION.running and _last_chat_turn_failed:
        _deferred_reopen_path = None
        _deferred_reopen_snapshot_path = None
        _deferred_reopen_min_messages = 0
        _set_work_cycle_phase("awaiting_feedback")
        _trigger_redraw()
        return 0.75
    # Deferred reopen: fire once the agent background turn has finished so the
    # user sees the discussion response before Blender reloads.
    if _deferred_reopen_ready():
        path = _deferred_reopen_path
        snapshot_path = _deferred_reopen_snapshot_path
        _deferred_reopen_path = None
        _deferred_reopen_snapshot_path = None
        _deferred_reopen_min_messages = 0
        try:
            import shutil as _shutil
            import bpy as _bpy  # already imported at module level; alias for clarity
            _set_work_cycle_phase("idle")
            _shutil.copy2(snapshot_path, path)
            _bpy.ops.wm.open_mainfile(filepath=path)
        except Exception:
            pass
        return 0.2  # timer will be killed by file reload anyway
    if _redraw_pending or SESSION.running or SESSION.screenshot_running or _deferred_reopen_path:
        _trigger_redraw()
        return 0.2
    return 0.75


def _message_wrap_width(context, *, chrome_px: int = 72) -> int:
    region = getattr(context, "region", None)
    region_width = int(getattr(region, "width", 0) or 0)
    return _estimate_wrap_width(region_width, chrome_px=chrome_px)


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def _get_runtime_ui_state(scene) -> dict:
    """Compact runtime snapshot for panel rendering."""
    _ = scene
    runtime = _get_runtime()
    blend_path = _get_effective_blend_path()
    session = _load_local_runtime_session(blend_path)
    journal_paths = runtime.journal.get_paths()
    session_id = str(session.get("session_id", "n/a") or "n/a")
    journal_base_dir = str(journal_paths.get("base_dir", "") or "")
    journal_session_file = str(journal_paths.get("session_file", "") or "")
    execution_phase = str(session.get("execution_phase", "") or "")
    chat_history = session.get("chat_history", []) if isinstance(session.get("chat_history"), list) else []

    return {
        "project_root": str(session.get("_runtime_project_root", runtime.project_root)),
        "session_id": session_id,
        "agent_session_active": bool(session.get("agent_session_active", False)),
        "session_resumed_notice": str(session.get("session_resumed_notice", "") or ""),
        "session_state": str(session.get("session_state", "no_session") or "no_session"),
        "debug_mode": bool(session.get("debug_mode", False)),
        "explicit_override_mode": bool(session.get("explicit_override_mode", False)),
        "mcp_write_enabled": bool(session.get("mcp_write_enabled", False)),
        "drafting_mode": bool(session.get("drafting_mode", False)),
        "simulate_bridge_failure": bool(session.get("simulate_bridge_failure", False)),
        "turn_counter": int(session.get("turn_counter", 0) or 0),
        "last_failure": str(session.get("last_failure", "") or ""),
        "task_class": str(session.get("last_task_class", "")),
        "target_tree": str(session.get("last_target_tree", "")),
        "last_action": {},
        "turn_tools": [],
        "journal_base_dir": journal_base_dir,
        "journal_session_file": journal_session_file,
        "chat_history": chat_history,
        "execution_phase": execution_phase,
        # Onda 5 (Item 5.4): work cycle state — must be forwarded from session
        "work_cycle_phase": str(session.get("work_cycle_phase", "idle") or "idle"),
        "current_revision": int(session.get("current_revision", 0) or 0),
        "draft_revision_count": int(session.get("draft_revision_count", 0) or 0),
    }


def _get_execution_phase(runtime: AgentRuntime, blend_path: str) -> str:
    """Read execution_state.phase from the V1 structured session if available."""
    return _get_execution_phase_helper(str(runtime.project_root), blend_path)


def _simple_session_state(runtime_info: dict) -> str:
    declared = str(runtime_info.get("session_state", "") or "").strip()
    if declared in {"no_session", "active", "paused"}:
        return declared
    active = bool(runtime_info.get("agent_session_active", False))
    if not active:
        return "no_session"
    if SESSION.running:
        return "active"
    if int(runtime_info.get("turn_counter", 0) or 0) <= 0:
        return "active"
    return "paused"



def _sync_ui_messages_from_session(runtime_info: dict) -> None:
    session_id = str(runtime_info.get("session_id", "") or "")
    history = runtime_info.get("chat_history", [])
    if not isinstance(history, list):
        history = []

    if session_id and session_id != SESSION.loaded_session_id:
        SESSION.update_session_id(session_id)

    if not _history_hydration_enabled and not history:
        return

    current_messages = SESSION.get_messages()
    should_reload = (
        (not current_messages and history)
        or (len(history) > len(current_messages))
    )
    if should_reload:
        SESSION.replace_messages(history, session_id=session_id)
        # DIAG: also log to journal so it's captured in the JSONL even without console
        try:
            _rt = _get_runtime()
            _rt.journal.log_runtime_event(
                event_type="ui_history_hydration_trace",
                payload={
                    "blend_path": runtime_info.get("_runtime_project_root", "?"),
                    "session_id": session_id,
                    "session_focus_blend_path": runtime_info.get("_session_focus_blend_path", "?"),
                    "msg_count_loaded": len(SESSION.get_messages()),
                    "history_source": runtime_info.get("_history_source", "unknown"),
                    "hydration_enabled": _history_hydration_enabled,
                    "first_msg": history[0].get("text", "")[:120] if history else "",
                    "last_msg": history[-1].get("text", "")[:120] if history else "",
                },
            )
        except Exception:
            pass


def _cache_runtime_session_state(blend_path: str, state: dict, *, timestamp: float | None = None) -> None:
    now = time.time() if timestamp is None else timestamp
    _session_cache["ts"] = now
    _session_cache["blend_path"] = blend_path
    _session_cache["state"] = dict(state)



def _load_local_runtime_session(blend_path: str = "") -> dict:
    import traceback as _tb
    runtime = _get_runtime()
    try:
        session = runtime.runtime.v1_session_for(blend_path)
    except Exception:
        import sys
        print(f"[panel._load_local] v1_session_for EXCEPTION:\n{_tb.format_exc()}", file=sys.stderr, flush=True)
        return {}
    ui_state = getattr(session, "ui_state", None)
    identity = getattr(session, "identity", None)
    focus = getattr(session, "focus", None)
    execution_state = getattr(session, "execution_state", None)
    history = getattr(session, "history", None)

    chat_history: list[dict[str, str]] = []
    raw_messages = getattr(history, "messages", []) if history is not None else []
    for item in raw_messages:
        role = str(getattr(item, "role", "") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        text = str(getattr(item, "content", "") or "")
        if not text.strip():
            continue
        chat_history.append({"role": role, "text": text})

    last_failure = getattr(execution_state, "last_failure", None)
    last_failure_text = str(getattr(last_failure, "error", "") or "").strip()
    session_active = bool(getattr(ui_state, "session_active", False))
    focus_bp = str(getattr(focus, "blend_path", "") or "")

    return {
        "_runtime_project_root": str(runtime.project_root),
        "_session_focus_blend_path": focus_bp,
        "session_id": str(getattr(identity, "session_id", "") or ""),
        "agent_session_active": session_active,
        "session_resumed_notice": "",
        "session_state": "active" if session_active else "no_session",
        "debug_mode": bool(getattr(ui_state, "debug_mode", False)),
        "explicit_override_mode": bool(getattr(ui_state, "explicit_override_mode", False)),
        "mcp_write_enabled": bool(getattr(ui_state, "mcp_write_enabled", False)),
        "turn_counter": len(chat_history),
        "last_failure": last_failure_text,
        "last_task_class": "",
        "last_target_tree": str(getattr(focus, "tree_name", "") or ""),
        "chat_history": chat_history,
        "execution_phase": str(getattr(execution_state, "phase", "") or ""),
        "drafting_mode": bool(getattr(execution_state, "drafting_mode", False)),
        "simulate_bridge_failure": bool(getattr(ui_state, "simulate_bridge_failure", False)),
        # Onda 5 (Item 5.4)
        "work_cycle_phase": str(getattr(execution_state, "work_cycle_phase", "idle") or "idle"),
        "current_revision": int(getattr(execution_state, "draft_revision", 0) or 0),
        "draft_revision_count": len(getattr(execution_state, "draft_revisions", []) or []),
    }


def _runtime_set_modes(
    *,
    blend_path: str = "",
    debug_mode: bool | None = None,
    explicit_override_mode: bool | None = None,
    mcp_write_enabled: bool | None = None,
    agent_session_active: bool | None = None,
    drafting_mode: bool | None = None,
    simulate_bridge_failure: bool | None = None,
    reset_session_memory: bool = False,
    start_new_session: bool = False,
    reset_transient_state: bool = False,
    claim_control_owner: bool = False,
    force_control_owner: bool = False,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": "runtime_set_modes",
        "blend_path": blend_path,
        "control_source": "chat_ui",
        "claim_control_owner": bool(claim_control_owner),
        "force_control_owner": bool(force_control_owner),
        "reset_session_memory": bool(reset_session_memory),
        "start_new_session": bool(start_new_session),
        "reset_transient_state": bool(reset_transient_state),
    }
    if debug_mode is not None:
        payload["debug_mode"] = bool(debug_mode)
    if explicit_override_mode is not None:
        payload["explicit_override_mode"] = bool(explicit_override_mode)
    if mcp_write_enabled is not None:
        payload["mcp_write_enabled"] = bool(mcp_write_enabled)
    if agent_session_active is not None:
        payload["agent_session_active"] = bool(agent_session_active)
    if drafting_mode is not None:
        payload["drafting_mode"] = bool(drafting_mode)
    if simulate_bridge_failure is not None:
        payload["simulate_bridge_failure"] = bool(simulate_bridge_failure)
    response = call_blender_socket(payload, timeout=4.0)
    if simulate_bridge_failure is not None:
        try:
            local_runtime = _get_runtime()
            local_state = local_runtime.runtime.set_modes(
                blend_path=blend_path,
                simulate_bridge_failure=bool(simulate_bridge_failure),
                control_source="chat_ui_local",
            )
            if isinstance(local_state, dict):
                response.setdefault("result", {}).update(
                    {"simulate_bridge_failure": bool(local_state.get("simulate_bridge_failure", False))}
                )
        except Exception:
            pass
    if response.get("status") in {"success", "blocked"} and isinstance(response.get("result"), dict):
        _cache_runtime_session_state(blend_path, response["result"])
    else:
        _session_cache["ts"] = 0.0
        _session_cache["blend_path"] = ""
        _session_cache["state"] = None
    return response


def _sync_scene_controls_from_runtime(scene, runtime_info: dict) -> None:
    try:
        scene.chat_debug_mode = bool(runtime_info.get("debug_mode", False))
        scene.chat_explicit_override_mode = bool(runtime_info.get("explicit_override_mode", False))
        scene.chat_mcp_write_enabled = bool(runtime_info.get("mcp_write_enabled", False))
        scene.chat_drafting_mode = bool(runtime_info.get("drafting_mode", False))
        scene.chat_simulate_bridge_failure = bool(runtime_info.get("simulate_bridge_failure", False))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Text / file helpers
# ---------------------------------------------------------------------------

_TEXT_ATTACHMENT_EXTENSIONS = {".json", ".txt", ".md", ".py", ".log", ".yaml", ".yml", ".csv"}
_MAX_ATTACHMENT_BYTES = 1024 * 1024
_MAX_ATTACHMENT_CHARS = 120_000


def _read_text_attachment(filepath: str) -> dict[str, str | int | bool]:
    path = Path(filepath)
    if not path.exists() or not path.is_file():
        raise RuntimeError("Selected file does not exist.")
    ext = path.suffix.lower()
    if ext not in _TEXT_ATTACHMENT_EXTENSIONS:
        supported = ", ".join(sorted(_TEXT_ATTACHMENT_EXTENSIONS))
        raise RuntimeError(f"Unsupported file type '{ext or '[none]'}'. Supported: {supported}")

    raw = path.read_bytes()
    original_bytes = len(raw)
    truncated = False
    if len(raw) > _MAX_ATTACHMENT_BYTES:
        raw = raw[:_MAX_ATTACHMENT_BYTES]
        truncated = True

    text: str | None = None
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except Exception:
            continue
    if text is None:
        raise RuntimeError("Could not decode file as text.")

    normalized = _normalize_multiline_text(text).strip()
    if len(normalized) > _MAX_ATTACHMENT_CHARS:
        normalized = normalized[:_MAX_ATTACHMENT_CHARS].rstrip() + "\n...[file truncated]"
        truncated = True
    if not normalized:
        raise RuntimeError("Selected file is empty.")

    return {
        "path": str(path),
        "name": path.name,
        "extension": ext,
        "text": normalized,
        "bytes": original_bytes,
        "truncated": truncated,
    }


def _build_file_context_blocks(file_attachments: list[dict[str, str | int | bool]]) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    for item in file_attachments:
        name = str(item.get("name", "") or "attachment")
        ext = str(item.get("extension", "") or "")
        path = str(item.get("path", "") or "")
        truncated = bool(item.get("truncated", False))
        text = str(item.get("text", "") or "").strip()
        if not text:
            continue
        header = f"[Attached File]\nName: {name}\nType: {ext or 'text'}\nPath: {path}"
        if truncated:
            header += "\nNote: file content was truncated before sending."
        blocks.append({"type": "text", "text": header + "\n\n" + text})
    return blocks


# ---------------------------------------------------------------------------
# Prompt buffer helpers
# ---------------------------------------------------------------------------

def _get_prompt_buffer(scene: bpy.types.Scene | None = None, *, create: bool = True) -> bpy.types.Text | None:
    text_block = None
    if scene is not None:
        candidate = getattr(scene, "chat_prompt_buffer", None)
        if candidate is not None and getattr(candidate, "name", "") in bpy.data.texts:
            text_block = candidate
    if text_block is None:
        text_block = bpy.data.texts.get(_PROMPT_BUFFER_NAME)
    if text_block is None and create:
        text_block = bpy.data.texts.new(_PROMPT_BUFFER_NAME)
    if text_block is not None and scene is not None:
        try:
            scene.chat_prompt_buffer = text_block
        except Exception:
            pass
    return text_block


def _replace_text_block_contents(text_block: bpy.types.Text, value: str) -> None:
    normalized = _normalize_multiline_text(value)
    text_block.clear()
    if normalized:
        text_block.write(normalized)


def _seed_prompt_buffer_from_input(scene: bpy.types.Scene, text_block: bpy.types.Text) -> None:
    buffer_text = _normalize_multiline_text(text_block.as_string())
    input_text = _normalize_multiline_text(getattr(scene, "chat_input", "") or "")
    if input_text.strip() and not buffer_text.strip():
        _replace_text_block_contents(text_block, input_text)


def _find_text_editor_area(screen: bpy.types.Screen) -> bpy.types.Area | None:
    for area in screen.areas:
        if area.type == "TEXT_EDITOR":
            return area
    return None


def _preferred_split_area(screen: bpy.types.Screen, fallback: bpy.types.Area | None) -> bpy.types.Area | None:
    preferred_types = {"NODE_EDITOR", "VIEW_3D"}
    candidates = [area for area in screen.areas if area.type in preferred_types]
    if candidates:
        return max(candidates, key=lambda area: area.width * area.height)
    return fallback


def _open_text_block_in_workspace(context, text_block: bpy.types.Text) -> bool:
    screen = context.window.screen
    area = _find_text_editor_area(screen)
    if area is None:
        split_source = _preferred_split_area(screen, context.area)
        if split_source is None:
            return False
        area_ids_before = {candidate.as_pointer() for candidate in screen.areas}
        with context.temp_override(window=context.window, screen=screen, area=split_source):
            bpy.ops.screen.area_split(direction="VERTICAL", factor=0.72)
        new_areas = [candidate for candidate in screen.areas if candidate.as_pointer() not in area_ids_before]
        if new_areas:
            area = max(new_areas, key=lambda candidate: candidate.width * candidate.height)
            area.type = "TEXT_EDITOR"
        else:
            area = _find_text_editor_area(screen)
    if area is None or area.type != "TEXT_EDITOR":
        return False
    space = area.spaces.active
    space.text = text_block
    if hasattr(space, "show_word_wrap"):
        space.show_word_wrap = True
    if hasattr(space, "show_line_numbers"):
        space.show_line_numbers = True
    return True


def _open_prompt_buffer_in_workspace(context, text_block: bpy.types.Text) -> bool:
    return _open_text_block_in_workspace(context, text_block)


def _draft_block_name_from_session() -> str:
    try:
        info = _get_work_cycle_info()
        blend_path = str(info.get("blend_path", "") or "")
        rt = _get_runtime()
        session = rt.runtime.v1_session_for(blend_path)
        es = getattr(session, "execution_state", None)
        draft = getattr(es, "current_draft", None) if es is not None else None
        return str(
            getattr(draft, "block_name", "")
            or getattr(es, "draft_block_name", "")
            or "GN_Agent_Draft"
        )
    except Exception:
        return "GN_Agent_Draft"


def _open_current_draft_in_workspace(context) -> tuple[bool, str]:
    block_name = _draft_block_name_from_session()
    text_block = bpy.data.texts.get(block_name)
    if text_block is None:
        return False, f"Draft '{block_name}' nao existe no Text Editor."
    if not _open_text_block_in_workspace(context, text_block):
        return False, f"Draft '{block_name}' existe, mas nao consegui abrir um Text Editor automaticamente."
    return True, block_name


def _draft_tree_name_from_text_block(text_block: bpy.types.Text | None) -> str:
    if text_block is None:
        return ""
    try:
        prop_value = str(text_block.get("_draft_tree_name", "") or "").strip()
        if prop_value:
            return prop_value
    except Exception:
        pass
    try:
        content = text_block.as_string()
    except Exception:
        content = ""
    match = re.search(
        r"node_groups\.(?:get\(\s*|\[\s*)[\"']([^\"']+)[\"']",
        str(content or ""),
    )
    return match.group(1).strip() if match else ""


def _tree_node_count(tree_name: str) -> int | None:
    if not tree_name:
        return None
    tree = bpy.data.node_groups.get(tree_name)
    if tree is None:
        return None
    try:
        return len(tree.nodes)
    except Exception:
        return None


def _run_current_draft_text(context) -> tuple[bool, str]:
    opened, detail = _open_current_draft_in_workspace(context)
    if not opened:
        return False, detail

    text_block = bpy.data.texts.get(detail)
    tree_name = _draft_tree_name_from_text_block(text_block)
    node_count_before = _tree_node_count(tree_name)

    try:
        code = text_block.as_string() if text_block is not None else ""
    except Exception:
        code = ""
    if not code.strip():
        return False, f"Draft '{detail}' esta vazio."
    stdout = StringIO()
    try:
        globals_dict = {
            "__name__": "__main__",
            "__file__": f"<Blender Text:{detail}>",
            "bpy": bpy,
        }
        with redirect_stdout(stdout):
            exec(compile(code, f"<Blender Text:{detail}>", "exec"), globals_dict, globals_dict)
    except Exception as exc:
        tb_tail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        return False, f"Erro ao rodar '{detail}': {tb_tail}"
    node_count_after = _tree_node_count(tree_name)
    output = stdout.getvalue().strip()
    output_hint = f" | print: {output[:160]}" if output else ""
    if tree_name and node_count_before is not None and node_count_after is not None:
        delta = node_count_after - node_count_before
        return True, f"{detail} em '{tree_name}' (nos: {node_count_before} -> {node_count_after}, delta {delta:+d}){output_hint}"
    if tree_name:
        return True, f"{detail} em '{tree_name}'{output_hint}"
    return True, f"{detail}{output_hint}"


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

# Item 5.1: fallback labels used when runtime._current_tool_status is not set.
_STATUS_MESSAGES = {
    "get_node_context": "Lendo contexto do nó...",
    "get_selected_nodes_context": "Lendo nós selecionados...",
    "get_active_frame_context": "Lendo frame ativo...",
    "get_local_subgraph_context": "Lendo subgrafo...",
    "get_scene_summary": "Lendo cena...",
    "get_gn_hosts": "Listando objetos GN...",
    "get_tree_parameters": "Lendo parâmetros da árvore...",
    "get_changes_since_last_turn": "Verificando mudanças...",
    "find_tree_nodes": "Buscando nós...",
    "list_tree_nodes": "Listando nós...",
    "resolve_gn_workspace": "Resolvendo workspace GN...",
    "build_tree_structural_memory": "Lendo árvore GN...",
    "read_script_draft": "Lendo draft...",
    "write_script_draft": "Escrevendo draft...",
    "prepare_draft_context": "Preparando contexto de draft...",
    "classify_tree_phases": "Classificando fases da árvore...",
    "map_clinical_parameter_roles": "Mapeando parâmetros clínicos...",
    "interpret_orthosis_tree_logic": "Interpretando lógica da órtese...",
    "analyze_gn_state": "Analisando estado GN...",
    "analyze_scene": "Analisando cena...",
    "capture_screenshot": "Capturando viewport...",
    "query_node_types": "Consultando tipos de nó...",
}


def _run_chat_turn(
    user_text: str,
    api_key: str,
    model: str,
    blend_path: str = "",
    screenshot_pngs: list[bytes] | None = None,
    file_context_blocks: list[dict[str, str]] | None = None,
) -> None:
    """Run in a background thread.  Calls AgentRuntime.run_turn()."""
    global _last_chat_turn_failed
    try:
        import anthropic as _anthropic
        runtime = _runtime
        if runtime is None:
            raise RuntimeError("Runtime not initialized on main thread.")
        runtime.client = _anthropic.Anthropic(api_key=api_key)
        runtime.model = model

        def _on_tool_call(tool_name: str, step: int) -> None:
            # Prefer the Portuguese status set by core.agent_loop (includes round
            # info); fall back to _STATUS_MESSAGES for callers that bypass the loop.
            status = getattr(runtime, "_current_tool_status", "") or ""
            if not status:
                status = _STATUS_MESSAGES.get(tool_name, f"{tool_name}...")
            with SESSION._lock:
                SESSION.current_tool = status
                SESSION.tool_call_count = step
            _schedule_redraw()

        def _on_text_chunk(chunk: str) -> None:
            SESSION.append_stream_chunk(chunk)
            _schedule_redraw()

        runtime.on_tool_call = _on_tool_call
        runtime.on_text_chunk = _on_text_chunk

        with SESSION._lock:
            SESSION.current_tool = "Starting..."
        _schedule_redraw()

        image_blocks = None
        if screenshot_pngs:
            import base64
            image_blocks = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.b64encode(png).decode("ascii"),
                    },
                }
                for png in screenshot_pngs
            ]

        response_text = runtime.run_turn(
            user_text,
            blend_path=blend_path,
            image_blocks=image_blocks,
            attachment_text_blocks=file_context_blocks,
        )

        SESSION.current_tool = ""
        SESSION.streaming_text = ""
        SESSION.error = ""
        SESSION.add("assistant", response_text)
        _last_chat_turn_failed = False
        try:
            in_tok, out_tok = runtime.journal.get_last_turn_tokens()
            with SESSION._lock:
                SESSION.last_turn_input_tokens = in_tok
                SESSION.last_turn_output_tokens = out_tok
                SESSION.session_input_tokens += in_tok
                SESSION.session_output_tokens += out_tok
        except Exception:
            pass
        SESSION.running = False
        _schedule_redraw()

    except Exception as exc:
        SESSION.current_tool = ""
        SESSION.streaming_text = ""
        SESSION.error = str(exc)
        SESSION.add("assistant", f"[Error] {exc}")
        _last_chat_turn_failed = True
        SESSION.running = False
        _schedule_redraw()


def _send_user_message(context, user_text: str, *, display_text: str | None = None) -> tuple[set[str], str]:
    global _history_hydration_enabled, _last_chat_turn_failed

    scene = context.scene
    text = str(user_text or "")
    if not text.strip():
        return {"CANCELLED"}, "Empty message."

    api_key = _get_api_key()
    if not api_key:
        return {"CANCELLED"}, "No API key. Set it in Edit > Preferences > Add-ons > Orthosis AI Agent."

    if SESSION.running:
        return {"CANCELLED"}, "Already processing a message."

    # Enable disk-history hydration from this point forward.  The panel starts
    # with hydration disabled so no ghost history appears on open; enabling it
    # here means the UI will start syncing new messages from the store as turns
    # complete and the legacy state is written back to disk.
    _history_hydration_enabled = True

    blend_path = _get_effective_blend_path()

    if SESSION.screenshot_running:
        return {"CANCELLED"}, "Wait for screenshot capture to finish before sending."

    screenshot_pngs = SESSION.consume_screenshots()
    file_attachments = SESSION.consume_file_attachments()
    SESSION.set_screenshot_notice("")
    file_context_blocks = _build_file_context_blocks(file_attachments)

    show_text = display_text if isinstance(display_text, str) and display_text.strip() else text.strip()
    if screenshot_pngs:
        count = len(screenshot_pngs)
        suffix = "screenshot" if count == 1 else "screenshots"
        show_text += f"  [+ {count} {suffix}]"
    if file_attachments:
        count = len(file_attachments)
        suffix = "file" if count == 1 else "files"
        show_text += f"  [+ {count} {suffix}]"

    SESSION.add("user", show_text)
    SESSION.running = True
    _last_chat_turn_failed = False
    SESSION.reset_turn()
    scene.chat_input = ""

    model = _get_model()
    thread = threading.Thread(
        target=_run_chat_turn,
        args=(text, api_key, model, blend_path, screenshot_pngs, file_context_blocks),
        daemon=True,
    )
    thread.start()
    return {"FINISHED"}, ""


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

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
# Onda 5 (Item 5.4): work-cycle transition helpers
# ---------------------------------------------------------------------------

def _set_work_cycle_phase(phase: str) -> None:
    """Set work_cycle_phase in the V1 session. Called from main-thread operators."""
    try:
        rt = _get_runtime()
        blend_path = _get_effective_blend_path()
        rt.runtime.set_work_cycle_phase(blend_path, phase)
    except Exception:
        pass


def _get_work_cycle_info() -> dict:
    """Return (session_id, blend_path, current_revision) for snapshot calls."""
    try:
        blend_path = _get_effective_blend_path()
        rt = _get_runtime()
        session = rt.runtime.v1_session_for(blend_path)
        session_id = str(getattr(getattr(session, "identity", None), "session_id", "") or "")
        revision = int(getattr(getattr(session, "execution_state", None), "draft_revision", 0) or 0)
        return {"blend_path": blend_path, "session_id": session_id, "revision": revision}
    except Exception:
        return {"blend_path": "", "session_id": "", "revision": 0}


class BLEND_OT_execute_draft(bpy.types.Operator):
    bl_idname = "blend.execute_draft"
    bl_label = "Abrir para executar"
    bl_description = "Abre o draft no Text Editor, cria snapshot de seguranca e avanca para estado de execucao"

    def execute(self, context):
        info = _get_work_cycle_info()
        blend_path = info["blend_path"]
        session_id = info["session_id"]
        revision = info["revision"]

        opened, detail = _open_current_draft_in_workspace(context)
        if not opened:
            self.report({"ERROR"}, detail)
            return {"CANCELLED"}

        # Call snapshot_manager directly — operators run on the main thread so
        # bpy.ops.wm.save_as_mainfile is safe to call here without a socket round-trip.
        if session_id and blend_path:
            try:
                from ..snapshot_manager import take_snapshot
                project_root = _get_runtime().project_root
                snap_path = take_snapshot(
                    blend_path=blend_path,
                    session_id=session_id,
                    revision=revision,
                    project_root=project_root,
                )
                self.report({"INFO"}, f"Snapshot salvo: {snap_path}")
            except Exception as exc:
                self.report({"WARNING"}, f"Snapshot falhou (continuando): {exc}")

        _set_work_cycle_phase("executing")
        _schedule_redraw()
        self.report({"INFO"}, f"Draft aberto: {detail}. Clique Run Script/Alt+P e depois 'Reportar resultado'.")
        return {"FINISHED"}


class BLEND_OT_open_draft(bpy.types.Operator):
    bl_idname = "blend.open_draft"
    bl_label = "Abrir Draft"
    bl_description = "Abre o Text Editor com o draft atual sem mudar o estado do ciclo"

    def execute(self, context):
        opened, detail = _open_current_draft_in_workspace(context)
        if not opened:
            self.report({"ERROR"}, detail)
            return {"CANCELLED"}
        self.report({"INFO"}, f"Draft aberto: {detail}")
        _schedule_redraw()
        return {"FINISHED"}


class BLEND_OT_run_draft(bpy.types.Operator):
    bl_idname = "blend.run_draft"
    bl_label = "Rodar Draft"
    bl_description = "Executa manualmente o draft atual no Text Editor"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        ok, detail = _run_current_draft_text(context)
        _set_work_cycle_phase("awaiting_feedback")
        try:
            context.scene.chat_result_failed_mode = False
            context.scene.chat_result_description = ""
        except Exception:
            pass
        if not ok:
            try:
                context.scene.chat_result_failed_mode = True
                context.scene.chat_result_description = detail
            except Exception:
                pass
            self.report({"ERROR"}, detail)
            _schedule_redraw()
            return {"CANCELLED"}
        self.report({"INFO"}, f"Draft executado: {detail}. Reporte o resultado visual.")
        _schedule_redraw()
        return {"FINISHED"}


class BLEND_OT_discard_draft(bpy.types.Operator):
    bl_idname = "blend.discard_draft"
    bl_label = "Descartar"
    bl_description = "Descarta o draft e volta ao estado de conversa"

    def execute(self, context):
        _set_work_cycle_phase("idle")
        _schedule_redraw()
        return {"FINISHED"}


class BLEND_OT_report_result(bpy.types.Operator):
    bl_idname = "blend.report_result"
    bl_label = "Reportar resultado"
    bl_description = "Avança para estado de resultado — descreva o que aconteceu"

    def execute(self, context):
        _set_work_cycle_phase("awaiting_feedback")
        try:
            context.scene.chat_result_failed_mode = False
            context.scene.chat_result_description = ""
        except Exception:
            pass
        _schedule_redraw()
        return {"FINISHED"}


class BLEND_OT_result_success(bpy.types.Operator):
    bl_idname = "blend.result_success"
    bl_label = "Funcionou"
    bl_description = "Script executado com sucesso — volta ao estado de conversa"

    def execute(self, context):
        info = _get_work_cycle_info()
        revision = info["revision"]
        _set_work_cycle_phase("idle")
        # No agent call needed for success — just acknowledge in the UI and
        # return to idle so the user can continue with the next task.
        SESSION.add("assistant", f"✓ Script v{revision} aplicado com sucesso. Pode continuar.")
        _schedule_redraw()
        return {"FINISHED"}


class BLEND_OT_result_failed(bpy.types.Operator):
    bl_idname = "blend.result_failed"
    bl_label = "Nao funcionou"
    bl_description = "Mostra campo para descrever o que aconteceu"

    def execute(self, context):
        try:
            context.scene.chat_result_failed_mode = True
        except Exception:
            pass
        _schedule_redraw()
        return {"FINISHED"}


class BLEND_OT_send_result_report(bpy.types.Operator):
    bl_idname = "blend.send_result_report"
    bl_label = "Enviar relatorio"
    bl_description = "Envia o relatório de falha ao agente como EXECUTION_FEEDBACK"

    def execute(self, context):
        info = _get_work_cycle_info()
        revision = info["revision"]
        try:
            description = str(getattr(context.scene, "chat_result_description", "") or "").strip()
        except Exception:
            description = ""
        if not description:
            self.report({"WARNING"}, "Descreva o que aconteceu antes de enviar.")
            return {"CANCELLED"}

        structured = (
            f"[RESULTADO DE EXECUÇÃO — Revisão v{revision}]\n"
            f"Resultado: FALHOU\n"
            f"Descrição: {description}\n"
        )
        _set_work_cycle_phase("idle")
        try:
            context.scene.chat_result_failed_mode = False
            context.scene.chat_result_description = ""
        except Exception:
            pass
        result, error = _send_user_message(context, structured, display_text=f"[Resultado: falhou] {description}")
        if "CANCELLED" in result and error:
            self.report({"WARNING"}, error)
        _schedule_redraw()
        return {"FINISHED"}


class BLEND_OT_send_and_revert(bpy.types.Operator):
    """Envia o relatorio de falha ao agente E reverte o snapshot ao mesmo tempo."""
    bl_idname = "blend.send_and_revert"
    bl_label = "Enviar e Reverter"
    bl_description = (
        "Envia a descricao da falha ao agente para discussao E reverte o Blender "
        "para o estado anterior ao script — tudo em um passo"
    )

    def execute(self, context):
        global _deferred_reopen_min_messages, _deferred_reopen_path, _deferred_reopen_snapshot_path
        info = _get_work_cycle_info()
        revision = info["revision"]
        blend_path = info["blend_path"]
        session_id = info["session_id"]

        try:
            description = str(getattr(context.scene, "chat_result_description", "") or "").strip()
        except Exception:
            description = ""
        if not description:
            self.report({"WARNING"}, "Descreva o que aconteceu antes de enviar.")
            return {"CANCELLED"}

        # Step 1: send feedback to the agent (non-blocking). The snapshot is
        # restored only after a successful response so API/auth failures leave
        # the user's current Blender state and feedback form intact.
        structured = (
            f"[RESULTADO DE EXECUÇÃO — Revisão v{revision}]\n"
            f"Resultado: FALHOU\n"
            f"Descrição: {description}\n"
            f"Acao solicitada: apos a sua resposta, o Blender sera reaberto no snapshot anterior ao script.\n"
        )
        messages_before = len(SESSION.get_messages())
        result, error = _send_user_message(context, structured, display_text=f"[Falhou + Revertendo] {description}")
        if "CANCELLED" in result and error:
            self.report({"WARNING"}, f"Nao foi possivel enviar: {error}")
            return {"CANCELLED"}

        # Step 2: copy snapshot over the blend file NOW (disk state reverted
        # immediately), but defer the bpy.ops.wm.open_mainfile until the agent
        # background thread finishes — so the user sees the discussion response
        # before Blender reloads.
        if session_id and blend_path:
            try:
                from ..snapshot_manager import list_snapshots
                project_root = _get_runtime().project_root
                snapshots = list_snapshots(session_id=session_id, project_root=project_root)
                if snapshots:
                    latest = snapshots[0]["path"]
                    # Schedule the reopen for after the agent responds.
                    _deferred_reopen_path = blend_path
                    _deferred_reopen_snapshot_path = latest
                    _deferred_reopen_min_messages = messages_before + 2
                    self.report({"INFO"}, "Feedback enviado. Aguardando resposta do agente — o arquivo sera reaberto logo apos.")
                else:
                    self.report({"WARNING"}, "Feedback enviado, mas nenhum snapshot encontrado para reverter.")
            except Exception as exc:
                self.report({"WARNING"}, f"Feedback enviado, mas o restore falhou: {exc}")
        else:
            self.report({"INFO"}, "Feedback enviado. Sem snapshot disponivel para reverter.")

        _schedule_redraw()
        return {"FINISHED"}


class BLEND_OT_revert_snapshot(bpy.types.Operator):
    bl_idname = "blend.revert_snapshot"
    bl_label = "Reverter snapshot"
    bl_description = "Restaura o arquivo .blend para o snapshot anterior à execução"

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        info = _get_work_cycle_info()
        blend_path = info["blend_path"]
        session_id = info["session_id"]

        if not session_id or not blend_path:
            self.report({"ERROR"}, "Nenhum snapshot disponível para esta sessão.")
            return {"CANCELLED"}

        try:
            from ..snapshot_manager import list_snapshots, restore_snapshot
            project_root = _get_runtime().project_root
            snapshots = list_snapshots(session_id=session_id, project_root=project_root)
            if not snapshots:
                self.report({"WARNING"}, "Nenhum snapshot encontrado para esta sessão.")
                return {"CANCELLED"}
            latest = snapshots[0]["path"]
            restore_snapshot(snapshot_path=latest, target_path=blend_path)
            self.report({"INFO"}, "Snapshot restaurado. O arquivo será reaberto em breve.")
        except Exception as exc:
            self.report({"ERROR"}, f"Restore falhou: {exc}")
            return {"CANCELLED"}
        return {"FINISHED"}


# ---------------------------------------------------------------------------
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

    claude_api_key: StringProperty(
        name="Claude API Key",
        description="Anthropic API key (get one at console.anthropic.com)",
        subtype="PASSWORD",
        default="",
    )

    claude_model: StringProperty(
        name="Model",
        description="Claude model to use",
        default="claude-sonnet-4-6",
    )

    project_root_path: StringProperty(
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
    CHAT_OT_AttachScreenshot,   # from screenshot.py
    CHAT_OT_SetupWorkspace,
    CHAT_OT_OpenJournalFolder,
    # Onda 5 (Item 5.4): work-cycle operators
    BLEND_OT_execute_draft,
    BLEND_OT_open_draft,
    BLEND_OT_run_draft,
    BLEND_OT_discard_draft,
    BLEND_OT_report_result,
    BLEND_OT_result_success,
    BLEND_OT_result_failed,
    BLEND_OT_send_result_report,
    BLEND_OT_send_and_revert,
    BLEND_OT_revert_snapshot,
    CHAT_PT_Panel,
)

_ALL_CLASSES = _MAIN_CLASSES + ADVANCED_CLASSES


def register() -> None:
    global _runtime_poll_registered
    for cls in _ALL_CLASSES:
        bpy.utils.register_class(cls)

    bpy.types.Scene.chat_input = StringProperty(
        name="Message",
        description="Type your message here",
        options={"TEXTEDIT_UPDATE"},
        default="",
    )
    bpy.types.Scene.chat_prompt_buffer = PointerProperty(
        name="Prompt Buffer",
        description="Text datablock used for multi-line GN chat prompts",
        type=bpy.types.Text,
    )
    bpy.types.Scene.chat_debug_mode = BoolProperty(
        name="Debug",
        description="Enable debug mode for runtime policy context",
        default=False,
    )
    bpy.types.Scene.chat_explicit_override_mode = BoolProperty(
        name="Override",
        description="Enable explicit override mode for risky mutations",
        default=False,
    )
    bpy.types.Scene.chat_mcp_write_enabled = BoolProperty(
        name="MCP Writes",
        description="Allow mutating MCP calls",
        default=False,
    )
    bpy.types.Scene.chat_drafting_mode = BoolProperty(
        name="Drafting Mode",
        description="Agent writes scripts to Text Editor for manual execution instead of auto-executing",
        default=False,
    )
    bpy.types.Scene.chat_simulate_bridge_failure = BoolProperty(
        name="Simulate Bridge Failure",
        description="Debug validation: make structural-memory recovery fail while keeping the chat UI available",
        default=False,
    )
    bpy.types.Scene.chat_visible_message_count = IntProperty(
        name="Visible Messages",
        description="How many recent chat messages are shown in the panel",
        default=_DEFAULT_VISIBLE_MESSAGES,
        min=_DEFAULT_VISIBLE_MESSAGES,
    )
    bpy.types.Scene.chat_result_failed_mode = BoolProperty(
        name="Result Failed Mode",
        description="Shows the failure description field in RESULTADO state",
        default=False,
    )
    bpy.types.Scene.chat_result_description = StringProperty(
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
        bpy.utils.unregister_class(cls)

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
