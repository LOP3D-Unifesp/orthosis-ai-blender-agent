import tempfile
import unittest
from pathlib import Path

from blender_addon.session_store import SessionStore


class SessionStoreTests(unittest.TestCase):
    def test_default_state_contains_operational_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(project_root=Path(tmp))
            state = store.load("demo.blend")
            self.assertIn("agent_session_active", state)
            self.assertIn("current_plan_id", state)
            self.assertIn("approval_token", state)
            self.assertIn("session_memory", state)
            self.assertIn("structural_index", state)
            self.assertIn("local_scope", state)

    def test_legacy_workflow_fields_are_removed_on_normalize(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(project_root=Path(tmp))
            state = store.load("demo.blend")
            state["workflow_mode"] = "assisted_execution"
            state["pending_approval"] = True
            state["pending_approval_scope"] = "mutation_plan"
            store.save(state, "demo.blend")
            loaded = store.load("demo.blend")
            self.assertNotIn("workflow_mode", loaded)
            self.assertNotIn("pending_approval", loaded)
            self.assertNotIn("pending_approval_scope", loaded)

    def test_session_memory_incremental_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(project_root=Path(tmp))
            state = store.load("demo.blend")
            store.update_session_memory(
                state,
                {
                    "target_tree": "GN_Teste",
                    "relevant_nodes": ["A", "B"],
                    "decisions": ["route_local_scope"],
                },
            )
            store.update_session_memory(
                state,
                {
                    "relevant_nodes": ["B", "C"],
                    "last_parameter_changes": [{"node": "A", "field": "Value"}],
                },
            )
            self.assertEqual(state["session_memory"]["target_tree"], "GN_Teste")
            self.assertEqual(state["session_memory"]["relevant_nodes"], ["A", "B", "C"])
            self.assertEqual(len(state["session_memory"]["last_parameter_changes"]), 1)

    def test_chat_history_is_enabled_by_default_for_blender_ui(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(project_root=Path(tmp))
            state = store.load("demo.blend")
            self.assertTrue(bool(state.get("legacy_chat_history_enabled", False)))
            store.append_chat_history(state, role="user", text="hello")
            self.assertEqual(len(state.get("chat_history", [])), 1)

    def test_legacy_chat_history_can_be_enabled_for_transition(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(project_root=Path(tmp))
            state = store.load("demo.blend")
            store.set_legacy_chat_history_enabled(state, True)
            store.append_chat_history(state, role="user", text="hello")
            self.assertEqual(len(state.get("chat_history", [])), 1)

    def test_chat_history_preserves_longer_messages_for_session_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(project_root=Path(tmp))
            state = store.load("demo.blend")
            long_text = "abc123 " * 1500
            store.append_chat_history(state, role="assistant", text=long_text)
            self.assertGreater(len(state.get("chat_history", [])[0]["text"]), 10000)

    def test_control_owner_lock_blocks_other_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(project_root=Path(tmp))
            state = store.load("demo.blend")
            ok, owner = store.claim_control_owner(state, "chat_ui", lock=True)
            self.assertTrue(ok)
            self.assertEqual(owner, "chat_ui")
            self.assertFalse(store.can_write_control(state, "mcp"))
            self.assertTrue(store.can_write_control(state, "chat_ui"))

    def test_force_claim_can_takeover_locked_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(project_root=Path(tmp))
            state = store.load("demo.blend")
            store.claim_control_owner(state, "chat_ui", lock=True)
            ok, owner = store.claim_control_owner(state, "mcp", lock=True, force=True)
            self.assertTrue(ok)
            self.assertEqual(owner, "mcp")

    def test_clear_pending_plan_and_approval_state_helpers(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(project_root=Path(tmp))
            state = store.load("demo.blend")
            state["agent_session_active"] = True
            state["current_plan_id"] = "plan-123"
            state["current_plan_status"] = "approved"
            state["approval_required"] = True
            state["approval_token"] = "appr-123"
            state["approval_status"] = "granted"
            state["presented_plan_stages"] = [{"stage_id": "stage-1"}]
            state["current_stage_id"] = "stage-1"
            state["current_stage_index"] = 0
            state["current_stage_status"] = "approved"

            store.clear_approval_state(state)
            self.assertFalse(state["approval_required"])
            self.assertEqual(state["approval_status"], "none")
            self.assertEqual(state["current_plan_status"], "presented")

            store.clear_pending_plan(state)
            self.assertEqual(state["current_plan_id"], "")
            self.assertEqual(state["current_plan_status"], "none")
            self.assertEqual(state["presented_plan_stages"], [])
            self.assertEqual(state["current_stage_id"], "")
            self.assertEqual(state["current_stage_index"], -1)

    def test_reset_transient_state_does_not_drop_plan_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(project_root=Path(tmp))
            state = store.load("demo.blend")
            state["agent_session_active"] = True
            state["current_plan_id"] = "plan-123"
            state["presented_plan_summary"] = "summary"
            state["presented_plan_stages"] = [{"stage_id": "stage-1"}]
            state["current_stage_id"] = "stage-1"
            state["current_stage_index"] = 0
            state["current_stage_status"] = "approved"
            state["last_replan"] = {"x": 1}
            state["last_failure"] = "error"
            state["execution_plan_id"] = "plan-123"

            store.reset_transient_state(state)
            self.assertEqual(state["presented_plan_summary"], "summary")
            self.assertEqual(state["presented_plan_stages"], [{"stage_id": "stage-1"}])
            self.assertEqual(state["current_stage_status"], "pending")
            self.assertEqual(state["last_replan"], {})
            self.assertEqual(state["last_failure"], "")
            self.assertEqual(state["execution_plan_id"], "")


if __name__ == "__main__":
    unittest.main()
