"""UI package — bridge status panel + biomodel anthropometry panel."""

from __future__ import annotations


def register() -> None:
    from .bridge_panel import register as _register_bridge
    from .anthropometry_panel import register as _register_anthro
    _register_bridge()
    _register_anthro()


def unregister() -> None:
    from .bridge_panel import unregister as _unregister_bridge
    from .anthropometry_panel import unregister as _unregister_anthro
    _unregister_anthro()
    _unregister_bridge()
