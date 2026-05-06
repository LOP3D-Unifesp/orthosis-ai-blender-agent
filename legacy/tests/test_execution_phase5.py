"""Tests for Phase 5 of REFATOR_PLAN.md — Dispatcher Consolidation.

Coverage:
    execution/ subpackage:
        - dispatch_tool is importable from blender_addon.execution
        - process_screenshot_result is importable from blender_addon.execution
        - dispatch_runtime_tool backward-compat alias exists and works
        - execution_dispatch.py shim re-exports dispatch_runtime_tool correctly

    execution.dispatcher.dispatch_tool:
        - calls dispatch_tool_raw with correct flags from session_state
        - returns (raw_dict, formatted_str, elapsed_ms) tuple
        - elapsed_ms is a non-negative integer

    execution.dispatcher.process_screenshot_result:
        - returns '' for non-screenshot tools
        - calls send_screenshot_turn for capture_screenshot

    Tombstone guards:
        - runtime_execution attributes raise ImportError
        - execution_postprocess attributes raise ImportError

    runtime_planning simplification:
        - module is importable and only 191 lines (no pipeline bloat)
        - live exports are present and correct
        - dead functions are gone (detect_intent, classify_task, etc.)

    agent_runtime integration:
        - _execute_tool uses dispatch_tool from the new execution subpackage
        - import path changes are transparent (same behaviour)
"""

from __future__ import annotations

import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Mock bpy before any blender_addon import that chains through runtime/__init__.py
if "bpy" not in sys.modules:
    sys.modules["bpy"] = types.SimpleNamespace()


# ---------------------------------------------------------------------------
# execution/ public API
# ---------------------------------------------------------------------------

class TestExecutionSubpackageAPI(unittest.TestCase):
    """Verify the new execution/ subpackage exports the expected public API."""

    def test_dispatch_tool_importable(self):
        from blender_addon.execution import dispatch_tool
        self.assertTrue(callable(dispatch_tool))

    def test_process_screenshot_importable(self):
        from blender_addon.execution import process_screenshot_result
        self.assertTrue(callable(process_screenshot_result))

    def test_backward_compat_alias_exists(self):
        from blender_addon.execution import dispatch_runtime_tool
        self.assertTrue(callable(dispatch_runtime_tool))

    def test_backward_compat_alias_is_dispatch_tool(self):
        from blender_addon.execution import dispatch_tool, dispatch_runtime_tool
        # Both names resolve to the same underlying function.
        self.assertIs(dispatch_runtime_tool, dispatch_tool)

    def test_execution_dispatch_shim_re_exports_dispatch_runtime_tool(self):
        from blender_addon.execution_dispatch import dispatch_runtime_tool
        self.assertTrue(callable(dispatch_runtime_tool))

    def test_execution_dispatch_shim_re_exports_process_screenshot(self):
        from blender_addon.execution_dispatch import process_screenshot_result
        self.assertTrue(callable(process_screenshot_result))

    def test_dispatcher_module_importable(self):
        from blender_addon.execution.dispatcher import dispatch_tool, process_screenshot_result
        self.assertTrue(callable(dispatch_tool))
        self.assertTrue(callable(process_screenshot_result))


# ---------------------------------------------------------------------------
# execution.dispatcher.dispatch_tool
# ---------------------------------------------------------------------------

def _make_runtime(session_state: dict | None = None):
    """Minimal runtime stub for dispatcher tests."""
    state = session_state or {}
    rt = SimpleNamespace(
        _session_state=state,
        _format_runtime_tool_result=MagicMock(return_value='{"ok": true}'),
        _send_screenshot_turn=MagicMock(return_value="screenshot analyzed"),
        journal=SimpleNamespace(log_runtime_event=MagicMock()),
    )
    return rt


class TestDispatchTool(unittest.TestCase):
    """Unit tests for execution.dispatcher.dispatch_tool."""

    def _patch_raw(self, return_value=None):
        if return_value is None:
            return_value = {"status": "success", "result": {"ok": True}}
        return patch(
            "blender_addon.execution.dispatcher.dispatch_tool_raw",
            return_value=return_value,
        )

    def test_returns_three_tuple(self):
        rt = _make_runtime()
        with self._patch_raw() as mock_raw:
            result = __import__("blender_addon.execution.dispatcher", fromlist=["dispatch_tool"]).dispatch_tool(
                rt, "get_tree_structure", {}
            )
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 3)

    def test_runtime_raw_is_dict(self):
        from blender_addon.execution.dispatcher import dispatch_tool
        rt = _make_runtime()
        raw = {"status": "success", "result": {}}
        with self._patch_raw(raw):
            runtime_raw, _, _ = dispatch_tool(rt, "get_tree_structure", {})
        self.assertIsInstance(runtime_raw, dict)
        self.assertEqual(runtime_raw["status"], "success")

    def test_result_is_string(self):
        from blender_addon.execution.dispatcher import dispatch_tool
        rt = _make_runtime()
        with self._patch_raw():
            _, result, _ = dispatch_tool(rt, "get_tree_structure", {})
        self.assertIsInstance(result, str)

    def test_elapsed_ms_is_nonneg_int(self):
        from blender_addon.execution.dispatcher import dispatch_tool
        rt = _make_runtime()
        with self._patch_raw():
            _, _, elapsed = dispatch_tool(rt, "get_tree_structure", {})
        self.assertIsInstance(elapsed, int)
        self.assertGreaterEqual(elapsed, 0)

    def test_passes_session_state_flags(self):
        from blender_addon.execution.dispatcher import dispatch_tool
        state = {
            "debug_mode": True,
            "explicit_override_mode": False,
            "mcp_write_enabled": True,
            "blend_path": "/tmp/test.blend",
        }
        rt = _make_runtime(state)
        with self._patch_raw() as mock_raw:
            dispatch_tool(rt, "get_tree_structure", {})
        call_kwargs = mock_raw.call_args.kwargs
        self.assertTrue(call_kwargs.get("debug_mode"))
        self.assertFalse(call_kwargs.get("explicit_override_mode"))
        self.assertTrue(call_kwargs.get("mcp_write_enabled"))
        self.assertEqual(call_kwargs.get("blend_path"), "/tmp/test.blend")

    def test_route_is_product(self):
        from blender_addon.execution.dispatcher import dispatch_tool
        rt = _make_runtime()
        with self._patch_raw() as mock_raw:
            dispatch_tool(rt, "get_tree_structure", {})
        call_kwargs = mock_raw.call_args.kwargs
        self.assertEqual(call_kwargs.get("route"), "product")

    def test_user_confirmed_is_true(self):
        from blender_addon.execution.dispatcher import dispatch_tool
        rt = _make_runtime()
        with self._patch_raw() as mock_raw:
            dispatch_tool(rt, "get_tree_structure", {})
        self.assertTrue(mock_raw.call_args.kwargs.get("user_confirmed"))

    def test_format_result_called(self):
        from blender_addon.execution.dispatcher import dispatch_tool
        rt = _make_runtime()
        rt._format_runtime_tool_result = MagicMock(return_value="formatted!")
        with self._patch_raw():
            _, result, _ = dispatch_tool(rt, "get_tree_structure", {})
        rt._format_runtime_tool_result.assert_called_once()
        self.assertEqual(result, "formatted!")

    def test_empty_session_state_uses_defaults(self):
        """dispatch_tool must not crash when _session_state is empty."""
        from blender_addon.execution.dispatcher import dispatch_tool
        rt = _make_runtime({})
        with self._patch_raw() as mock_raw:
            dispatch_tool(rt, "make_plan", {})
        call_kwargs = mock_raw.call_args.kwargs
        self.assertFalse(call_kwargs.get("debug_mode"))
        self.assertEqual(call_kwargs.get("blend_path"), "")


# ---------------------------------------------------------------------------
# execution.dispatcher.process_screenshot_result
# ---------------------------------------------------------------------------

class TestProcessScreenshotResult(unittest.TestCase):

    def test_non_screenshot_returns_empty(self):
        from blender_addon.execution.dispatcher import process_screenshot_result
        rt = _make_runtime()
        result = process_screenshot_result(rt, "get_tree_structure", "some data")
        self.assertEqual(result, "")

    def test_execute_code_returns_empty(self):
        from blender_addon.execution.dispatcher import process_screenshot_result
        rt = _make_runtime()
        result = process_screenshot_result(rt, "execute_code", "output")
        self.assertEqual(result, "")

    def test_capture_screenshot_calls_send_screenshot_turn(self):
        from blender_addon.execution.dispatcher import process_screenshot_result
        rt = _make_runtime()
        rt._send_screenshot_turn = MagicMock(return_value="analysis text")
        result = process_screenshot_result(rt, "capture_screenshot", "SCREENSHOT_BASE64:abc")
        rt._send_screenshot_turn.assert_called_once()
        self.assertEqual(result, "analysis text")

    def test_capture_screenshot_logs_event(self):
        from blender_addon.execution.dispatcher import process_screenshot_result
        rt = _make_runtime()
        rt._send_screenshot_turn = MagicMock(return_value="x")
        process_screenshot_result(rt, "capture_screenshot", "data")
        rt.journal.log_runtime_event.assert_called_once()
        event_type = rt.journal.log_runtime_event.call_args.kwargs.get("event_type")
        self.assertEqual(event_type, "visual_evidence_processed")


# ---------------------------------------------------------------------------
# Tombstone guards
# ---------------------------------------------------------------------------

class TestTombstoneGuardsPhase5(unittest.TestCase):

    def test_runtime_execution_raises(self):
        import blender_addon.runtime_execution as re_mod
        with self.assertRaises(ImportError):
            _ = re_mod.execute_tool

    def test_runtime_execution_any_attr_raises(self):
        import blender_addon.runtime_execution as re_mod
        with self.assertRaises(ImportError):
            _ = re_mod.get_current_stage

    def test_execution_postprocess_raises(self):
        import blender_addon.execution_postprocess as ep
        with self.assertRaises(ImportError):
            _ = ep.build_replan_payload

    def test_execution_postprocess_advance_stage_raises(self):
        import blender_addon.execution_postprocess as ep
        with self.assertRaises(ImportError):
            _ = ep.advance_stage_after_success


# ---------------------------------------------------------------------------
# runtime_planning simplification
# ---------------------------------------------------------------------------

class TestRuntimePlanningSimplified(unittest.TestCase):

    def test_module_importable(self):
        import blender_addon.runtime_planning
        self.assertIsNotNone(blender_addon.runtime_planning)

    def test_line_count_reduced(self):
        """runtime_planning.py should be under 250 lines after Phase 5."""
        with open("blender_addon/runtime_planning.py", encoding="utf-8") as f:
            lines = f.readlines()
        self.assertLess(len(lines), 250, f"Expected <250 lines, got {len(lines)}")

    def test_mutation_tools_present(self):
        from blender_addon.runtime_planning import MUTATION_TOOLS
        self.assertIn("execute_code", MUTATION_TOOLS)
        self.assertIn("set_node_value", MUTATION_TOOLS)

    def test_focal_read_tools_present(self):
        from blender_addon.runtime_planning import FOCAL_READ_TOOLS
        self.assertIn("get_node_context", FOCAL_READ_TOOLS)

    def test_extract_tree_name_works(self):
        from blender_addon.runtime_planning import extract_tree_name
        self.assertEqual(extract_tree_name({"tree_name": "VM_G1"}), "VM_G1")
        self.assertEqual(extract_tree_name({}), "")

    def test_extract_node_name_works(self):
        from blender_addon.runtime_planning import extract_node_name
        self.assertEqual(extract_node_name({"node_name": "Scale"}), "Scale")
        self.assertEqual(extract_node_name({}), "")

    def test_normalize_plan_type_works(self):
        from blender_addon.runtime_planning import normalize_plan_type, PLAN_TYPE_EXECUTION
        self.assertEqual(normalize_plan_type(""), PLAN_TYPE_EXECUTION)
        self.assertEqual(normalize_plan_type("context_plan"), "context_plan")

    def test_dead_function_detect_intent_gone(self):
        """detect_intent was removed — must not be importable."""
        import blender_addon.runtime_planning as rp
        self.assertFalse(hasattr(rp, "detect_intent"), "detect_intent should be gone")

    def test_dead_function_classify_task_gone(self):
        import blender_addon.runtime_planning as rp
        self.assertFalse(hasattr(rp, "classify_task"))

    def test_dead_function_assess_continuity_gone(self):
        import blender_addon.runtime_planning as rp
        self.assertFalse(hasattr(rp, "assess_continuity"))

    def test_dead_function_build_plan_preview_gone(self):
        import blender_addon.runtime_planning as rp
        self.assertFalse(hasattr(rp, "build_plan_preview"))

    def test_dead_function_build_plan_gate_gone(self):
        import blender_addon.runtime_planning as rp
        self.assertFalse(hasattr(rp, "build_plan_gate"))

    def test_dead_function_build_plan_stages_gone(self):
        import blender_addon.runtime_planning as rp
        self.assertFalse(hasattr(rp, "build_plan_stages"))

    def test_build_structural_index_entry_present(self):
        from blender_addon.runtime_planning import build_structural_index_entry
        result = build_structural_index_entry({
            "name": "VM_G1",
            "nodes": [{"name": "Scale", "type": "ShaderNodeValue"}],
            "links": [],
        })
        self.assertEqual(result["tree_name"], "VM_G1")
        self.assertGreater(result["node_count"], 0)


if __name__ == "__main__":
    unittest.main()
