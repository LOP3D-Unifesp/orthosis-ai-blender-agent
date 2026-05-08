"""Runtime, session, prompt-buffer, and chat-turn helpers for the UI panel."""

from __future__ import annotations

import site
import sys
import threading
import time
from pathlib import Path

import bpy

from ..core.runtime import AgentRuntime
from ..project_paths import resolve_project_root
from ..tools import call_blender_socket
from .. import get_effective_blend_path as _get_effective_blend_path
from .chat_session import SESSION
from ._helpers import (
    _estimate_wrap_width,
    _normalize_multiline_text,
    _get_execution_phase as _get_execution_phase_helper,
)
from .cycle_state import _set_work_cycle_phase

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


# Operators
# ---------------------------------------------------------------------------

__all__ = [name for name in globals() if name == "SESSION" or name.startswith("_")]
