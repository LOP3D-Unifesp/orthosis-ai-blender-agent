import unittest

from blender_addon.simulator_mapper import build_gn_ops_from_simulator_payload


class SimulatorMapperTests(unittest.TestCase):
    def test_build_ops_with_defaults(self):
        ops = build_gn_ops_from_simulator_payload(
            tree_name="GN_Main",
            payload={
                "wrist_circumference_mm": 160,
                "orthosis_length_mm": "220.5",
            },
        )
        self.assertGreaterEqual(len(ops), 2)
        first = ops[0]
        self.assertEqual(first["op"], "set_node_value")
        self.assertIn("node", first["params"])
        self.assertIn("socket", first["params"])

    def test_strict_mode_raises_for_missing_keys(self):
        with self.assertRaises(ValueError):
            build_gn_ops_from_simulator_payload(
                tree_name="GN_Main",
                payload={},
                strict=True,
            )

    def test_custom_mapping(self):
        ops = build_gn_ops_from_simulator_payload(
            tree_name="GN_Main",
            payload={"x": 12},
            mapping={"x": ["NodeA", "InputA"]},
        )
        self.assertEqual(len(ops), 1)
        self.assertEqual(ops[0]["params"]["node"], "NodeA")


if __name__ == "__main__":
    unittest.main()

