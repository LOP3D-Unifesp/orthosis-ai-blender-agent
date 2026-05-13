"""Smoke tests for the slim single-handler dispatch surface."""

from __future__ import annotations

import sys
import types
import unittest
import importlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch


def _install_fake_bpy():
    bpy = types.ModuleType("bpy")
    bpy.app = types.SimpleNamespace(
        handlers=types.SimpleNamespace(persistent=lambda fn: fn, load_post=[], save_post=[]),
        timers=types.SimpleNamespace(register=lambda fn: fn()),
    )
    bpy.data = types.SimpleNamespace(filepath="")
    sys.modules["bpy"] = bpy


_install_fake_bpy()


def _install_fake_anthropic():
    anthropic = types.ModuleType("anthropic")
    anthropic.Anthropic = lambda api_key=None: types.SimpleNamespace(api_key=api_key)
    sys.modules["anthropic"] = anthropic


_install_fake_anthropic()

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))


@dataclass
class _FakeExecutionState:
    phase: str = "idle"
    current_draft: Any = None
    pending_user_decision: Any = None
    session_state: str = "IDLE"
    retry_requires_draft_change: bool = False
    pending_draft_action: str = ""
    draft_revision: int = 0
    drafting_mode: bool = False

    def set_phase(self, phase: str):
        self.phase = phase

    def set_work_cycle_phase(self, phase: str):
        self.work_cycle_phase = phase


@dataclass
class _FakeHistory:
    messages: list = field(default_factory=list)


@dataclass
class _FakeIdentity:
    session_id: str = "test-session"


@dataclass
class _FakeOperationalState:
    session_memory: dict[str, Any] = field(default_factory=dict)
    tree_structural_memory: dict[str, Any] = field(default_factory=dict)
    tree_change_markers: dict[str, Any] = field(default_factory=dict)
    local_scope: dict[str, Any] = field(default_factory=dict)
    structural_index: dict[str, Any] = field(default_factory=dict)


@dataclass
class _FakeSession:
    identity: _FakeIdentity = field(default_factory=_FakeIdentity)
    execution_state: _FakeExecutionState = field(default_factory=_FakeExecutionState)
    history: _FakeHistory = field(default_factory=_FakeHistory)
    operational_state: _FakeOperationalState = field(default_factory=_FakeOperationalState)
    focus: Any = field(default_factory=lambda: types.SimpleNamespace(
        blend_path="",
        object_name=None,
        modifier_name=None,
        tree_name=None,
    ))
    baseline_workspace: Any = None


class _FakeJournal:
    def __init__(self):
        self.events: list[tuple[str, dict[str, Any], str]] = []

    def start_run(self, **_kwargs):
        return None

    def log_runtime_event(self, event_type: str, payload: dict[str, Any] | None = None, status: str = "info"):
        self.events.append((event_type, dict(payload or {}), status))


class _FakeRuntimeForAgentTurn:
    def __init__(self, session: _FakeSession):
        self.project_root = _PROJECT_ROOT
        self.journal = _FakeJournal()
        self.dispatcher = types.SimpleNamespace()
        self.session = session
        self.saved_sessions: list[_FakeSession] = []
        self.chat_messages: list[tuple[str, str, str]] = []

    def v1_session_for(self, _blend_path: str):
        return self.session

    def read_persisted_session_state(self, _session_id: str):
        return ""

    def load_runtime_state(self, _blend_path: str):
        return {}

    def append_chat_message(self, _session_id: str, *, role: str, content: str, turn_class: str):
        self.chat_messages.append((role, content, turn_class))

    def persist_session_state(self, *_args, **_kwargs):
        return None

    def save_v1_session(self, session: _FakeSession):
        self.saved_sessions.append(session)


class SlimHandlerSmokeTests(unittest.TestCase):
    def test_runtime_intent_rules_route_to_single_workspace_modes(self):
        from blender_addon.runtime.router import TurnClass, infer_turn_intent

        session = _FakeSession()
        turn_class, meta, goal_mode = infer_turn_intent(session, "qual o estado da arvore?")
        self.assertEqual(TurnClass.CONTEXT_INQUIRY, turn_class)
        self.assertEqual("inquiry", goal_mode)
        self.assertEqual("inquiry", meta.goal_mode)

        turn_class, meta, goal_mode = infer_turn_intent(
            session,
            "[RESULTADO DE EXECUÇÃO — Revisão v38]\nResultado: FALHOU",
        )
        self.assertEqual(TurnClass.EXECUTION_FEEDBACK, turn_class)
        self.assertEqual("feedback_fix", goal_mode)
        self.assertEqual("feedback_fix", meta.goal_mode)

        session.execution_state.current_draft = types.SimpleNamespace(block_name="GN_Agent_Draft")
        turn_class, meta, goal_mode = infer_turn_intent(
            session,
            "o draft nao foi, tenta escrever novamente",
        )
        self.assertEqual(TurnClass.DRAFT_WORKSPACE, turn_class)
        self.assertEqual("focal_correction", goal_mode)
        self.assertEqual("draft_refinement", meta.turn_intent)

    def test_diagnosis_before_write_routes_read_only_even_with_write_word(self):
        from blender_addon.runtime.router import TurnClass, infer_turn_intent

        session = _FakeSession()
        session.execution_state.current_draft = types.SimpleNamespace(block_name="GN_Agent_Draft")

        turn_class, meta, goal_mode = infer_turn_intent(
            session,
            "Faz um diagnostico geral primeiro, analise a arvore profundamente e pegue todas as certezas que vc precisa antes de escrever.",
        )

        self.assertEqual(TurnClass.DRAFT_WORKSPACE, turn_class)
        self.assertEqual("diagnose_only", goal_mode)
        self.assertEqual("diagnose_only", meta.turn_intent)
        self.assertIn("diagnose_only_request", meta.signals)

    def test_pending_repair_continua_routes_to_read_only_diagnosis(self):
        from blender_addon.runtime.router import TurnClass, infer_turn_intent

        session = _FakeSession()
        session.execution_state.current_draft = types.SimpleNamespace(block_name="GN_Agent_Draft")
        session.execution_state.session_state = "STRATEGY_PROPOSED"
        session.execution_state.pending_user_decision = types.SimpleNamespace(
            status="pending",
            kind="repair_direction",
            options=["sim", "não"],
        )

        turn_class, meta, goal_mode = infer_turn_intent(session, "continua")

        self.assertEqual(TurnClass.DRAFT_WORKSPACE, turn_class)
        self.assertEqual("diagnose_only", goal_mode)
        self.assertEqual("diagnose_only", meta.turn_intent)
        self.assertIn("pending_diagnosis_continuation", meta.signals)

    def test_repair_retry_routes_to_draft_refinement_without_router_regex(self):
        from blender_addon.runtime.router import TurnClass, infer_turn_intent

        session = _FakeSession()
        session.execution_state.current_draft = types.SimpleNamespace(block_name="GN_Agent_Draft")
        session.execution_state.session_state = "REPAIRING"
        session.execution_state.retry_requires_draft_change = True
        session.execution_state.pending_draft_action = "write_confirmed_draft_revision"

        turn_class, meta, goal_mode = infer_turn_intent(session, "ok tenta denovo")

        self.assertEqual(TurnClass.DRAFT_WORKSPACE, turn_class)
        self.assertEqual("focal_correction", goal_mode)
        self.assertEqual("draft_refinement", meta.turn_intent)
        self.assertIn("stateful_retry_request", meta.signals)

    def test_workspace_goal_configs_are_the_live_handler_surface(self):
        from blender_addon.handler.workspace import GOAL_CONFIGS

        self.assertEqual(
            set(GOAL_CONFIGS),
            {"inquiry", "diagnose_only", "focal_correction", "functional_expansion", "feedback_fix"},
        )
        self.assertTrue(GOAL_CONFIGS["inquiry"].read_only)
        self.assertTrue(GOAL_CONFIGS["diagnose_only"].read_only)
        self.assertFalse(GOAL_CONFIGS["focal_correction"].read_only)
        self.assertFalse(GOAL_CONFIGS["functional_expansion"].read_only)
        self.assertTrue(GOAL_CONFIGS["feedback_fix"].read_only)
        self.assertIn("write_script_draft", GOAL_CONFIGS["feedback_fix"].excluded_tools)
        self.assertGreaterEqual(GOAL_CONFIGS["diagnose_only"].max_rounds, 8)
        self.assertGreaterEqual(GOAL_CONFIGS["focal_correction"].max_rounds, 8)
        self.assertGreaterEqual(GOAL_CONFIGS["functional_expansion"].max_rounds, 10)
        self.assertEqual(3, GOAL_CONFIGS["feedback_fix"].focal_budget_min)

    def test_handler_package_no_longer_exports_turn_dispatcher(self):
        import blender_addon.handler as handler

        self.assertFalse(hasattr(handler, "dispatch_turn"))
        self.assertFalse(hasattr(handler, "_workspace_goal_mode"))

    def test_inquiry_handler_uses_single_structural_read_when_refresh_is_needed(self):
        from blender_addon.handler import TurnContext
        from blender_addon.handler.workspace import handle
        from blender_addon.runtime.router import ClassifierMeta, TurnClass

        session = _FakeSession(
            focus=types.SimpleNamespace(tree_name="Biomodelo_GN"),
            baseline_workspace=types.SimpleNamespace(
                structural_summary={},
                stale=True,
                tree_signature="",
                built_at="",
                built_from="",
                semantic_layers=[],
                subgraph_index={},
                recipe_associations=[],
                known_parameters={},
                open_questions=[],
            ),
        )

        class _Runtime:
            def __init__(self):
                self._messages = []
                self._session_memory = {"target_tree": "Biomodelo_GN"}
                self._session_state = {"tree_structural_memory": {}}
                self.journal = types.SimpleNamespace(log_runtime_event=lambda **_: None)
                self.tools = []
                self.model = "fake-model"
                self.tool_calls: list[tuple[str, dict[str, Any]]] = []

            def _execute_tool(self, name, tool_input, _elapsed):
                self.tool_calls.append((name, dict(tool_input)))
                return json.dumps({
                    "status": "success",
                    "result": {
                        "memory": {
                            "tree_name": "Biomodelo_GN",
                            "node_count": 2,
                            "frame_count": 1,
                            "major_regions": [{"name": "Palm", "type": "frame"}],
                            "parameters": {"measures": [{"name": "Palm Width"}]},
                            "marker": {"node_names": ["ORTHOSIS_CONTEXT"], "links": []},
                        }
                    },
                })

            def _agent_loop(self, *_args, **_kwargs):
                return "resposta"

        runtime = _Runtime()
        ctx = TurnContext(
            session=session,
            message="qual a estrutura da arvore?",
            meta=ClassifierMeta(
                turn_class=TurnClass.CONTEXT_INQUIRY,
                goal_mode="inquiry",
                needs_baseline_refresh=True,
            ),
            blend_path="",
            _runtime=runtime,
            knowledge_dir=Path("/nonexistent/knowledge/domain"),
        )

        result = handle(ctx, "inquiry")

        self.assertEqual("resposta", result.response_text)
        self.assertEqual([("build_tree_structural_memory", {"tree_name": "Biomodelo_GN"})], runtime.tool_calls)

    def test_legacy_drafting_support_module_is_removed(self):
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("blender_addon.handler._drafting_support")

    def test_agent_runtime_run_turn_dispatches_to_live_workspace_handler(self):
        from blender_addon.core.runtime import AgentRuntime
        from blender_addon.handler import HandlerResult
        from blender_addon.runtime.router import TurnClass

        session = _FakeSession()
        fake_runtime = _FakeRuntimeForAgentTurn(session)
        agent = AgentRuntime(_PROJECT_ROOT, api_key="test-key", runtime=fake_runtime)

        calls: list[tuple[Any, str]] = []

        def _fake_workspace_handle(ctx, goal_mode: str):
            calls.append((ctx, goal_mode))
            return HandlerResult(response_text="draft path reached")

        with patch("blender_addon.handler.workspace.handle", side_effect=_fake_workspace_handle):
            response = agent.run_turn("cria um draft inicial para a ortese", blend_path="")

        self.assertEqual("draft path reached", response)
        self.assertEqual(1, len(calls))
        ctx, goal_mode = calls[0]
        self.assertEqual("functional_expansion", goal_mode)
        self.assertEqual(TurnClass.DRAFT_WORKSPACE, ctx.meta.turn_class)
        self.assertEqual("functional_expansion", ctx.meta.goal_mode)
        self.assertIs(ctx.session, session)
        self.assertIs(ctx._runtime, agent)
        self.assertEqual(
            [("user", "cria um draft inicial para a ortese", str(TurnClass.DRAFT_WORKSPACE))],
            fake_runtime.chat_messages[:1],
        )

    def test_knowledge_budget_only_tracks_live_intents(self):
        from blender_addon.handler import _KNOWLEDGE_BUDGET_BY_CLASS

        self.assertEqual(
            set(_KNOWLEDGE_BUDGET_BY_CLASS),
            {
                "trivial_chat",
                "context_inquiry",
                "draft_workspace",
                "execution_feedback",
                "state_control",
            },
        )

    def test_runtime_dispatcher_routes_script_draft_tools_through_draft_module(self):
        from blender_addon.tools import draft
        from blender_addon.tools.server_dispatch import RuntimeDispatcher

        dispatcher = RuntimeDispatcher()
        calls: list[tuple[str, dict[str, Any]]] = []

        def _fake_write(tool_input):
            calls.append(("write", dict(tool_input)))
            return {"status": "success", "result": {"block_name": tool_input.get("block_name", "")}}

        def _fake_read(tool_input):
            calls.append(("read", dict(tool_input)))
            return {"status": "success", "result": {"block_name": tool_input.get("block_name", "")}}

        original_write = draft.handle_write_script_draft
        original_read = draft.handle_read_script_draft
        try:
            draft.handle_write_script_draft = _fake_write
            draft.handle_read_script_draft = _fake_read

            write = dispatcher.execute("write_script_draft", {"block_name": "GN_Agent_Draft"})
            read = dispatcher.execute("read_script_draft", {"block_name": "GN_Agent_Draft"})
        finally:
            draft.handle_write_script_draft = original_write
            draft.handle_read_script_draft = original_read

        self.assertEqual("success", write["status"])
        self.assertEqual("success", read["status"])
        self.assertEqual(
            [
                ("write", {"block_name": "GN_Agent_Draft"}),
                ("read", {"block_name": "GN_Agent_Draft"}),
            ],
            calls,
        )

    def test_runtime_dispatcher_routes_focal_reads_through_reads_module(self):
        from blender_addon.tools import reads
        from blender_addon.tools.server_dispatch import RuntimeDispatcher

        dispatcher = RuntimeDispatcher()
        calls: list[tuple[str, dict[str, Any]]] = []

        def _handler(label: str):
            def _fake(tool_input):
                calls.append((label, dict(tool_input)))
                return {"status": "success", "result": {"label": label}}

            return _fake

        originals = {
            "handle_get_node_context": reads.handle_get_node_context,
            "handle_get_selected_nodes_context": reads.handle_get_selected_nodes_context,
            "handle_get_active_frame_context": reads.handle_get_active_frame_context,
            "handle_get_local_subgraph_context": reads.handle_get_local_subgraph_context,
            "handle_list_tree_nodes": reads.handle_list_tree_nodes,
            "handle_find_tree_nodes": reads.handle_find_tree_nodes,
        }
        try:
            reads.handle_get_node_context = _handler("node")
            reads.handle_get_selected_nodes_context = _handler("selected")
            reads.handle_get_active_frame_context = _handler("active_frame")
            reads.handle_get_local_subgraph_context = _handler("subgraph")
            reads.handle_list_tree_nodes = _handler("list")
            reads.handle_find_tree_nodes = _handler("find")

            for tool_name in (
                "get_node_context",
                "get_selected_nodes_context",
                "get_active_frame_context",
                "get_local_subgraph_context",
                "list_tree_nodes",
                "find_tree_nodes",
            ):
                result = dispatcher.execute(tool_name, {"tree_name": "Biomodelo_GN"})
                self.assertEqual("success", result["status"])
        finally:
            for name, original in originals.items():
                setattr(reads, name, original)

        self.assertEqual(
            [
                ("node", {"tree_name": "Biomodelo_GN"}),
                ("selected", {"tree_name": "Biomodelo_GN"}),
                ("active_frame", {"tree_name": "Biomodelo_GN"}),
                ("subgraph", {"tree_name": "Biomodelo_GN"}),
                ("list", {"tree_name": "Biomodelo_GN"}),
                ("find", {"tree_name": "Biomodelo_GN"}),
            ],
            calls,
        )

    def test_runtime_dispatcher_routes_query_node_types_through_query_module(self):
        from blender_addon.tools import query
        from blender_addon.tools.server_dispatch import RuntimeDispatcher

        dispatcher = RuntimeDispatcher()
        calls: list[dict[str, Any]] = []

        def _fake_query(tool_input):
            calls.append(dict(tool_input))
            return {"status": "ok", "matches": ["GeometryNodeTest"]}

        original_query = query.handle_query_node_types
        try:
            query.handle_query_node_types = _fake_query
            result = dispatcher.execute("query_node_types", {"search": "test"})
        finally:
            query.handle_query_node_types = original_query

        self.assertEqual("ok", result["status"])
        self.assertEqual([{"search": "test"}], calls)

    def test_runtime_dispatcher_routes_execute_code_through_execution_module(self):
        from blender_addon.tools import execution
        from blender_addon.tools.server_dispatch import RuntimeDispatcher

        dispatcher = RuntimeDispatcher()
        calls: list[dict[str, Any]] = []

        def _fake_execute(tool_input):
            calls.append(dict(tool_input))
            return {"status": "success", "stdout": "done"}

        original_execute = execution.handle_execute_code
        try:
            execution.handle_execute_code = _fake_execute
            result = dispatcher.execute("execute_code", {"code": "print('done')"})
        finally:
            execution.handle_execute_code = original_execute

        self.assertEqual("success", result["status"])
        self.assertEqual([{"code": "print('done')"}], calls)

    def test_legacy_handlers_routes_apply_tools_through_edits_module(self):
        from blender_addon.tools import edits
        from blender_addon.tools.handlers import HANDLERS

        self.assertIs(HANDLERS["apply_renames"], edits.handle_apply_renames)
        self.assertIs(HANDLERS["apply_collections"], edits.handle_apply_collections)
        self.assertIs(HANDLERS["apply_gn_edits"], edits.handle_apply_gn_edits)

    def test_runtime_dispatcher_routes_snapshot_helpers_through_snapshots_module(self):
        from blender_addon.tools import snapshots
        from blender_addon.tools.server_dispatch import RuntimeDispatcher

        dispatcher = RuntimeDispatcher()
        calls: list[str] = []

        def _fake(label: str):
            def _handler(_tool_input):
                calls.append(label)
                return {"status": "success", "result": {"label": label}}

            return _handler

        originals = {
            "handle_capture_scene": snapshots.handle_capture_scene,
            "handle_capture_node_trees": snapshots.handle_capture_node_trees,
            "handle_capture_full": snapshots.handle_capture_full,
        }
        try:
            snapshots.handle_capture_scene = _fake("scene")
            snapshots.handle_capture_node_trees = _fake("node_trees")
            snapshots.handle_capture_full = _fake("full")

            self.assertEqual({"label": "scene"}, dispatcher._capture_scene())
            self.assertEqual({"label": "node_trees"}, dispatcher._capture_node_trees())
            self.assertEqual({"label": "full"}, dispatcher._capture_full())
        finally:
            for name, original in originals.items():
                setattr(snapshots, name, original)

        self.assertEqual(["scene", "node_trees", "full"], calls)


if __name__ == "__main__":
    unittest.main()
