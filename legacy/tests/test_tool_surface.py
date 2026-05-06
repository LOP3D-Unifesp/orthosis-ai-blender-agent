import sys
import types
import unittest
from unittest.mock import patch

# Mock bpy before importing blender_addon modules outside Blender.
if "bpy" not in sys.modules:
    _handlers = types.SimpleNamespace(load_post=[], persistent=lambda fn: fn)
    sys.modules["bpy"] = types.SimpleNamespace(
        app=types.SimpleNamespace(handlers=_handlers),
        data=types.SimpleNamespace(filepath=""),
    )

from blender_addon.tools import TOOLS, dispatch_tool_raw


class ToolSurfaceTests(unittest.TestCase):
    def test_make_plan_present(self):
        names = [tool["name"] for tool in TOOLS]
        self.assertIn("make_plan", names)

    def test_required_runtime_tools_present(self):
        names = {tool["name"] for tool in TOOLS}
        required = {
            "get_scene_summary",
            "get_gn_hosts",
            "get_node_context",
            "get_selected_nodes_context",
            "get_active_frame_context",
            "get_local_subgraph_context",
            "get_changes_since_last_turn",
            "get_tree_parameters",
            "capture_screenshot",
            "execute_code",
            "analyze_scene",
            "query_node_types",
            "apply_simulator_payload",
        }
        self.assertTrue(required.issubset(names))

    def test_execute_code_description_mentions_fresh_namespace(self):
        execute_code = next(tool for tool in TOOLS if tool["name"] == "execute_code")
        self.assertIn("fresh Python namespace", execute_code["description"])

    def test_removed_heavy_or_legacy_tools_not_exposed(self):
        names = {tool["name"] for tool in TOOLS}
        self.assertNotIn("analyze_gn_state", names)
        self.assertNotIn("build_gn_graph", names)

    def test_dispatch_tool_raw_forwards_runtime_mode_flags(self):
        captured = {}

        def _fake_call(payload, **kwargs):
            _ = kwargs
            captured.update(payload)
            return {"status": "success", "result": {}}

        with patch("blender_addon.tools.call_blender_socket", side_effect=_fake_call):
            dispatch_tool_raw(
                "execute_code",
                {"code": "print('ok')"},
                route="product",
                output_mode="compact",
                user_confirmed=True,
                debug_mode=True,
                explicit_override_mode=True,
                mcp_write_enabled=False,
                blend_path="C:/tmp/test.blend",
            )

        self.assertEqual(captured.get("debug_mode"), True)
        self.assertEqual(captured.get("explicit_override_mode"), True)
        self.assertEqual(captured.get("mcp_write_enabled"), False)
        self.assertEqual(captured.get("blend_path"), "C:/tmp/test.blend")


if __name__ == "__main__":
    unittest.main()
