import json
import unittest
from unittest.mock import patch

import server


class McpServerSurfaceTests(unittest.TestCase):
    def test_start_new_session_returns_compact_state(self):
        bridge_state = {
            "status": "success",
            "result": {
                "session_id": "sess-new",
                "session_state": "active",
                "agent_session_active": True,
                "_runtime_journal_session_file": "C:/proj/runtime/journal/sessions/sess-new.jsonl",
            },
        }

        with patch.object(server, "_blender") as blender:
            blender.runtime_set_modes.return_value = bridge_state
            payload = json.loads(server.start_new_session())

        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["action"], "start_new_session")
        self.assertEqual(payload["session_id"], "sess-new")
        self.assertEqual(payload["session_state"], "active")
        blender.runtime_set_modes.assert_called_once_with(
            agent_session_active=True,
            reset_session_memory=True,
            start_new_session=True,
            control_source="mcp",
        )

    def test_get_runtime_overview_returns_compact_snapshot(self):
        """Phase 9: compact overview no longer includes plan/approval fields."""
        bridge_state = {
            "status": "success",
            "result": {
                "session_id": "sess-123",
                "session_state": "active",
                "blend_path": "C:/tmp/test.blend",
                "runtime_phase": "executing",
                "agent_session_active": True,
                "turn_counter": 7,
                "last_task_class": "localized_mutation",
                "last_routing_reason": "parsimony",
                "_runtime_journal_base_dir": "C:/proj/runtime/journal",
                "_runtime_journal_session_file": "C:/proj/runtime/journal/sessions/sess-123.jsonl",
                "_runtime_journal_index_file": "C:/proj/runtime/journal/index.json",
            },
        }

        with patch.object(server, "_runtime_session_state", return_value=bridge_state):
            payload = json.loads(server.get_runtime_overview())

        self.assertEqual(payload["session_id"], "sess-123")
        self.assertEqual(payload["turn_counter"], 7)
        self.assertEqual(payload["last_task_class"], "localized_mutation")
        self.assertEqual(payload["journal_session_file"], "C:/proj/runtime/journal/sessions/sess-123.jsonl")
        # Phase 9: dead fields must not be present
        self.assertNotIn("current_plan_id", payload)
        self.assertNotIn("presented_plan_tools", payload)
        self.assertNotIn("approval_required", payload)
        self.assertNotIn("approval_status", payload)

    def test_continue_agent_session_resumes_without_rotating(self):
        with patch.object(server, "_blender") as blender:
            blender.runtime_set_modes.return_value = {"status": "success", "result": {"session_state": "active"}}
            payload = json.loads(server.continue_agent_session())

        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["action"], "continue_agent_session")
        blender.runtime_set_modes.assert_called_once_with(
            agent_session_active=True,
            reset_session_memory=False,
            control_source="mcp",
        )

    def test_get_current_session_journal_summary_uses_journal_helper(self):
        state = {
            "status": "success",
            "result": {
                "session_id": "sess-abc",
                "_runtime_journal_session_file": "C:/proj/runtime/journal/sessions/sess-abc.jsonl",
            },
        }
        with patch.object(server, "_runtime_session_state", return_value=state):
            with patch.object(server, "_journal") as journal:
                journal.get_last_session_summary.return_value = "Previous session summary"
                payload = json.loads(server.get_current_session_journal_summary(max_goals=2))

        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["session_id"], "sess-abc")
        self.assertIn("Previous session summary", payload["summary"])
        journal.get_last_session_summary.assert_called_once_with(max_goals=2)

    def test_dead_tools_removed_from_server(self):
        """Phase 9: approval/plan tools were deleted from server.py."""
        self.assertFalse(hasattr(server, "approve_current_plan"))
        self.assertFalse(hasattr(server, "deny_current_plan"))
        self.assertFalse(hasattr(server, "get_pending_plan"))
        self.assertFalse(hasattr(server, "clear_pending_plan"))
        self.assertFalse(hasattr(server, "clear_approval_state"))
        self.assertFalse(hasattr(server, "reset_transient_runtime_state"))
        self.assertFalse(hasattr(server, "rebuild_pending_plan"))


if __name__ == "__main__":
    unittest.main()
