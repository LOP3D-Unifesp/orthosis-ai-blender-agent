"""Aggregated operator classes for GN Copilot UI registration."""

from __future__ import annotations

from .chat_operators import CHAT_OPERATOR_CLASSES
from .cycle_operators import CYCLE_OPERATOR_CLASSES

OPERATOR_CLASSES = CHAT_OPERATOR_CLASSES + CYCLE_OPERATOR_CLASSES

