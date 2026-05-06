import unittest

from blender_addon.fast_path import _try_simple_read


class _RuntimeStub:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def _execute_tool(self, tool_name, tool_input, api_elapsed_ms):
        self.calls.append((tool_name, tool_input, api_elapsed_ms))
        return self.result


class FastPathTests(unittest.TestCase):
    def test_simple_read_accepts_valid_json_that_mentions_error(self):
        runtime = _RuntimeStub('{"summary":"error budget node","node":"VM_G1_Scale"}')

        result = _try_simple_read("mostra VM_G1_Scale", runtime)

        self.assertIsNotNone(result)
        self.assertEqual(result[1]["fp_type"], "read")

    def test_simple_read_rejects_explicit_error_text(self):
        runtime = _RuntimeStub("ERROR: Node not found")

        result = _try_simple_read("mostra VM_G1_Scale", runtime)

        self.assertIsNone(result)

    def test_simple_read_rejects_structured_blocked_envelope(self):
        runtime = _RuntimeStub('{"status":"blocked","error":"safety gate"}')

        result = _try_simple_read("mostra VM_G1_Scale", runtime)

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
