"""UI package for the GN Copilot Blender panel.

Phase 8 of REFATOR_PLAN.md — Workstream H (UI Layering).

Package layout:
  chat_session.py   — _ChatSession class and SESSION singleton (no bpy deps)
  _helpers.py       — bpy-free utilities (_wrap_text, _PHASE_LABELS, etc.)
  screenshot.py     — Windows screenshot capture + operator
  advanced.py       — Advanced/Debug sub-panel (DEFAULT_CLOSED)
  panel.py          — Main conversation panel, operators, registration

register()/unregister() are lazy so that importing this package does NOT
pull bpy into the test environment.  SESSION is always safe to import.
"""

from __future__ import annotations

from .chat_session import SESSION  # bpy-free; safe to import anywhere


def register() -> None:
    from .panel import register as _register
    _register()


def unregister() -> None:
    from .panel import unregister as _unregister
    _unregister()


__all__ = ["SESSION", "register", "unregister"]
