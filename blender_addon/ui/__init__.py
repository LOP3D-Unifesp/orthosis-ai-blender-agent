"""UI package — bridge status panel only."""

from __future__ import annotations


def register() -> None:
    from .bridge_panel import register as _register
    _register()


def unregister() -> None:
    from .bridge_panel import unregister as _unregister
    _unregister()
