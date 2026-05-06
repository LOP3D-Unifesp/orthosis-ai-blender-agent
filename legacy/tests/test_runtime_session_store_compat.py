import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch, sentinel

if "bpy" not in sys.modules:
    sys.modules["bpy"] = types.SimpleNamespace()

from blender_addon.runtime import Runtime


def _persist_state(runtime: Runtime, blend_path: str, state: dict) -> None:
    runtime.persist_runtime_state(state, blend_path)


class RuntimeSessionStoreCompatTests(unittest.TestCase):
    def test_persist_runtime_state_delegates_to_runtime_persist_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(project_root=Path(tmp))
            state = runtime.load_runtime_state("demo.blend")

            with patch.object(runtime, "_persist_runtime_state", return_value=sentinel.saved_path) as persist:
                result = runtime.persist_runtime_state(state, "demo.blend")

            self.assertIs(result, sentinel.saved_path)
            persist.assert_called_once_with(
                "demo.blend",
                state,
                canonical_tool=None,
                raw=None,
                tool_input=None,
            )

    def test_runtime_internal_paths_use_explicit_runtime_state_helpers(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Runtime(project_root=Path(tmp))
            state = runtime.load_runtime_state("demo.blend")
            state["debug_mode"] = True
            _persist_state(runtime, "demo.blend", state)

            updated = runtime.set_modes(
                blend_path="demo.blend",
                explicit_override_mode=True,
                control_source="mcp",
            )

            self.assertTrue(bool(updated.get("debug_mode", False)))
            self.assertTrue(bool(updated.get("explicit_override_mode", False)))

            with patch.object(runtime.dispatcher, "execute", return_value={"status": "success", "result": {"objects": []}}):
                result = runtime.execute_tool_call(
                    tool_name="get_scene_summary",
                    tool_input={},
                    blend_path="demo.blend",
                )

            self.assertEqual(result.get("status"), "success")
            persisted = runtime.v1_session_for("demo.blend")
            self.assertTrue(persisted.ui_state.explicit_override_mode)


if __name__ == "__main__":
    unittest.main()
