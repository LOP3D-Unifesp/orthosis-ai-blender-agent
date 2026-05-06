from __future__ import annotations

import json
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

if "bpy" not in sys.modules:
    handlers = types.SimpleNamespace(load_post=[], save_post=[], persistent=lambda fn: fn)
    sys.modules["bpy"] = types.SimpleNamespace(
        app=types.SimpleNamespace(handlers=handlers),
        data=types.SimpleNamespace(filepath=""),
    )

from blender_addon.agent_runtime import AgentRuntime
from blender_addon.runtime.gn_targeting import resolve_canonical_gn_target
from blender_addon.runtime.handlers import TurnContext
from blender_addon.runtime.handlers import _agent_loop
from blender_addon.runtime.router import ClassifierMeta, TurnClass
from blender_addon.session.schema import Session


class CanonicalGnTargetResolverTests(unittest.TestCase):
    def test_explicit_tree_target(self) -> None:
        session = Session()
        hosts = [
            {"object": "Foot", "modifier": "Geometry Nodes", "node_group": "Geometry Nodes"},
            {"object": "Foot", "modifier": "Geometry Nodes.001", "node_group": "Biomodelo"},
        ]

        result = resolve_canonical_gn_target(
            message="inspecione a árvore Biomodelo",
            session=session,
            gn_hosts=hosts,
            scene_summary=None,
            local_scope=None,
        )

        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["source"], "explicit")
        self.assertTrue(result["explicit"])
        self.assertEqual(result["target"]["tree_name"], "Biomodelo")

    def test_inferred_active_object_target(self) -> None:
        session = Session()
        hosts = [
            {"object": "Armature", "modifier": "Geometry Nodes", "node_group": "Geometry Nodes"},
            {"object": "FootMesh", "modifier": "GN_Biomodelo", "node_group": "Biomodelo"},
        ]

        result = resolve_canonical_gn_target(
            message="analise os nós",
            session=session,
            gn_hosts=hosts,
            scene_summary={"active_object": "FootMesh"},
            local_scope=None,
        )

        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["source"], "active_object")
        self.assertEqual(result["target"]["object"], "FootMesh")
        self.assertEqual(result["target"]["tree_name"], "Biomodelo")

    def test_multiple_gn_hosts_present_stays_ambiguous(self) -> None:
        session = Session()
        hosts = [
            {"object": "ObjA", "modifier": "Geometry Nodes", "node_group": "Geometry Nodes"},
            {"object": "ObjB", "modifier": "Geometry Nodes.001", "node_group": "Biomodelo"},
        ]

        result = resolve_canonical_gn_target(
            message="analise os nós",
            session=session,
            gn_hosts=hosts,
            scene_summary={"active_object": ""},
            local_scope=None,
        )

        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(len(result["candidates"]), 2)


class CanonicalGnToolInputTests(unittest.TestCase):
    def _runtime_stub(self, session: Session):
        rt = SimpleNamespace(
            journal=SimpleNamespace(log_runtime_event=MagicMock(), accumulate_tokens=MagicMock()),
            _session_state={},
            _tool_step=0,
            _current_turn_tools=[],
            _session_memory={},
            _structural_index={},
            _halt_execution=False,
            _halt_message="",
            _execute_code_fail_count=0,
            _make_plan_count=0,
            _read_call_counts={},
            _active_v1_session=session,
            _capture_mode=False,
            _canonical_gn_target={"object": "FootMesh", "modifier": "GN_Biomodelo", "tree_name": "Biomodelo"},
            runtime=SimpleNamespace(state_adapter=None),
        )
        rt._update_operational_state_from_tool = lambda **_: None
        rt._format_runtime_tool_result = AgentRuntime._format_runtime_tool_result
        rt._postprocess_tool = AgentRuntime._postprocess_tool.__get__(rt, type(rt))
        rt._execute_tool = AgentRuntime._execute_tool.__get__(rt, type(rt))
        return rt

    def test_get_node_context_success_with_canonical_target(self) -> None:
        session = Session()
        runtime = self._runtime_stub(session)

        with patch("blender_addon.agent_runtime.dispatch_tool_raw") as dispatch:
            dispatch.return_value = {
                "status": "success",
                "result": {"tree_name": "Biomodelo", "target_node": "Scale", "nodes": [], "links": []},
            }
            result = runtime._execute_tool("get_node_context", {"node_name": "Scale"}, 0)

        dispatch.assert_called_once()
        called_input = dispatch.call_args.args[1]
        self.assertEqual(called_input["tree_name"], "Biomodelo")
        self.assertEqual(called_input["node_name"], "Scale")
        self.assertNotIn("BLOCKED", result)


class CanonicalGnAmbiguityHandlerTests(unittest.TestCase):
    class _Runtime:
        def __init__(self):
            self.journal = SimpleNamespace(log_runtime_event=MagicMock(), accumulate_tokens=MagicMock())
            self._canonical_gn_target = None
            self._canonical_gn_target_source = ""
            self._local_scope = {}
            self._messages = []

        def _execute_tool(self, name: str, tool_input: dict, _api_elapsed_ms: int) -> str:
            if name == "get_gn_hosts":
                return json.dumps(
                    {
                        "gn_hosts": [
                            {"object": "ObjA", "modifier": "Geometry Nodes", "node_group": "Geometry Nodes"},
                            {"object": "ObjB", "modifier": "Geometry Nodes.001", "node_group": "Biomodelo"},
                        ]
                    }
                )
            if name == "get_scene_summary":
                return json.dumps({"active_object": ""})
            raise AssertionError(f"Unexpected tool call: {name}")

        def _agent_loop(self, system: str, messages: list[dict], max_tokens: int = 4096, excluded_tools=None) -> str:
            raise AssertionError("Agent loop should not run when canonical target is ambiguous.")

    def test_ambiguity_path_asks_clarification(self) -> None:
        runtime = self._Runtime()
        session = Session()
        ctx = TurnContext(
            session=session,
            message="analise isso",
            meta=ClassifierMeta(turn_class=TurnClass.DIAGNOSIS),
            blend_path="",
            _runtime=runtime,
            knowledge_dir=Path("missing") / "domain",
        )

        result = _agent_loop.handle(ctx, "diagnosis")

        self.assertIn("Qual deles devo usar", result.response_text)
        self.assertIn("ObjA / Geometry Nodes / Geometry Nodes", result.response_text)
        self.assertIsNone(runtime._canonical_gn_target)


if __name__ == "__main__":
    unittest.main()
