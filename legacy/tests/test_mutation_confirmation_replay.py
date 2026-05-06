from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

if "bpy" not in sys.modules:
    _handlers = types.SimpleNamespace(load_post=[], save_post=[], persistent=lambda fn: fn)
    sys.modules["bpy"] = types.SimpleNamespace(
        app=types.SimpleNamespace(handlers=_handlers),
        data=types.SimpleNamespace(filepath=""),
    )

from blender_addon.runtime.handlers import TurnContext
from blender_addon.runtime.handlers.mutation_confirmation import handle
from blender_addon.runtime.router import ClassifierMeta, TurnClass
from blender_addon.session.schema import PendingMutation, Session


class _RuntimeStub:
    def __init__(self, tool_result: str = "ok"):
        self.tool_result = tool_result
        self.tool_calls: list[tuple[str, dict]] = []
        self.runtime = types.SimpleNamespace(save_v1_session=lambda session: None)

    def _execute_tool(self, name: str, tool_input: dict, _api_elapsed_ms: int) -> str:
        self.tool_calls.append((name, dict(tool_input)))
        return self.tool_result


class MutationConfirmationReplayTests(unittest.TestCase):
    def _ctx(self, session: Session, runtime: _RuntimeStub | None = None) -> TurnContext:
        return TurnContext(
            session=session,
            message="yes",
            meta=ClassifierMeta(turn_class=TurnClass.MUTATION_CONFIRMATION),
            blend_path=session.focus.blend_path,
            _runtime=runtime or _RuntimeStub(),
            knowledge_dir=Path("."),
        )

    def test_confirmation_replays_exact_staged_tool_calls(self):
        session = Session.new(blend_path="demo.blend")
        session.set_pending_mutation(
            PendingMutation(
                description="Set VM_G1_Scale to 1.0",
                tool_calls=[{"name": "execute_code", "input": {"code": "print('approved')"}}],
            )
        )
        runtime = _RuntimeStub(tool_result="approved")

        result = handle(self._ctx(session, runtime))

        self.assertEqual(runtime.tool_calls, [("execute_code", {"code": "print('approved')"})])
        self.assertEqual(session.execution_state.phase, "idle")
        self.assertEqual(result.phase_transition, "idle")

    def test_confirmation_fails_closed_when_staged_tool_calls_are_missing(self):
        session = Session.new(blend_path="demo.blend")
        session.set_pending_mutation(
            PendingMutation(
                description="Set VM_G1_Scale to 1.0",
                tool_calls=[],
            )
        )
        runtime = _RuntimeStub()

        result = handle(self._ctx(session, runtime))

        self.assertEqual(runtime.tool_calls, [])
        self.assertEqual(session.execution_state.phase, "failed")
        self.assertIsNone(session.execution_state.pending_mutation)
        self.assertEqual(session.execution_state.last_failure.cause, "missing_staged_plan")
        self.assertIn("did not execute", result.response_text.lower())
        self.assertEqual(result.phase_transition, "failed")


if __name__ == "__main__":
    unittest.main()
