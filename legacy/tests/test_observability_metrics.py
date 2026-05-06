from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

if "bpy" not in sys.modules:
    handlers = types.SimpleNamespace(load_post=[], save_post=[], persistent=lambda fn: fn)
    sys.modules["bpy"] = types.SimpleNamespace(
        app=types.SimpleNamespace(handlers=handlers),
        data=types.SimpleNamespace(filepath=""),
    )

from blender_addon.agent_runtime import AgentRuntime
from blender_addon.operation_journal import OperationJournal
from blender_addon.session.schema import Session


def _goal_dashboard(path: Path) -> dict:
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    end_event = next(entry for entry in lines if entry.get("type") == "goal_end")
    return end_event.get("dashboard", {})


class ObservabilityDashboardTests(unittest.TestCase):
    def test_tool_calls_increment_from_runtime_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            journal = OperationJournal(project_root=root)
            journal.start_session("sess-observability")
            journal.start_goal(user_message="inspect tree")
            journal.log_runtime_event(
                event_type="tool_dispatched",
                payload={
                    "tool": "get_tree_structure",
                    "elapsed_ms": 12,
                    "status": "success",
                    "tree_name": "Biomodelo",
                    "used_structured_tool": True,
                },
            )
            journal.log_runtime_event(
                event_type="tool_dispatched",
                payload={
                    "tool": "get_node_context",
                    "elapsed_ms": 8,
                    "status": "success",
                    "tree_name": "Biomodelo",
                    "node_name": "Group Output",
                    "used_structured_tool": True,
                },
            )
            journal.end_goal()

            dashboard = _goal_dashboard(root / "runtime" / "journal" / "sessions" / "sess-observability.jsonl")

            self.assertEqual(dashboard.get("total_tool_calls"), 2)
            self.assertEqual(dashboard.get("tool_breakdown", {}).get("get_tree_structure"), 1)
            self.assertEqual(dashboard.get("tool_breakdown", {}).get("get_node_context"), 1)
            self.assertEqual(dashboard.get("structured_vs_code_ratio", {}).get("structured_tool_calls"), 2)
            self.assertEqual(dashboard.get("structured_vs_code_ratio", {}).get("execute_code_calls"), 0)
            self.assertEqual(dashboard.get("broad_reads_count"), 1)
            self.assertEqual(dashboard.get("focal_reads_count"), 1)

    def test_staged_approval_flow_and_read_only_execute_code_are_visible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            journal = OperationJournal(project_root=root)
            journal.start_session("sess-staged")
            journal.start_goal(user_message="inspect Biomodelo")
            journal.log_runtime_event(
                event_type="canonical_gn_target_resolved",
                payload={
                    "target": {
                        "object": "FootMesh",
                        "modifier": "GN_Biomodelo",
                        "tree_name": "Biomodelo",
                    },
                    "source": "active_object",
                    "explicit": False,
                },
            )
            journal.log_runtime_event(
                event_type="staged_plan_created",
                payload={
                    "classification": "read_only",
                    "target_summary": {
                        "object": "FootMesh",
                        "modifier": "GN_Biomodelo",
                        "node_group": "Biomodelo",
                    },
                    "expected_visible_scene_change": "no visible scene change",
                    "script_behavior": "only prints/inspects Blender data",
                },
            )
            journal.log_runtime_event(event_type="stage_presented_to_user", payload={"stage_id": "stage-1"})
            journal.log_runtime_event(event_type="approval_requested", payload={"plan_id": "plan-1"})
            journal.log_runtime_event(event_type="stage_approved", payload={"stage_id": "stage-1"})
            journal.log_runtime_event(event_type="approval_granted", payload={"plan_id": "plan-1"})
            journal.log_runtime_event(
                event_type="tool_dispatched",
                payload={
                    "tool": "execute_code",
                    "elapsed_ms": 5,
                    "status": "success",
                    "staged": True,
                    "used_structured_tool": False,
                    "classification": "read_only",
                    "expected_visible_scene_change": "no visible scene change",
                },
            )
            journal.log_runtime_event(
                event_type="execute_code_attempt",
                payload={
                    "status": "success",
                    "code": "print('inspect')",
                    "staged": True,
                    "classification": "read_only",
                    "expected_visible_scene_change": "no visible scene change",
                    "script_behavior": "only prints/inspects Blender data",
                    "target_summary": {
                        "object": "FootMesh",
                        "modifier": "GN_Biomodelo",
                        "node_group": "Biomodelo",
                    },
                },
            )
            journal.end_goal()

            dashboard = _goal_dashboard(root / "runtime" / "journal" / "sessions" / "sess-staged.jsonl")

            self.assertEqual(dashboard.get("staged_plan_created_count"), 1)
            self.assertEqual(dashboard.get("stage_presented_to_user_count"), 1)
            self.assertEqual(dashboard.get("stage_approved_count"), 1)
            self.assertEqual(dashboard.get("approval_requested_count"), 1)
            self.assertEqual(dashboard.get("approval_granted_count"), 1)
            self.assertEqual(dashboard.get("structured_vs_code_ratio", {}).get("execute_code_calls"), 1)
            self.assertEqual(dashboard.get("code_executions"), 0)
            self.assertEqual(dashboard.get("staged_execute_code_calls"), 1)
            self.assertEqual(dashboard.get("execute_code_calls_read_only"), 1)
            self.assertEqual(dashboard.get("code_executions_read_only"), 0)
            self.assertEqual(dashboard.get("staged_payload_classification"), "read_only")
            self.assertEqual(
                dashboard.get("canonical_gn_target", {}).get("tree_name"),
                "Biomodelo",
            )

    def test_mutating_execute_code_is_visible_in_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            journal = OperationJournal(project_root=root)
            journal.start_session("sess-mutating")
            journal.start_goal(user_message="move output node")
            journal.log_runtime_event(
                event_type="tool_dispatched",
                payload={
                    "tool": "execute_code",
                    "elapsed_ms": 18,
                    "status": "success",
                    "staged": False,
                    "used_structured_tool": False,
                    "classification": "mutating",
                    "expected_visible_scene_change": "will change scene",
                },
            )
            journal.log_runtime_event(
                event_type="execute_code_attempt",
                payload={
                    "status": "success",
                    "code": "node.location = (200, 100)",
                    "staged": False,
                    "classification": "mutating",
                    "expected_visible_scene_change": "will change scene",
                    "script_behavior": "actually edits Blender data",
                },
            )
            journal.end_goal()

            dashboard = _goal_dashboard(root / "runtime" / "journal" / "sessions" / "sess-mutating.jsonl")

            self.assertEqual(dashboard.get("structured_vs_code_ratio", {}).get("execute_code_calls"), 1)
            self.assertEqual(dashboard.get("code_executions"), 1)
            self.assertEqual(dashboard.get("execute_code_calls_mutating"), 1)
            self.assertEqual(dashboard.get("code_executions_mutating"), 1)


class SessionMemoryInstrumentationTests(unittest.TestCase):
    @staticmethod
    def _runtime_stub(initial_memory: dict | None = None):
        runtime = SimpleNamespace(
            _session_memory=dict(initial_memory or {}),
            _session_state={},
            _local_scope={},
            _structural_index={},
            _session_memory_usage_reasons=set(),
            _canonical_gn_target=None,
            _active_v1_session=Session(),
            journal=SimpleNamespace(log_runtime_event=MagicMock()),
        )
        runtime._extract_tree_name = AgentRuntime._extract_tree_name
        runtime._extract_node_name = AgentRuntime._extract_node_name
        runtime._build_structural_index_entry = AgentRuntime._build_structural_index_entry
        runtime._build_target_summary = AgentRuntime._build_target_summary.__get__(runtime, type(runtime))
        runtime._log_session_memory_used = AgentRuntime._log_session_memory_used.__get__(runtime, type(runtime))
        runtime._update_operational_state_from_tool = AgentRuntime._update_operational_state_from_tool.__get__(
            runtime,
            type(runtime),
        )
        return runtime

    def test_session_memory_used_only_on_real_fallback(self) -> None:
        runtime = self._runtime_stub({"target_tree": "Biomodelo", "relevant_nodes": []})

        runtime._update_operational_state_from_tool(
            tool_name="get_scene_summary",
            tool_input={},
            runtime_raw={"status": "success", "result": {}},
        )

        used_events = [
            call.kwargs
            for call in runtime.journal.log_runtime_event.call_args_list
            if call.kwargs.get("event_type") == "session_memory_used"
        ]
        self.assertEqual(len(used_events), 1)
        self.assertEqual(used_events[0]["payload"]["reason"], "target_tree_fallback_for_operational_state")

    def test_session_memory_used_stays_false_when_tool_input_is_explicit(self) -> None:
        runtime = self._runtime_stub({"target_tree": "Biomodelo", "relevant_nodes": []})

        runtime._update_operational_state_from_tool(
            tool_name="get_node_context",
            tool_input={"tree_name": "Biomodelo", "node_name": "Group Output"},
            runtime_raw={"status": "success", "result": {"tree_name": "Biomodelo", "nodes": [], "links": []}},
        )

        used_events = [
            call.kwargs
            for call in runtime.journal.log_runtime_event.call_args_list
            if call.kwargs.get("event_type") == "session_memory_used"
        ]
        self.assertEqual(used_events, [])


if __name__ == "__main__":
    unittest.main()
