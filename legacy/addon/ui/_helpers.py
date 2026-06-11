"""bpy-free utilities shared across the UI package.

Keeping these in a separate module lets unit tests import them
without pulling in bpy.
"""

from __future__ import annotations

import textwrap


_LINE_WIDTH = 56


def _wrap_text(text: str, width: int = _LINE_WIDTH) -> list[str]:
    """Wrap *text* to *width* characters, preserving blank lines."""
    if not text:
        return [""]
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            lines.append("")
        else:
            lines.extend(textwrap.wrap(paragraph, width) or [paragraph])
    return lines


def _estimate_wrap_width(
    region_width: int,
    *,
    chrome_px: int = 72,
    min_chars: int = 24,
    max_chars: int = 120,
    avg_char_px: float = 7.2,
) -> int:
    """Estimate a text wrap width from the current UI region width."""
    try:
        width_px = max(int(region_width), 0)
    except Exception:
        width_px = 0
    usable_px = max(width_px - chrome_px, int(min_chars * avg_char_px))
    estimated = int(usable_px / max(avg_char_px, 1.0))
    return max(min_chars, min(max_chars, estimated))


def _normalize_multiline_text(value: str) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n")


# Phase → (label text, Blender icon name)
# idle is intentionally absent — no badge is shown for idle.
_PHASE_LABELS: dict[str, tuple[str, str]] = {
    # Internal runtime phases (execution_state.phase)
    "executing": ("Executando...", "SCRIPT"),
    "failed": ("Última tentativa falhou", "ERROR"),
    "reading": ("Lendo...", "VIEWZOOM"),
    "halted": ("Pausado", "PAUSE"),
    # Work cycle phases (execution_state.work_cycle_phase) — shown as status banner
    "pending_user_execution": ("Draft pronto — aguardando execução", "CHECKMARK"),
    "awaiting_feedback": ("Aguardando resultado", "QUESTION"),
}


def _get_execution_phase(runtime_project_root: str, blend_path: str) -> str:
    """Read execution_state.phase from the V1 structured session.

    Returns an empty string on any error (no bpy required, no file
    required — safe to call from tests).
    """
    try:
        from pathlib import Path
        from ..session import SessionV1Store
        store = SessionV1Store(project_root=Path(runtime_project_root))
        v1 = store.load(blend_path)
        return v1.execution_state.phase
    except Exception:
        return ""
