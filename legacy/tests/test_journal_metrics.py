import json
import os
import tempfile
import unittest
from pathlib import Path

from blender_addon.operation_journal import OperationJournal


class JournalMetricsTests(unittest.TestCase):
    def test_index_prunes_old_session_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            journal = OperationJournal(project_root=root)
            for idx in range(15):
                journal.start_session(f"sess-{idx:02d}")
                journal.start_goal(user_message=f"goal {idx}")
                journal.end_goal()

            sessions_dir = root / "runtime" / "journal" / "sessions"
            session_files = sorted(p.name for p in sessions_dir.glob("*.jsonl"))
            self.assertLessEqual(len(session_files), 12)
            self.assertIn("sess-14.jsonl", session_files)
            self.assertNotIn("sess-00.jsonl", session_files)

    def test_tool_call_enriched_fields_are_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            journal = OperationJournal(project_root=root)
            journal.start_session("sess-test")
            journal.start_goal(user_message="test")
            journal.log_tool_call(
                tool_name="execute_code",
                payload_size=12,
                result_size=24,
                round_time_ms=5,
                status="success",
                tool_args_preview={"code": "print('x')"},
                tool_result_preview={"status": "success"},
                routing_reason="parsimony",
                tree_name="TreeA",
                node_name="NodeA",
                source_route="chat_internal",
                used_structured_tool=False,
                fallback_to_execute_code_reason="structured_tool_available_but_execute_code_selected",
                structured_tool_available=True,
                execute_code_inevitable=False,
                metadata={"k": "v"},
            )
            journal.end_goal()

            path = root / "runtime" / "journal" / "sessions" / "sess-test.jsonl"
            lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            tool_event = next(e for e in lines if e.get("type") == "tool_call")
            self.assertIn("tool_args_preview", tool_event)
            self.assertEqual(tool_event["routing_reason"], "parsimony")
            self.assertEqual(tool_event["tree_name"], "TreeA")
            self.assertEqual(tool_event["source_route"], "chat_internal")
            self.assertEqual(tool_event["used_structured_tool"], False)
            self.assertTrue(tool_event["structured_tool_available"])

    def test_goal_dashboard_contains_extended_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            journal = OperationJournal(project_root=root)
            journal.start_session("sess-metrics")
            journal.start_goal(user_message="test")
            journal.log_runtime_event(
                event_type="knowledge_selected",
                payload={
                    "injected_files": [{"source": "knowledge/skills/gn_mutation.md"}],
                    "estimated_tokens_total": 321,
                },
            )
            journal.log_runtime_event(
                event_type="skills_activated",
                payload={"skills_used": [{"skill": "scene_context_inspector"}]},
            )
            journal.log_runtime_event(
                event_type="plan_created",
                payload={"plan_id": "plan-1", "approval_token": "appr-1"},
            )
            journal.log_runtime_event(event_type="plan_presented_to_user", payload={"plan_summary": "x"})
            journal.log_runtime_event(event_type="approval_requested", payload={"plan_id": "plan-1"})
            journal.log_runtime_event(event_type="approval_granted", payload={"plan_id": "plan-1"})
            journal.log_runtime_event(event_type="approval_denied", payload={"plan_id": "plan-0"})
            journal.log_runtime_event(event_type="approval_expired", payload={"plan_id": "plan-0"})
            journal.log_runtime_event(event_type="plan_superseded", payload={"superseded_plan_id": "plan-0", "new_plan_id": "plan-1"})
            journal.log_runtime_event(event_type="staged_plan_created", payload={"plan_id": "plan-1", "stage_count": 3})
            journal.log_runtime_event(event_type="stage_presented_to_user", payload={"plan_id": "plan-1", "stage_id": "stage-1"})
            journal.log_runtime_event(event_type="stage_approved", payload={"plan_id": "plan-1", "stage_id": "stage-1"})
            journal.log_runtime_event(event_type="stage_executed", payload={"plan_id": "plan-1", "stage_id": "stage-1"})
            journal.log_runtime_event(event_type="stage_completed", payload={"plan_id": "plan-1", "stage_id": "stage-1"})
            journal.log_runtime_event(event_type="execution_blocked_waiting_user", payload={"reason": "approval_required_before_execution"})
            journal.log_runtime_event(event_type="session_resumed", payload={"session_id": "sess-metrics"})
            journal.log_runtime_event(event_type="resumed_session_state", payload={"resumed_session_state": "resumed_with_plan_pending"})
            journal.log_runtime_event(event_type="session_state_reset", payload={"reason": "reset_transient_state"})
            journal.log_runtime_event(event_type="pending_plan_cleared", payload={"source": "chat_ui"})
            journal.log_runtime_event(event_type="approval_state_cleared", payload={"source": "chat_ui"})
            journal.log_runtime_event(event_type="plan_rebuilt_after_invalid_state", payload={"plan_id": "plan-2"})
            journal.log_runtime_event(
                event_type="execution_started_with_valid_approval",
                payload={"execution_plan_id": "plan-1", "execution_approval_token": "appr-1"},
            )
            journal.log_runtime_event(
                event_type="execution_blocked_invalid_or_missing_approval",
                payload={"reason": "missing_plan_id_or_approval_token"},
            )
            journal.log_runtime_event(event_type="code_fallback_proposed", payload={"tool": "execute_code"})
            journal.log_runtime_event(event_type="fallback_plan_created", payload={"plan_id": "plan-fb"})
            journal.log_runtime_event(event_type="fallback_approval_requested", payload={"plan_id": "plan-fb"})
            journal.log_runtime_event(event_type="fallback_approval_granted", payload={"plan_id": "plan-fb"})
            journal.log_runtime_event(event_type="replan_presented_to_user", payload={"failed_tool": "create_node"})
            journal.log_runtime_event(event_type="task_class_inferred_by_agent", payload={"task_class": "localized_mutation"})
            journal.log_runtime_event(
                event_type="session_memory_used",
                payload={"used": True},
            )
            journal.log_runtime_event(
                event_type="local_scope_used",
                payload={"scope_type": "subgraph", "selected_nodes_count": 3},
            )
            journal.log_runtime_event(
                event_type="manual_execution_roundtrip",
                payload={"nodes": ["A", "B"]},
            )
            journal.log_runtime_event(event_type="api_usage", payload={"input_tokens": 10, "output_tokens": 5})
            journal.log_runtime_event(event_type="read_skipped_parsimony", payload={"tool_name": "get_scene_summary"})
            journal.log_tool_call(
                tool_name="create_node",
                payload_size=10,
                result_size=10,
                round_time_ms=1,
                status="success",
                used_structured_tool=True,
            )
            journal.log_tool_call(
                tool_name="get_node_context",
                payload_size=10,
                result_size=10,
                round_time_ms=1,
                status="success",
                used_structured_tool=True,
            )
            journal.log_tool_call(
                tool_name="get_node_context",
                payload_size=10,
                result_size=10,
                round_time_ms=1,
                status="success",
                used_structured_tool=True,
            )
            journal.log_tool_call(
                tool_name="execute_code",
                payload_size=10,
                result_size=10,
                round_time_ms=1,
                status="success",
                used_structured_tool=False,
                fallback_to_execute_code_reason="structured_tool_available_but_execute_code_selected",
            )
            journal.end_goal()

            path = root / "runtime" / "journal" / "sessions" / "sess-metrics.jsonl"
            lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            end_event = next(e for e in lines if e.get("type") == "goal_end")
            dashboard = end_event.get("dashboard", {})
            self.assertIn("structured_vs_code_ratio", dashboard)
            self.assertEqual(dashboard.get("total_api_rounds"), 1)
            self.assertEqual(dashboard.get("knowledge_files_injected"), 1)
            self.assertEqual(dashboard.get("knowledge_tokens_estimated"), 321)
            self.assertEqual(dashboard.get("analytical_skills_used"), 1)
            self.assertEqual(dashboard.get("skipped_reads_count"), 1)
            self.assertEqual(dashboard.get("execute_code_fallbacks"), 1)
            self.assertGreaterEqual(dashboard.get("repeated_reads_count", 0), 1)
            self.assertTrue(dashboard.get("session_memory_used"))
            self.assertTrue(dashboard.get("local_scope_used"))
            self.assertEqual(dashboard.get("selected_nodes_count"), 3)
            self.assertTrue(dashboard.get("manual_execution_roundtrip"))
            self.assertEqual(dashboard.get("plan_created_count"), 1)
            self.assertEqual(dashboard.get("plan_presented_to_user_count"), 1)
            self.assertEqual(dashboard.get("approval_requested_count"), 1)
            self.assertEqual(dashboard.get("approval_granted_count"), 1)
            self.assertEqual(dashboard.get("approval_denied_count"), 1)
            self.assertEqual(dashboard.get("approval_expired_count"), 1)
            self.assertEqual(dashboard.get("plan_superseded_count"), 1)
            self.assertEqual(dashboard.get("execution_started_with_valid_approval_count"), 1)
            self.assertEqual(dashboard.get("execution_blocked_invalid_or_missing_approval_count"), 1)
            self.assertEqual(dashboard.get("execution_blocked_waiting_user_count"), 1)
            self.assertEqual(dashboard.get("code_fallback_proposed_count"), 1)
            self.assertEqual(dashboard.get("fallback_plan_created_count"), 1)
            self.assertEqual(dashboard.get("fallback_approval_requested_count"), 1)
            self.assertEqual(dashboard.get("fallback_approval_granted_count"), 1)
            self.assertEqual(dashboard.get("replan_presented_to_user_count"), 1)
            self.assertEqual(dashboard.get("task_class_inferred_by_agent_count"), 1)
            self.assertEqual(dashboard.get("staged_plan_created_count"), 1)
            self.assertEqual(dashboard.get("stage_presented_to_user_count"), 1)
            self.assertEqual(dashboard.get("stage_approved_count"), 1)
            self.assertEqual(dashboard.get("stage_executed_count"), 1)
            self.assertEqual(dashboard.get("stage_completed_count"), 1)
            self.assertEqual(dashboard.get("session_resumed_count"), 1)
            self.assertEqual(dashboard.get("resumed_session_state_count"), 1)
            self.assertEqual(dashboard.get("session_state_reset_count"), 1)
            self.assertEqual(dashboard.get("pending_plan_cleared_count"), 1)
            self.assertEqual(dashboard.get("approval_state_cleared_count"), 1)
            self.assertEqual(dashboard.get("plan_rebuilt_after_invalid_state_count"), 1)

    def test_last_session_summary_prefers_index_updated_at_over_mtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            journal = OperationJournal(project_root=root)
            sessions_dir = root / "runtime" / "journal" / "sessions"
            newer = sessions_dir / "newer.jsonl"
            older = sessions_dir / "older.jsonl"
            newer.write_text('{"type":"goal_start","timestamp":"2026-04-01T00:00:00+00:00","session_id":"newer","goal_id":"g1","payload":{"user_message":"newer"}}\n', encoding="utf-8")
            older.write_text('{"type":"goal_start","timestamp":"2026-04-01T00:00:00+00:00","session_id":"older","goal_id":"g2","payload":{"user_message":"older"}}\n', encoding="utf-8")
            os.utime(newer, (10, 10))
            os.utime(older, (20, 20))
            (root / "runtime" / "journal" / "index.json").write_text(
                json.dumps({
                    "sessions": [
                        {
                            "session_id": "newer",
                            "session_file": str(newer.resolve()),
                            "updated_at": "2026-04-20T12:00:00+00:00",
                        },
                        {
                            "session_id": "older",
                            "session_file": str(older.resolve()),
                            "updated_at": "2026-04-19T12:00:00+00:00",
                        },
                    ]
                }),
                encoding="utf-8",
            )

            summary = journal.get_last_session_summary(max_goals=1)

            self.assertIn("newer", summary)

    def test_last_session_summary_falls_back_to_created_at_then_mtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            journal = OperationJournal(project_root=root)
            sessions_dir = root / "runtime" / "journal" / "sessions"
            created = sessions_dir / "created.jsonl"
            malformed = sessions_dir / "malformed.jsonl"
            created.write_text('{"type":"goal_start","timestamp":"2026-04-01T00:00:00+00:00","session_id":"created","goal_id":"g1","payload":{"user_message":"created"}}\n', encoding="utf-8")
            malformed.write_text('{"type":"goal_start","timestamp":"2026-04-01T00:00:00+00:00","session_id":"malformed","goal_id":"g2","payload":{"user_message":"malformed"}}\n', encoding="utf-8")
            os.utime(created, (10, 10))
            os.utime(malformed, (20, 20))
            (root / "runtime" / "journal" / "index.json").write_text(
                json.dumps({
                    "sessions": [
                        {
                            "session_id": "created",
                            "session_file": str(created.resolve()),
                            "created_at": "2026-04-20T12:00:00+00:00",
                        },
                        {
                            "session_id": "malformed",
                            "session_file": str(malformed.resolve()),
                            "updated_at": "not-a-timestamp",
                        },
                    ]
                }),
                encoding="utf-8",
            )
            journal._session_file = created

            last_summary = journal.get_last_session_summary(max_goals=1)
            previous_summary = journal.get_previous_session_summary(max_goals=1)

            self.assertIn("created", last_summary)
            self.assertIn("malformed", previous_summary)


if __name__ == "__main__":
    unittest.main()
