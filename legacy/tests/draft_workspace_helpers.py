from __future__ import annotations

from typing import Any


def handle_draft_workspace_via_live_handler(ctx: Any):
    """Dispatch draft tests through the live workspace handler surface."""
    from blender_addon.handler.draft_state import _load_draft_workspace_state
    from blender_addon.handler.workspace import handle

    goal_mode = str(getattr(ctx.meta, "goal_mode", "") or "").strip()
    if not goal_mode:
        state = _load_draft_workspace_state(ctx)
        setattr(ctx, "_draft_workspace_state_cache", state)
        goal_mode = state.goal_mode or "focal_correction"
    return handle(ctx, goal_mode)
