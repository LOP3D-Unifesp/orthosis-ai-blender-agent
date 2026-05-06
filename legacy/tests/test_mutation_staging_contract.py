from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

if "bpy" not in sys.modules:
    handlers = types.SimpleNamespace(load_post=[], save_post=[], persistent=lambda fn: fn)
    sys.modules["bpy"] = types.SimpleNamespace(
        app=types.SimpleNamespace(handlers=handlers),
        data=types.SimpleNamespace(filepath=""),
    )

from blender_addon.agent_runtime import AgentRuntime
from blender_addon.runtime.handlers import TurnContext
from blender_addon.runtime.handlers import _agent_loop
from blender_addon.runtime.handlers.mutation_confirmation import handle as confirm_mutation
from blender_addon.runtime.router import ClassifierMeta, TurnClass
from blender_addon.session.schema import PendingMutation, Session


class _MutationRequestRuntime:
    def __init__(
        self,
        session: Session,
        *,
        goal: str = "Inspect Biomodelo interface",
        steps: list[str] | None = None,
        script: str = "print('approved')",
    ):
        self.runtime = SimpleNamespace(save_v1_session=MagicMock())
        self.journal = SimpleNamespace(
            log_runtime_event=MagicMock(),
            accumulate_tokens=MagicMock(),
        )
        self._session_state = {}
        self._tool_step = 0
        self._current_turn_tools: list[dict] = []
        self._session_memory = {}
        self._structural_index = {}
        self._halt_execution = False
        self._halt_message = ""
        self._execute_code_fail_count = 0
        self._make_plan_count = 0
        self._read_call_counts = {}
        self._active_v1_session = session
        self._capture_mode = False
        self._messages: list[dict] = []
        self.model = "test-model"
        self.tools = []
        self._execute_tool = AgentRuntime._execute_tool.__get__(self, type(self))
        self._postprocess_tool = AgentRuntime._postprocess_tool.__get__(self, type(self))
        self._update_operational_state_from_tool = lambda **_: None
        self._format_runtime_tool_result = AgentRuntime._format_runtime_tool_result
        self._goal = goal
        self._steps = list(steps or ["Inspect current interface", "Print sockets"])
        self._script = script

    def _agent_loop(self, system: str, messages: list[dict], max_tokens: int = 4096, excluded_tools=None) -> str:
        self._execute_tool(
            "make_plan",
            {
                "goal": self._goal,
                "steps": list(self._steps),
            },
            0,
        )
        self._execute_tool("execute_code", {"code": self._script}, 0)
        self._messages.append({"role": "assistant", "content": "model-generated summary"})
        return "model-generated summary"


class _ReplayRuntime:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.runtime = SimpleNamespace(save_v1_session=MagicMock())
        self.journal = SimpleNamespace(log_runtime_event=MagicMock(), accumulate_tokens=MagicMock())
        self._active_v1_session = None

    def _execute_tool(self, name: str, tool_input: dict, _api_elapsed_ms: int) -> str:
        self.calls.append((name, dict(tool_input)))
        return f"ok:{name}"


class MutationStagingContractTests(unittest.TestCase):
    def _mutation_request_ctx(self, session: Session, runtime: object) -> TurnContext:
        meta = ClassifierMeta(turn_class=TurnClass.MUTATION_REQUEST, needs_baseline_refresh=False)
        return TurnContext(
            session=session,
            message="set VM_G1_Scale to 1.0",
            meta=meta,
            blend_path="",
            _runtime=runtime,
            knowledge_dir=Path("missing") / "domain",
        )

    def test_read_only_staged_script_preview(self) -> None:
        session = Session()
        session.update_focus(object_name="FootMesh", modifier_name="GN_Biomodelo", tree_name="Biomodelo")
        runtime = _MutationRequestRuntime(
            session,
            goal="Inspect Biomodelo interface",
            steps=["Read current interface", "Print socket list"],
            script="print('Biomodelo interface')",
        )
        ctx = self._mutation_request_ctx(session, runtime)

        result = _agent_loop.handle(ctx, "mutation_request")

        pending = session.execution_state.pending_mutation
        self.assertIsNotNone(pending)
        self.assertEqual(session.execution_state.phase, "awaiting_confirmation")
        self.assertEqual(result.phase_transition, "awaiting_confirmation")
        self.assertEqual(
            pending.tool_calls,
            [
                {
                    "name": "make_plan",
                    "input": {
                        "goal": "Inspect Biomodelo interface",
                        "steps": ["Read current interface", "Print socket list"],
                    },
                },
                {
                    "name": "execute_code",
                    "input": {"code": "print('Biomodelo interface')"},
                },
            ],
        )
        self.assertEqual(pending.description, "Inspect Biomodelo interface")
        self.assertIn("Diagnóstico pronto para aprovação", result.response_text)
        self.assertIn("- Target object: FootMesh", result.response_text)
        self.assertIn("- Target modifier: GN_Biomodelo", result.response_text)
        self.assertIn("- Target node group: Biomodelo", result.response_text)
        self.assertIn("- Classification: read-only diagnostic", result.response_text)
        self.assertIn("- Expected visible effect: no visible scene change", result.response_text)
        self.assertIn("- Script behavior: only prints/inspects Blender data", result.response_text)
        self.assertEqual(runtime._messages[-1]["content"], result.response_text)
        staged_event = runtime.journal.log_runtime_event.call_args_list[-1].kwargs
        self.assertEqual(staged_event["event_type"], "staged_plan_created")
        self.assertEqual(staged_event["payload"]["classification"], "read_only")

    def test_mutating_staged_script_preview(self) -> None:
        session = Session()
        session.update_focus(object_name="FootMesh", modifier_name="GN_Biomodelo", tree_name="Biomodelo")
        runtime = _MutationRequestRuntime(
            session,
            goal="Move the Group Output node for readability",
            steps=["Find Group Output", "Move node in the editor"],
            script="node.location = (200, 100)",
        )
        ctx = self._mutation_request_ctx(session, runtime)

        result = _agent_loop.handle(ctx, "mutation_request")

        self.assertIn("Plano de alteração pronto para aprovação", result.response_text)
        self.assertIn("- Classification: mutating change", result.response_text)
        self.assertIn("- Expected visible effect: will change scene", result.response_text)
        self.assertIn("- Script behavior: actually edits Blender data", result.response_text)
        staged_event = runtime.journal.log_runtime_event.call_args_list[-1].kwargs
        self.assertEqual(staged_event["event_type"], "staged_plan_created")
        self.assertEqual(staged_event["payload"]["classification"], "mutating")

    def test_approval_replays_exact_staged_payload(self) -> None:
        session = Session()
        session.set_pending_mutation(
            PendingMutation(
                description="Set VM_G1_Scale to 1.0",
                tool_calls=[
                    {"name": "make_plan", "input": {"goal": "Set VM_G1_Scale to 1.0", "steps": ["Set scale"]}},
                    {"name": "execute_code", "input": {"code": "print('approved')"}},
                ],
            )
        )
        runtime = _ReplayRuntime()
        ctx = TurnContext(
            session=session,
            message="sim",
            meta=ClassifierMeta(turn_class=TurnClass.MUTATION_CONFIRMATION),
            blend_path="",
            _runtime=runtime,
        )

        result = confirm_mutation(ctx)

        self.assertEqual(
            runtime.calls,
            [
                ("make_plan", {"goal": "Set VM_G1_Scale to 1.0", "steps": ["Set scale"]}),
                ("execute_code", {"code": "print('approved')"}),
            ],
        )
        self.assertEqual(result.phase_transition, "idle")
        self.assertIsNone(session.execution_state.pending_mutation)

    def test_placeholder_payload_blocked_before_exec(self) -> None:
        session = Session()
        session.set_pending_mutation(
            PendingMutation(
                description="Inspect Biomodelo interface",
                tool_calls=[{"name": "execute_code", "input": {"code": "[1143-char script]"}}],
            )
        )
        runtime = _MutationRequestRuntime(session)
        ctx = TurnContext(
            session=session,
            message="sim",
            meta=ClassifierMeta(turn_class=TurnClass.MUTATION_CONFIRMATION),
            blend_path="",
            _runtime=runtime,
        )

        with patch("blender_addon.agent_runtime.dispatch_tool_raw") as dispatch:
            result = confirm_mutation(ctx)

        dispatch.assert_not_called()
        self.assertEqual(result.phase_transition, "failed")
        self.assertEqual(session.execution_state.phase, "failed")
        self.assertIn("placeholder", session.execution_state.last_failure.error.lower())
        blocked_events = [
            call.kwargs
            for call in runtime.journal.log_runtime_event.call_args_list
            if call.kwargs.get("event_type") == "execute_code_placeholder_blocked"
        ]
        self.assertTrue(blocked_events)

    def test_missing_staged_plan_fails_closed(self) -> None:
        session = Session()
        session.set_pending_mutation(PendingMutation(description="Set scale", tool_calls=[]))
        runtime = _ReplayRuntime()
        ctx = TurnContext(
            session=session,
            message="sim",
            meta=ClassifierMeta(turn_class=TurnClass.MUTATION_CONFIRMATION),
            blend_path="",
            _runtime=runtime,
        )

        result = confirm_mutation(ctx)

        self.assertEqual(runtime.calls, [])
        self.assertEqual(result.phase_transition, "failed")
        self.assertEqual(session.execution_state.last_failure.cause, "missing_staged_plan")
        self.assertIsNone(session.execution_state.pending_mutation)

    def test_non_execute_code_mutation_tools_now_depend_on_phase_not_flag(self) -> None:
        session = Session()
        session.execution_state.set_phase("executing")
        runtime = _MutationRequestRuntime(session)
        runtime._capture_mode = False

        with patch("blender_addon.agent_runtime.dispatch_tool_raw") as dispatch:
            dispatch.return_value = {"status": "success", "result": {"ok": True}}
            result = runtime._execute_tool(
                "apply_simulator_payload",
                {"tree_name": "Tree", "payload": {"value": 1}},
                0,
            )

        dispatch.assert_called_once()
        self.assertNotIn("BLOCKED", result)

        idle_session = Session()
        idle_runtime = _MutationRequestRuntime(idle_session)
        idle_runtime._capture_mode = False

        with patch("blender_addon.agent_runtime.dispatch_tool_raw") as dispatch:
            blocked = idle_runtime._execute_tool(
                "apply_simulator_payload",
                {"tree_name": "Tree", "payload": {"value": 1}},
                0,
            )

        dispatch.assert_not_called()
        self.assertIn("BLOCKED", blocked)


if __name__ == "__main__":
    unittest.main()
