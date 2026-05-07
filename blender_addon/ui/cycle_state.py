"""Work-cycle state helpers used by UI operators and deferred redraw."""

from __future__ import annotations

from .. import get_effective_blend_path as _get_effective_blend_path


def _set_work_cycle_phase(phase: str) -> None:
    """Set work_cycle_phase in the V1 session."""
    try:
        from . import panel_runtime as _runtime

        rt = _runtime._get_runtime()
        blend_path = _get_effective_blend_path()
        rt.runtime.set_work_cycle_phase(blend_path, phase)
    except Exception:
        pass


def _get_work_cycle_info() -> dict:
    """Return (session_id, blend_path, current_revision) for snapshot calls."""
    try:
        from . import panel_runtime as _runtime

        blend_path = _get_effective_blend_path()
        rt = _runtime._get_runtime()
        session = rt.runtime.v1_session_for(blend_path)
        session_id = str(getattr(getattr(session, "identity", None), "session_id", "") or "")
        revision = int(getattr(getattr(session, "execution_state", None), "draft_revision", 0) or 0)
        return {"blend_path": blend_path, "session_id": session_id, "revision": revision}
    except Exception:
        return {"blend_path": "", "session_id": "", "revision": 0}
