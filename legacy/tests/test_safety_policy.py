import unittest

from blender_addon.safety_policy import SafetyContext, classify_safety_level, evaluate_tool_call


class SafetyPolicyTests(unittest.TestCase):
    def test_auto_apply_read_tool(self):
        ctx = SafetyContext(route="product")
        decision = evaluate_tool_call("get_scene_summary", ctx, {})
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.level, "auto_apply")

    def test_mcp_blocks_mutation_when_read_only(self):
        ctx = SafetyContext(route="mcp", mcp_write_enabled=False)
        decision = evaluate_tool_call("create_node", ctx, {})
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.level, "confirm_then_apply")

    def test_execute_code_escalates_when_risky(self):
        level = classify_safety_level("execute_code", {"code": "bpy.ops.wm.save_mainfile()"})
        self.assertEqual(level, "explicit_override")

    def test_execute_code_non_risky_confirm_level(self):
        level = classify_safety_level("execute_code", {"code": "print('ok')"})
        self.assertEqual(level, "confirm_then_apply")


if __name__ == "__main__":
    unittest.main()

