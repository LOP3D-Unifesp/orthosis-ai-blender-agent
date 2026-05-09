"""Blender addon for orthosis copilot runtime.

Primary path: Blender sidebar copilot UI.
Alternate path: MCP tools for Claude/external automation.
"""

bl_info = {
    "name": "Orthosis AI Agent",
    "author": "VB Orthosis Project",
    "version": (0, 3, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > Orthosis",
    "description": "Copilot for parametric orthosis design in Blender with optional MCP integration",
    "category": "Development",
}

import bpy

_last_known_blend_path = ""


def get_effective_blend_path() -> str:
    """Return the current blend file path, or empty string when unsaved."""
    try:
        return bpy.data.filepath or ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Blend-file lifecycle handler
# ---------------------------------------------------------------------------

@bpy.app.handlers.persistent
def _on_blend_load_post(scene=None):
    """Reset in-memory state when Blender loads a new file.

    Fires after File > New, File > Open, File > Open Recent, and File > Revert.
    Clears the visible message list and the runtime's API context buffer, then
    re-enables history hydration so any persisted history for the opened file
    appears in the panel on the next draw cycle.
    """
    _new_path = get_effective_blend_path()

    try:
        from .ui.chat_session import SESSION
        SESSION.clear()
    except Exception:
        pass

    try:
        from .ui import panel as _panel_module
        rt = getattr(_panel_module, "_runtime", None)
        if rt is not None:
            rt.clear_runtime_context()
        # Enable hydration so the per-file session history (if any) is
        # restored to the panel on the next draw cycle.
        _panel_module._history_hydration_enabled = True
    except Exception:
        pass

    global _last_known_blend_path
    _last_known_blend_path = _new_path


def _reattach_session_binding(previous_blend_path: str, current_blend_path: str) -> None:
    if not current_blend_path or previous_blend_path == current_blend_path:
        return

    reattach_result: dict[str, object] = {
        "status": "noop",
        "old_blend_path": previous_blend_path,
        "new_blend_path": current_blend_path,
    }
    try:
        from .project_paths import resolve_project_root
        from .runtime import Runtime

        runtime = Runtime(project_root=resolve_project_root())
        reattach_result = runtime.reattach_session_result(previous_blend_path, current_blend_path)
        if str(reattach_result.get("status") or "") == "target_exists":
            runtime.journal.log_runtime_event(
                event_type="save_as_session_conflict",
                payload={
                    "old_blend_path": str(reattach_result.get("old_blend_path") or previous_blend_path),
                    "new_blend_path": str(reattach_result.get("new_blend_path") or current_blend_path),
                    "source_session_file": str(reattach_result.get("source_session_file") or ""),
                    "target_session_file": str(reattach_result.get("target_session_file") or ""),
                    "message": (
                        "Save As found an existing session for the target file. "
                        "The previous file session was not rebound. No overwrite or merge was performed."
                    ),
                },
                status="warning",
            )
    except Exception:
        pass

    try:
        from .ui.chat_session import SESSION
        from .ui import panel as _panel_module

        if str(reattach_result.get("status") or "") == "target_exists":
            SESSION.set_session_notice(
                "Save As found an existing session for this file. "
                "The previous file's session was not rebound, and no overwrite/merge was performed."
            )
        else:
            SESSION.set_session_notice("")

        rt = getattr(_panel_module, "_runtime", None)
        if rt is not None:
            rt._active_v1_session = rt.runtime.v1_session_for(current_blend_path)
            if isinstance(getattr(rt, "_session_state", None), dict):
                rt._session_state["blend_path"] = current_blend_path
        _panel_module._session_cache["ts"] = 0.0
        _panel_module._session_cache["blend_path"] = ""
        _panel_module._session_cache["state"] = None
        _panel_module._history_hydration_enabled = True
        _panel_module._schedule_redraw()
    except Exception:
        pass


@bpy.app.handlers.persistent
def _on_blend_save_post(scene=None):
    _ = scene
    global _last_known_blend_path
    current_blend_path = get_effective_blend_path()
    previous_blend_path = _last_known_blend_path
    _reattach_session_binding(previous_blend_path, current_blend_path)
    _last_known_blend_path = current_blend_path


def register():
    from . import ui, server
    from .project_paths import sync_addon_project_root_preference

    ui.register()
    server.register()
    try:
        sync_addon_project_root_preference()
        server.refresh_runtime_project_root()
    except Exception:
        pass
    handlers = getattr(getattr(bpy, "app", None), "handlers", None)
    load_post = getattr(handlers, "load_post", None)
    save_post = getattr(handlers, "save_post", None)
    if isinstance(load_post, list) and _on_blend_load_post not in load_post:
        load_post.append(_on_blend_load_post)
    if isinstance(save_post, list) and _on_blend_save_post not in save_post:
        save_post.append(_on_blend_save_post)


def unregister():
    from . import ui, server
    server.unregister()
    ui.unregister()
    handlers = getattr(getattr(bpy, "app", None), "handlers", None)
    load_post = getattr(handlers, "load_post", None)
    save_post = getattr(handlers, "save_post", None)
    if isinstance(load_post, list) and _on_blend_load_post in load_post:
        load_post.remove(_on_blend_load_post)
    if isinstance(save_post, list) and _on_blend_save_post in save_post:
        save_post.remove(_on_blend_save_post)
