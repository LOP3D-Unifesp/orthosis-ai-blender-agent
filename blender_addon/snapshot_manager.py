"""Blend file snapshot manager — Item 5.3 / Onda 5.

Creates, lists, and restores point-in-time copies of the .blend file.
Snapshots live at:
    {project_root}/runtime/snapshots/{session_id}/snap_{ts}_r{n}.blend

Intended callers: UI operators only (BLEND_OT_execute_draft,
BLEND_OT_restore_snapshot).  Never called from the agent loop.

Design notes
------------
take_snapshot()
    Uses bpy.ops.wm.save_as_mainfile(copy=True).  This saves the current
    bpy.data state to a NEW file without changing bpy.data.filepath or
    setting the unsaved-changes flag.  Must be called from the Blender main
    thread — the socket dispatch handler qualifies because Blender's socket
    server processes commands synchronously before returning to the event loop.

restore_snapshot()
    Copies the snapshot over target_path with shutil.copy2(), then schedules
    bpy.ops.wm.open_mainfile() via bpy.app.timers to run on the main thread.
    The 0.4-second delay gives the socket response time to reach the client
    before the file reload kills the server thread.

    User confirmation must happen in the UI operator (BLEND_OT_restore_snapshot)
    BEFORE calling this function — showing a modal dialog from a socket handler
    thread is not safe.

    After open_mainfile fires:
    - The socket server thread is destroyed (addon re-registers it on load).
    - All in-memory AgentRuntime / _runtime state is reset.
    - Disk-persisted state (sessions_v1/, chat_history/, journal/) survives.

Snapshot uniqueness
    Snapshots of the same revision are never overwritten.  If snap_*_r3.blend
    already exists a letter suffix (_b, _c, …) is appended.
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _snapshots_dir(project_root: str | Path, session_id: str) -> Path:
    path = Path(project_root) / "runtime" / "snapshots" / session_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _unique_snapshot_path(directory: Path, timestamp: str, revision: int) -> Path:
    """Return a path that does not exist, appending a suffix if needed."""
    base = f"snap_{timestamp}_r{revision}"
    candidate = directory / f"{base}.blend"
    if not candidate.exists():
        return candidate
    for ch in "bcdefghijklmnopqrstuvwxyz":
        candidate = directory / f"{base}_{ch}.blend"
        if not candidate.exists():
            return candidate
    # Extreme fallback: microsecond precision guarantees uniqueness
    ts_us = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    return directory / f"snap_{ts_us}_r{revision}.blend"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def take_snapshot(
    blend_path: str,
    session_id: str,
    revision: int,
    project_root: str | Path,
) -> str:
    """Save a copy of the current bpy.data state without touching the original.

    Returns the absolute path of the created snapshot file.
    Raises RuntimeError if bpy is unavailable or the save fails.
    """
    try:
        import bpy  # type: ignore
    except ImportError as exc:
        raise RuntimeError("bpy not available — must run inside Blender") from exc

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snap_dir = _snapshots_dir(project_root, session_id)
    snap_path = _unique_snapshot_path(snap_dir, ts, revision)

    result = bpy.ops.wm.save_as_mainfile(
        filepath=str(snap_path),
        copy=True,
        check_existing=False,
    )
    if "FINISHED" not in result:
        raise RuntimeError(
            f"save_as_mainfile returned {result!r} for {snap_path}"
        )

    return str(snap_path)


def list_snapshots(
    session_id: str,
    project_root: str | Path,
) -> list[dict[str, Any]]:
    """Return metadata for all snapshots of a session, newest first."""
    snap_dir = Path(project_root) / "runtime" / "snapshots" / session_id
    if not snap_dir.exists():
        return []

    entries: list[dict[str, Any]] = []
    for p in sorted(
        snap_dir.glob("snap_*.blend"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    ):
        try:
            stat = p.stat()
            entries.append(
                {
                    "path": str(p),
                    "filename": p.name,
                    "size_bytes": stat.st_size,
                    "mtime": datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc
                    ).isoformat(),
                }
            )
        except OSError:
            continue
    return entries


def restore_snapshot(snapshot_path: str, target_path: str) -> None:
    """Overwrite target_path with snapshot_path, then reopen target_path.

    The file copy is synchronous.  The reopen is deferred via
    bpy.app.timers so it runs on the main thread after the socket response
    has been sent.

    Caller responsibility: show a confirmation dialog BEFORE calling this.
    """
    shutil.copy2(snapshot_path, target_path)

    try:
        import bpy  # type: ignore

        _target = str(target_path)

        def _open_restored() -> None:
            try:
                bpy.ops.wm.open_mainfile(filepath=_target)
            except Exception:
                pass
            return None  # do not repeat

        bpy.app.timers.register(_open_restored, first_interval=0.4)
    except ImportError:
        pass  # outside Blender — file was still copied
