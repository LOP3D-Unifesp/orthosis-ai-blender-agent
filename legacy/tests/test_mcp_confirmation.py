import unittest

from mcp_policy import resolve_user_confirmation


class McpConfirmationTests(unittest.TestCase):
    def test_structured_mutation_auto_confirms_when_unspecified(self):
        self.assertTrue(resolve_user_confirmation("create_node", None))
        self.assertTrue(resolve_user_confirmation("build_gn_graph", None))
        self.assertTrue(resolve_user_confirmation("apply_simulator_payload", None))

    def test_execute_code_remains_explicit(self):
        self.assertFalse(resolve_user_confirmation("execute_code", None))
        self.assertFalse(resolve_user_confirmation("execute_code", False))
        self.assertTrue(resolve_user_confirmation("execute_code", True))

    def test_read_tools_not_auto_confirmed(self):
        self.assertFalse(resolve_user_confirmation("get_scene_summary", None))
        self.assertFalse(resolve_user_confirmation("analyze_scene", None))


if __name__ == "__main__":
    unittest.main()

