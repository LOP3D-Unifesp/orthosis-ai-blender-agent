import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

if "bpy" not in sys.modules:
    sys.modules["bpy"] = types.SimpleNamespace()

from blender_addon.agent_runtime import AgentRuntime
from blender_addon.runtime import Runtime
from blender_addon.session import HistoryMessage


def _persist_state(runtime: Runtime, blend_path: str, state: dict) -> None:
    runtime.persist_runtime_state(state, blend_path)


class RuntimeConvergencePhase2Tests(unittest.TestCase):
    def test_runtimebridgecore_is_now_a_runtime_alias(self):
        if "bpy" not in sys.modules:
            sys.modules["bpy"] = types.SimpleNamespace()

        from blender_addon.server import RuntimeBridgeCore

        self.assertIs(RuntimeBridgeCore, Runtime)

    def test_get_session_state_drops_chatgpt_leftover(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(project_root=Path(tmp))

            state = runtime.get_session_state(blend_path="fresh.blend")

            self.assertNotIn("conversation_surface_primary", state)
            self.assertEqual(state.get("backend_session_kind"), "technical_runtime")

    def test_set_modes_does_not_bump_turn_counter(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(project_root=Path(tmp))
            state = runtime.load_runtime_state("demo.blend")
            state["turn_counter"] = 7
            _persist_state(runtime, "demo.blend", state)

            updated = runtime.set_modes(
                blend_path="demo.blend",
                debug_mode=True,
                control_source="mcp",
            )

            self.assertEqual(int(updated.get("turn_counter", 0)), 7)
            self.assertTrue(bool(updated.get("debug_mode", False)))

    def test_runtime_state_persist_updates_structured_session_v1_without_legacy_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(project_root=Path(tmp))
            state = runtime.load_runtime_state("demo.blend")
            state["debug_mode"] = True
            state["explicit_override_mode"] = True
            state["mcp_write_enabled"] = True
            state["last_target_tree"] = "VM_Tree"
            state["current_plan_id"] = "plan-1"
            state["current_plan_type"] = "execution_plan"
            state["presented_plan_type"] = "execution_plan"
            state["approval_required"] = True
            state["approval_status"] = "pending"
            state["presented_plan_summary"] = "Set VM_G1_Scale to 1.0."
            state["presented_plan_tools"] = ["set_node_value"]
            runtime.state_adapter.append_chat_history(state, role="user", text="ajuste a escala")
            _persist_state(runtime, "demo.blend", state)

            session = runtime.v1_session_for("demo.blend")

            self.assertEqual(session.focus.tree_name, "VM_Tree")
            self.assertTrue(session.ui_state.debug_mode)
            self.assertTrue(session.ui_state.explicit_override_mode)
            self.assertTrue(session.ui_state.mcp_write_enabled)
            self.assertEqual(session.history.messages[-1].content, "ajuste a escala")
            self.assertEqual(session.execution_state.phase, "awaiting_confirmation")
            self.assertIsNotNone(session.execution_state.pending_mutation)
            self.assertEqual(
                session.execution_state.pending_mutation.description,
                "Set VM_G1_Scale to 1.0.",
            )
            self.assertFalse(runtime.state_adapter._session_path("demo.blend").exists())

    def test_get_session_state_and_flat_adapter_are_projected_from_v1(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(project_root=Path(tmp))
            session = runtime.v1_session_for("demo.blend")
            session.update_focus(tree_name="VM_Tree")
            session.ui_state.debug_mode = True
            session.ui_state.session_active = True
            session.operational_state.session_memory = {"target_tree": "VM_Tree"}
            session.operational_state.recent_actions = [{"tool_name": "get_scene_summary", "status": "ok"}]
            session.history.messages.append(
                HistoryMessage(role="assistant", content="memoria v1", turn_class="diagnosis")
            )
            runtime.save_v1_session(session)

            state = runtime.get_session_state(blend_path="demo.blend")

            self.assertTrue(bool(state.get("debug_mode", False)))
            self.assertTrue(bool(state.get("agent_session_active", False)))
            self.assertEqual(state.get("last_target_tree"), "VM_Tree")
            self.assertEqual(state.get("session_memory", {}).get("target_tree"), "VM_Tree")
            self.assertEqual(state.get("recent_actions", [])[0]["tool_name"], "get_scene_summary")

            runtime_state = runtime.load_runtime_state("demo.blend")
            self.assertTrue(bool(runtime_state.get("debug_mode", False)))
            self.assertEqual(str(runtime_state.get("last_target_tree", "") or ""), "VM_Tree")
            self.assertEqual(runtime_state.get("session_memory", {}).get("target_tree"), "VM_Tree")
            self.assertEqual(runtime_state.get("chat_history", [])[-1]["text"], "memoria v1")
            self.assertFalse(runtime.state_adapter._session_path("demo.blend").exists())

    def test_same_session_sync_preserves_v1_history_when_legacy_is_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(project_root=Path(tmp))
            state = runtime.load_runtime_state("demo.blend")
            runtime.state_adapter.begin_new_session(state)
            _persist_state(runtime, "demo.blend", state)

            session = runtime.v1_session_for("demo.blend")
            session.ui_state.advanced_open = True
            session.lifecycle.add_note("keep this note")
            session.history.messages.append(
                HistoryMessage(role="assistant", content="memoria v1", turn_class="diagnosis")
            )
            runtime.save_v1_session(session)

            legacy_minimal = {
                "session_id": session.identity.session_id,
                "blend_path": "demo.blend",
            }
            runtime._sync_v1_session("demo.blend", legacy_minimal)

            reloaded = runtime.v1_session_for("demo.blend")
            self.assertEqual(reloaded.history.messages[-1].content, "memoria v1")
            self.assertTrue(reloaded.ui_state.advanced_open)
            self.assertIn("keep this note", reloaded.lifecycle.notes)

    def test_same_session_sync_still_merges_legacy_chat_when_it_advances(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(project_root=Path(tmp))
            state = runtime.load_runtime_state("demo.blend")
            runtime.state_adapter.begin_new_session(state)
            _persist_state(runtime, "demo.blend", state)

            session = runtime.v1_session_for("demo.blend")
            session.ui_state.advanced_open = True
            session.lifecycle.add_note("keep this note")
            runtime.save_v1_session(session)

            runtime.state_adapter.append_chat_history(state, role="user", text="ajuste a escala")
            _persist_state(runtime, "demo.blend", state)

            reloaded = runtime.v1_session_for("demo.blend")
            self.assertEqual(reloaded.history.messages[-1].content, "ajuste a escala")
            self.assertTrue(reloaded.ui_state.advanced_open)
            self.assertIn("keep this note", reloaded.lifecycle.notes)

    def test_set_modes_can_end_v1_backed_session_without_legacy_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(project_root=Path(tmp))
            session = runtime.v1_session_for("demo.blend")
            session.ui_state.session_active = True
            session.update_focus(tree_name="VM_Tree")
            runtime.save_v1_session(session)

            updated = runtime.set_modes(blend_path="demo.blend", agent_session_active=False)

            self.assertFalse(bool(updated.get("agent_session_active", False)))
            self.assertEqual(updated.get("last_target_tree"), "")
            self.assertFalse(runtime.v1_session_for("demo.blend").ui_state.session_active)

    def test_set_modes_start_new_session_reanchors_from_v1_backed_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(project_root=Path(tmp))
            session = runtime.v1_session_for("demo.blend")
            session.ui_state.session_active = True
            runtime.save_v1_session(session)
            old_session_id = session.identity.session_id

            updated = runtime.set_modes(
                blend_path="demo.blend",
                start_new_session=True,
                agent_session_active=True,
            )

            reloaded = runtime.v1_session_for("demo.blend")
            self.assertNotEqual(updated.get("session_id"), old_session_id)
            self.assertEqual(reloaded.identity.session_id, updated.get("session_id"))
            self.assertTrue(reloaded.ui_state.session_active)

    def test_agent_runtime_can_share_runtime_foundation(self):
        fake_anthropic = types.SimpleNamespace(
            Anthropic=lambda api_key: types.SimpleNamespace(api_key=api_key)
        )

        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(project_root=Path(tmp))
            with patch.dict(sys.modules, {"anthropic": fake_anthropic}):
                agent = AgentRuntime(
                    project_root=Path(tmp),
                    api_key="test-key",
                    runtime=runtime,
                )

        self.assertIs(agent.runtime, runtime)
        self.assertIs(agent.state_adapter, runtime.state_adapter)
        self.assertIs(agent.session, runtime.state_adapter)
        self.assertIs(agent.journal, runtime.journal)
        self.assertIs(agent.dispatcher, runtime.dispatcher)
        self.assertEqual(agent.client.api_key, "test-key")


if __name__ == "__main__":
    unittest.main()
