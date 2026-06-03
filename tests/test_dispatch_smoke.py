"""Smoke tests for the slim single-handler dispatch surface."""

from __future__ import annotations

import sys
import tempfile
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

    def test_workspace_seed_biomodel_source_request_calls_seed_tool_directly(self):
        from blender_addon.handler import TurnContext
        from blender_addon.handler.workspace import handle
        from blender_addon.runtime.router import ClassifierMeta, TurnClass

        class _Runtime:
            def __init__(self):
                self._messages = []
                self._session_memory = {}
                self._session_state = {}
                self.journal = types.SimpleNamespace(log_runtime_event=lambda **_: None)
                self.tools = []
                self.model = "fake-model"
                self.tool_calls: list[tuple[str, dict[str, Any]]] = []

            def _execute_tool(self, name, tool_input, _elapsed):
                self.tool_calls.append((name, dict(tool_input)))
                return json.dumps({
                    "block_name": "GN_Biomodel_Source",
                    "source_block_name": "GN_Biomodel_Source",
                    "generated_tree_name": "VB_Biomodel_Generated",
                    "version": 1,
                    "char_count": 12000,
                    "manual_execution_required": True,
                })

            def _agent_loop(self, *_args, **_kwargs):
                raise AssertionError("seed request should bypass the model loop")

        runtime = _Runtime()
        ctx = TurnContext(
            session=_FakeSession(),
            message="Use seed_biomodel_source para criar o GN_Biomodel_Source. Nao execute ainda; apenas escreva o Text block para revisao.",
            meta=ClassifierMeta(
                turn_class=TurnClass.CONTEXT_INQUIRY,
                goal_mode="inquiry",
                needs_baseline_refresh=False,
            ),
            blend_path="",
            _runtime=runtime,
            knowledge_dir=Path("/nonexistent/knowledge/domain"),
        )

        result = handle(ctx, "inquiry")

        self.assertEqual([("seed_biomodel_source", {"block_name": "GN_Biomodel_Source"})], runtime.tool_calls)
        self.assertIn("GN_Biomodel_Source", result.response_text)
        self.assertIn("VB_Biomodel_Generated", result.response_text)
        self.assertIn("Nao executei", result.response_text)
        self.assertEqual("drafting", result.phase_transition)

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

    def test_biomodel_source_template_compiles_and_preserves_parameter_inventory(self):
        from blender_addon.biomodel.source_template import (
            GENERATED_TREE_NAME,
            PARAMETERS,
            build_biomodel_source_template,
        )

        code = build_biomodel_source_template()

        compile(code, "GN_Biomodel_Source", "exec")
        self.assertEqual(39, len(PARAMETERS))
        self.assertIn("GN_Biomodel_Source", code)
        self.assertIn(GENERATED_TREE_NAME, code)
        self.assertIn("Comp Antebraço", code)
        self.assertIn("Raio Punho", code)
        self.assertIn("Largura Metacarpo", code)
        self.assertIn("VB_Biomodel_Generated", code)
        self.assertIn("bpy.data.node_groups.remove(existing)", code)

    def test_runtime_dispatcher_seeds_biomodel_source_through_draft_writer(self):
        from blender_addon.tools import draft
        from blender_addon.tools.handlers import HANDLERS
        from blender_addon.tools.server_dispatch import RuntimeDispatcher

        self.assertIn("seed_biomodel_source", HANDLERS)

        dispatcher = RuntimeDispatcher()
        calls: list[dict[str, Any]] = []

        def _fake_write(tool_input):
            calls.append(dict(tool_input))
            return {"status": "success", "result": {"block_name": tool_input.get("block_name", ""), "version": 1}}

        original_write = draft.handle_write_script_draft
        try:
            draft.handle_write_script_draft = _fake_write
            result = dispatcher.execute(
                "seed_biomodel_source",
                {},
                session_state={"_runtime_project_root": "C:/workspace", "session_id": "sess-1"},
            )
        finally:
            draft.handle_write_script_draft = original_write

        self.assertEqual("success", result["status"])
        self.assertEqual(1, len(calls))
        seeded = calls[0]
        self.assertEqual("GN_Biomodel_Source", seeded["block_name"])
        self.assertEqual("biomodel_source", seeded["goal_mode"])
        self.assertEqual("intentional_rebuild", seeded["edit_mode"])
        self.assertTrue(seeded["allow_tree_change"])
        self.assertTrue(seeded["allow_capability_regression"])
        self.assertIn("VB_Biomodel_Generated", seeded["code"])
        self.assertEqual("C:/workspace", seeded["project_root"])
        self.assertEqual("sess-1", seeded["session_id"])
        self.assertEqual("VB_Biomodel_Generated", result["result"]["generated_tree_name"])
        self.assertTrue(result["result"]["manual_execution_required"])

    def test_biomodel_source_tools_are_registered_in_schema_and_dispatcher(self):
        from blender_addon.tools.handlers import HANDLERS
        from blender_addon.tools.schemas import TOOLS
        from blender_addon.tools.server_dispatch import RuntimeDispatcher

        schema_names = {str(tool.get("name") or "") for tool in TOOLS}
        for tool_name in ("read_biomodel_source", "write_biomodel_source", "validate_biomodel_source"):
            self.assertIn(tool_name, schema_names)
            self.assertIn(tool_name, HANDLERS)
            self.assertIn(tool_name, RuntimeDispatcher._TOOL_HANDLERS)

    def test_runtime_dispatcher_routes_biomodel_source_tools_through_source_module(self):
        from blender_addon.tools import biomodel_source
        from blender_addon.tools.server_dispatch import RuntimeDispatcher

        dispatcher = RuntimeDispatcher()
        calls: list[tuple[str, dict[str, Any]]] = []

        def _handler(label: str):
            def _fake(tool_input):
                calls.append((label, dict(tool_input)))
                return {"status": "success", "result": {"label": label}}

            return _fake

        originals = {
            "handle_read_biomodel_source": biomodel_source.handle_read_biomodel_source,
            "handle_write_biomodel_source": biomodel_source.handle_write_biomodel_source,
            "handle_validate_biomodel_source": biomodel_source.handle_validate_biomodel_source,
        }
        try:
            biomodel_source.handle_read_biomodel_source = _handler("read")
            biomodel_source.handle_write_biomodel_source = _handler("write")
            biomodel_source.handle_validate_biomodel_source = _handler("validate")

            read = dispatcher.execute("read_biomodel_source", {"block_name": "GN_Biomodel_Source"})
            write = dispatcher.execute("write_biomodel_source", {"code": "source", "description": "test"})
            validate = dispatcher.execute("validate_biomodel_source", {"code": "source"})
        finally:
            for name, original in originals.items():
                setattr(biomodel_source, name, original)

        self.assertEqual("success", read["status"])
        self.assertEqual("success", write["status"])
        self.assertEqual("success", validate["status"])
        self.assertEqual(
            [
                ("read", {"block_name": "GN_Biomodel_Source"}),
                ("write", {"code": "source", "description": "test"}),
                ("validate", {"code": "source"}),
            ],
            calls,
        )

    def test_write_biomodel_source_succeeds_without_draft_writer(self):
        from blender_addon.biomodel.source_template import build_biomodel_source_template
        from blender_addon.tools import draft
        from blender_addon.tools.biomodel_source import (
            handle_read_biomodel_source,
            handle_write_biomodel_source,
        )

        class _FakeText:
            def __init__(self, name: str):
                self.name = name
                self._content = ""
                self._props: dict[str, Any] = {}

            @property
            def lines(self):
                return self._content.splitlines() or [""]

            def as_string(self):
                return self._content

            def write(self, text: str):
                self._content += text

            def clear(self):
                self._content = ""

            def get(self, key: str, default: Any = None):
                return self._props.get(key, default)

            def __setitem__(self, key: str, value: Any):
                self._props[key] = value

        class _FakeTexts(dict):
            def new(self, name: str):
                text = _FakeText(name)
                self[name] = text
                return text

            def __iter__(self):
                return iter(self.values())

        sys.modules["bpy"].data.texts = _FakeTexts()

        original_write = draft.handle_write_script_draft
        try:
            draft.handle_write_script_draft = lambda _tool_input: (_ for _ in ()).throw(
                AssertionError("write_biomodel_source must not use write_script_draft")
            )
            written = handle_write_biomodel_source({
                "block_name": "GN_Biomodel_Source",
                "code": build_biomodel_source_template(),
                "description": "Direct source-mode write",
            })
        finally:
            draft.handle_write_script_draft = original_write

        self.assertEqual("success", written["status"])
        self.assertEqual("GN_Biomodel_Source", written["result"]["source_block_name"])
        self.assertTrue(written["result"]["validation"]["valid"])
        self.assertTrue(written["result"]["manual_execution_required"])

        read = handle_read_biomodel_source({"block_name": "GN_Biomodel_Source"})
        self.assertEqual("success", read["status"])
        self.assertIn("VB_Biomodel_Generated", read["result"]["content"])

    def test_validate_biomodel_source_blocks_reference_tree_mutation(self):
        from blender_addon.biomodel.source_template import build_biomodel_source_template
        from blender_addon.tools.biomodel_source import handle_validate_biomodel_source

        code = build_biomodel_source_template() + "\n" + (
            "bpy.data.node_groups.remove(bpy.data.node_groups.get('Biomodelo'))\n"
        )

        result = handle_validate_biomodel_source({"code": code})

        self.assertEqual("blocked", result["status"])
        self.assertFalse(result["result"]["valid"])
        self.assertIn("mutates_reference_tree:Biomodelo", result["result"]["errors"])

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

    def test_runtime_dispatcher_inspects_full_tree_inventory_in_pages(self):
        from blender_addon.tools import reads
        from blender_addon.tools.server_dispatch import RuntimeDispatcher

        dispatcher = RuntimeDispatcher()
        dispatcher._resolve_gn_workspace = lambda tool_input, session_state=None: {
            "status": "success",
            "result": {
                "selected_tree": "Biomodelo_GN",
                "selected_binding": {"object_name": "HandMesh", "modifier_name": "OrthosisGN"},
                "selection_reason": "test",
                "confidence": {"level": "high", "score": 1.0},
            },
        }
        dispatcher._get_tree_parameters = lambda tree_name: {
            "status": "success",
            "result": {
                "tree": tree_name,
                "parameters": [
                    {"name": "Palm Width", "identifier": "Input_12", "socket_type": "NodeSocketFloat"},
                ],
            },
        }
        fake_inventory = {
            "status": "success",
            "result": {
                "schema_version": "tree_direct_inventory.v1",
                "tree_name": "Biomodelo_GN",
                "node_count": 4,
                "link_count": 2,
                "frame_count": 1,
                "group_count": 0,
                "unframed_count": 2,
                "interface": {
                    "inputs": [{"name": "Palm Width", "identifier": "Input_12", "socket_type": "NodeSocketFloat"}],
                    "outputs": [{"name": "Geometry", "identifier": "Socket_1", "socket_type": "NodeSocketGeometry"}],
                    "panels": [],
                },
                "nodes": [
                    {"name": "Group Input", "label": "", "type": "NodeGroupInput", "parent_frame": "", "location": [0, 0]},
                    {"name": "REGION_HAND", "label": "Hand Region", "type": "NodeFrame", "parent_frame": "", "location": [100, 0]},
                    {"name": "Anchor_Wrist", "label": "Wrist Anchor", "type": "GeometryNodeInputPosition", "parent_frame": "REGION_HAND", "location": [200, 0]},
                    {"name": "Group Output", "label": "", "type": "NodeGroupOutput", "parent_frame": "", "location": [500, 0]},
                ],
                "links": [
                    {"from_node": "Group Input", "from_socket": "Palm Width", "to_node": "Anchor_Wrist", "to_socket": "Vector"},
                    {"from_node": "Anchor_Wrist", "from_socket": "Position", "to_node": "Group Output", "to_socket": "Geometry"},
                ],
            },
        }
        original_inventory = reads.handle_get_tree_inventory
        try:
            reads.handle_get_tree_inventory = lambda tool_input: fake_inventory

            overview = dispatcher.execute("inspect_tree_inventory", {"tree_name": "Biomodelo_GN"})
            nodes = dispatcher.execute(
                "inspect_tree_inventory",
                {"tree_name": "Biomodelo_GN", "section": "nodes", "offset": 2, "limit": 1},
            )
            parameters = dispatcher.execute(
                "inspect_tree_inventory",
                {"tree_name": "Biomodelo_GN", "section": "parameters"},
            )
        finally:
            reads.handle_get_tree_inventory = original_inventory

        self.assertEqual("success", overview["status"])
        self.assertEqual(4, overview["result"]["totals"]["nodes"])
        self.assertEqual(2, overview["result"]["totals"]["links"])
        self.assertTrue(overview["result"]["inspection_policy"]["full_tree_read"])
        self.assertEqual(["parameters", "regions", "nodes", "links", "anchors", "invariants"], overview["result"]["overview"]["next_sections"])

        self.assertEqual("success", nodes["status"])
        self.assertEqual(2, nodes["result"]["page"]["offset"])
        self.assertEqual(1, nodes["result"]["page"]["count"])
        self.assertEqual("Anchor_Wrist", nodes["result"]["page"]["items"][0]["name"])
        self.assertEqual(3, nodes["result"]["page"]["next_offset"])

        self.assertEqual("success", parameters["status"])
        self.assertEqual("Palm Width", parameters["result"]["interface"]["inputs"][0]["name"])
        self.assertEqual("Input_12", parameters["result"]["live_modifier_parameters"][0]["identifier"])

    def test_build_tree_structural_memory_keeps_full_direct_inventory(self):
        from blender_addon.tools import reads
        from blender_addon.tools.server_dispatch import RuntimeDispatcher

        dispatcher = RuntimeDispatcher()
        dispatcher._resolve_gn_workspace = lambda tool_input, session_state=None: {
            "status": "success",
            "result": {
                "selected_tree": "Biomodelo_GN",
                "selected_binding": {"object_name": "HandMesh", "modifier_name": "OrthosisGN"},
                "selection_reason": "test",
                "confidence": {"level": "high", "score": 1.0},
            },
        }
        dispatcher._capture_node_trees = lambda: {
            "node_groups": [
                {
                    "name": "Biomodelo_GN",
                    "bindings": [{"object_name": "HandMesh", "modifier_name": "OrthosisGN"}],
                    "snapshot_truncated": True,
                }
            ]
        }
        dispatcher._get_tree_parameters = lambda tree_name: {
            "status": "success",
            "result": {"tree": tree_name, "parameters": [{"name": "Palm Width", "identifier": "Input_12"}]},
        }
        fake_inventory = {
            "status": "success",
            "result": {
                "tree_name": "Biomodelo_GN",
                "node_count": 3,
                "link_count": 2,
                "frame_count": 1,
                "group_count": 0,
                "unframed_count": 2,
                "interface": {"inputs": [{"name": "Palm Width"}], "outputs": [{"name": "Geometry"}]},
                "nodes": [
                    {"name": "Group Input", "label": "", "type": "NodeGroupInput", "parent_frame": ""},
                    {"name": "REGION_HAND", "label": "Hand Region", "type": "NodeFrame", "parent_frame": ""},
                    {"name": "Anchor_Wrist", "label": "Wrist Anchor", "type": "GeometryNodeInputPosition", "parent_frame": "REGION_HAND"},
                ],
                "links": [
                    {"from_node": "Group Input", "from_socket": "Palm Width", "to_node": "Anchor_Wrist", "to_socket": "Vector"},
                    {"from_node": "Anchor_Wrist", "from_socket": "Position", "to_node": "REGION_HAND", "to_socket": "Geometry"},
                ],
            },
        }
        original_inventory = reads.handle_get_tree_inventory
        try:
            reads.handle_get_tree_inventory = lambda tool_input: fake_inventory
            result = dispatcher.execute("build_tree_structural_memory", {"tree_name": "Biomodelo_GN"})
        finally:
            reads.handle_get_tree_inventory = original_inventory

        self.assertEqual("success", result["status"])
        memory = result["result"]["memory"]
        self.assertEqual(3, memory["node_count"])
        self.assertEqual(2, memory["inventory"]["link_count"])
        self.assertTrue(memory["inventory"]["complete"])
        self.assertEqual("direct_bpy_full_inventory", memory["inventory"]["source"])
        self.assertEqual("Anchor_Wrist", memory["inventory"]["nodes"][2]["name"])
        self.assertTrue(memory["freshness"]["full_inventory_available"])

    def test_export_tree_inventory_writes_json_and_markdown_artifacts(self):
        from blender_addon.tools import reads
        from blender_addon.tools.server_dispatch import RuntimeDispatcher

        dispatcher = RuntimeDispatcher()
        dispatcher._resolve_gn_workspace = lambda tool_input, session_state=None: {
            "status": "success",
            "result": {
                "selected_tree": "Biomodelo_GN",
                "selected_binding": {"object_name": "HandMesh", "modifier_name": "OrthosisGN"},
                "selection_reason": "test",
                "confidence": {"level": "high", "score": 1.0},
            },
        }
        dispatcher._get_tree_parameters = lambda tree_name: {
            "status": "success",
            "result": {
                "tree": tree_name,
                "parameters": [{"name": "Palm Width", "identifier": "Input_12", "value": 42}],
            },
        }
        fake_inventory = {
            "status": "success",
            "result": {
                "tree_name": "Biomodelo_GN",
                "node_count": 3,
                "link_count": 2,
                "frame_count": 1,
                "group_count": 0,
                "unframed_count": 2,
                "interface": {
                    "inputs": [{"name": "Palm Width", "identifier": "Input_12", "socket_type": "NodeSocketFloat"}],
                    "outputs": [{"name": "Geometry", "identifier": "Socket_1", "socket_type": "NodeSocketGeometry"}],
                },
                "nodes": [
                    {"name": "Group Input", "label": "", "type": "NodeGroupInput", "parent_frame": "", "location": [0, 0]},
                    {"name": "REGION_HAND", "label": "Hand Region", "type": "NodeFrame", "parent_frame": "", "location": [100, 0]},
                    {"name": "Anchor_Wrist", "label": "Wrist Anchor", "type": "GeometryNodeInputPosition", "parent_frame": "REGION_HAND", "location": [200, 0]},
                ],
                "links": [
                    {"from_node": "Group Input", "from_socket": "Palm Width", "to_node": "Anchor_Wrist", "to_socket": "Vector"},
                    {"from_node": "Anchor_Wrist", "from_socket": "Position", "to_node": "REGION_HAND", "to_socket": "Geometry"},
                ],
            },
        }
        original_inventory = reads.handle_get_tree_inventory
        try:
            reads.handle_get_tree_inventory = lambda tool_input: fake_inventory
            with tempfile.TemporaryDirectory() as tmp:
                result = dispatcher.execute(
                    "export_tree_inventory",
                    {"tree_name": "Biomodelo_GN", "project_root": tmp},
                )
                self.assertEqual("success", result["status"])
                json_path = Path(result["result"]["json_path"])
                md_path = Path(result["result"]["markdown_path"])
                self.assertTrue(json_path.exists())
                self.assertTrue(md_path.exists())
                payload = json.loads(json_path.read_text(encoding="utf-8"))
                markdown = md_path.read_text(encoding="utf-8")
        finally:
            reads.handle_get_tree_inventory = original_inventory

        self.assertEqual("tree_inventory_export.v1", payload["schema_version"])
        self.assertEqual(3, payload["totals"]["nodes"])
        self.assertEqual("Anchor_Wrist", payload["nodes"][2]["name"])
        self.assertEqual("Palm Width", payload["live_modifier_parameters"][0]["name"])
        self.assertIn("# Tree Inventory: Biomodelo_GN", markdown)
        self.assertIn("Anchor_Wrist", markdown)

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
