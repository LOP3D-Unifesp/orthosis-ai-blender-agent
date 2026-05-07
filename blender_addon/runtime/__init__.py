"""Central runtime package for the draft-first product flow.

The chat path in ``AgentRuntime.run_turn`` now infers a small workspace
``goal_mode`` and calls ``handler.workspace.handle`` directly.

Public exports:
    Runtime         - central bridge runtime
    TurnRouter      - message classifier
    TurnClass       - enum of live draft-first turn classes
"""

from __future__ import annotations

from .core import Runtime
from .router import TurnClass, TurnRouter

__all__ = ["Runtime", "TurnClass", "TurnRouter"]
