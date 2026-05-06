"""Structural-memory tool handlers — thin re-export layer.

The full implementations live in server_dispatch.RuntimeDispatcher.
This module exposes the public names for future extraction.
"""

from .server_dispatch import RuntimeDispatcher

__all__ = ["RuntimeDispatcher"]
