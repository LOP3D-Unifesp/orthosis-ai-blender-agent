"""Focused stabilization checks for the unified draft workspace."""

from __future__ import annotations

import sys
import tempfile
import types
import unittest
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch


_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))


class _FakeNode:
    def __init__(self, name: str, *, bl_idname: str = "GeometryNodeGroup"):
        self.name = name
        self.bl_idname = bl_idname


class _FakeNodes(list):
    def new(self, node_type: str):
        node = _FakeNode(node_type, bl_idname=node_type)
        self.append(node)
        return node


class _FakeTree:
    def __init__(self, name: str, nodes: list[_FakeNode] | None = None):
        self.name = name
        self.bl_idname = "GeometryNodeTree"
        self.nodes = _FakeNodes(nodes or [])
        self.links = []


class _FakeNodeGroups(dict):
    def new(self, name: str, bl_idname: str):
        tree = _FakeTree(name)
        tree.bl_idname = bl_idname
        self[name] = tree
        return tree

    def remove(self, tree: Any):
        self.pop(getattr(tree, "name", ""), None)

    def __iter__(self):
        return iter(self.values())


class _FakeToolUseBlock:
    def __init__(self, name: str, tool_input: dict[str, Any], block_id: str):
        self.type = "tool_use"
        self.name = name
        self.input = tool_input
        self.id = block_id


class _FakeUsage:
    input_tokens = 10
    output_tokens = 5


class _FakeResponse:
    def __init__(self, content: list[Any], stop_reason: str = "tool_use"):
        self.content = content
        self.stop_reason = stop_reason
        self.usage = _FakeUsage()


class _FakeJournal:
    def __init__(self):
        self.events: list[dict[str, Any]] = []

    def accumulate_tokens(self, _input_tokens: int, _output_tokens: int) -> None:
        pass

    def log_runtime_event(self, event_type: str, payload: dict[str, Any] | None = None, status: str = "info") -> None:
        self.events.append({"event_type": event_type, "payload": payload or {}, "status": status})


class _FakeLoopRuntime:
    def __init__(self, response: _FakeResponse):
        self._response = response
        self.tools = [
            {"name": "write_script_draft"},
            {"name": "read_script_draft"},
        ]
        self.model = "fake-model"
        self.journal = _FakeJournal()
        self._messages: list[dict[str, Any]] = []
        self._tool_step = 0
        self._halt_execution = False
        self._halt_message = ""
        self._last_agent_loop_truncated = False
        self._last_agent_loop_round_limit_hit = False
        self.executed_tools: list[str] = []
        self.on_tool_call = None

    def _request_with_retry(self, **_kwargs):
        return self._response

    def _stream_with_retry(self, **_kwargs):
        return self._response

    def _extract_text(self, _response) -> str:
        return ""

    def _execute_tool(self, tool_name: str, tool_input: dict[str, Any], api_elapsed_ms: int) -> str:
        self.executed_tools.append(tool_name)
        if tool_name == "write_script_draft":
            return json.dumps({"status": "success", "result": {"block_name": "GN_Agent_Draft", "version": 7}})
        return json.dumps({"status": "success", "result": {}})


def _install_fake_bpy(texts: Any | None = None, node_groups: Any | None = None):
    bpy = types.ModuleType("bpy")
    handlers = types.SimpleNamespace(
        persistent=lambda fn: fn,
        load_post=[],
        save_post=[],
    )
    timers = types.SimpleNamespace(register=lambda fn: fn())
    bpy.app = types.SimpleNamespace(handlers=handlers, timers=timers)
    default_groups = node_groups or _FakeNodeGroups({
        "Biomodelo_GN": _FakeTree(
            "Biomodelo_GN",
            nodes=[
                _FakeNode("Group Input"),
                _FakeNode("ORTHOSIS_CONTEXT"),
                _FakeNode("Existing Orthosis Frame"),
            ],
        )
    })
    bpy.data = types.SimpleNamespace(filepath="", texts=texts or _FakeTexts(), node_groups=default_groups)
    sys.modules["bpy"] = bpy
    loaded_handlers = sys.modules.get("blender_addon.tools.handlers")
    if loaded_handlers is not None:
        loaded_handlers.bpy = bpy


@dataclass
class _FakeDraft:
    block_name: str = "GN_Agent_Draft"
    description: str = "Draft para ortese de palma/metacarpos"
    tree_name: str = "Biomodelo_GN"
    version: int = 1


@dataclass
class _FakeExecutionState:
    phase: str = "drafting"
    current_draft: Any = field(default_factory=_FakeDraft)
    draft_edit_mode: str = "preserve_and_refine"


@dataclass
class _FakeSession:
    execution_state: _FakeExecutionState = field(default_factory=_FakeExecutionState)


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

    def __getitem__(self, key: str):
        return self._props[key]

    def __setitem__(self, key: str, value: Any):
        self._props[key] = value


class _FakeTexts(dict):
    def new(self, name: str):
        text = _FakeText(name)
        self[name] = text
        return text

    def __iter__(self):
        return iter(self.values())


def _complete_validation_code(block_label: str = "Orthosis palm metacarpal controls") -> str:
    code = "\n".join([
        "import bpy",
        "tree = bpy.data.node_groups.get('Biomodelo_GN')",
        "if tree is None:",
        "    raise RuntimeError('Biomodelo_GN not found')",
        "nodes = tree.nodes",
        "links = tree.links",
        "frame = nodes.new('NodeFrame')",
        f"frame.label = {block_label!r}",
        "frame.name = 'ORTHOSIS_PALM_METACARPAL_CONTROLS'",
        "print('draft ready for manual review in Blender Text Editor')",
    ])
    return code + "\n# " + ("complete revision " * 20)


def _code_referencing_existing_tree_node(node_name: str) -> str:
    return "\n".join([
        "import bpy",
        "tree = bpy.data.node_groups.get('Biomodelo_GN')",
        "if tree is None:",
        "    raise RuntimeError('Biomodelo_GN not found')",
        f"target = tree.nodes[{node_name!r}]",
        "frame = tree.nodes.new('NodeFrame')",
        "frame.parent = target",
        "print('draft ready for manual review in Blender Text Editor')",
        "# " + ("complete revision " * 20),
    ])


def _code_with_semantic_expectations(
    node_name: str,
    *,
    parameter_name: str = "Palm Width",
    region_name: str = "Metacarpos",
) -> str:
    return "\n".join([
        "import bpy",
        "tree = bpy.data.node_groups.get('Biomodelo_GN')",
        "if tree is None:",
        "    raise RuntimeError('Biomodelo_GN not found')",
        f"anchor = tree.nodes[{node_name!r}]",
        "frame = tree.nodes.new('NodeFrame')",
        f"frame.label = {region_name!r}",
        f"parameter_name = {parameter_name!r}",
        "frame.parent = anchor",
        "print(parameter_name, frame.label)",
        "# " + ("complete revision " * 20),
    ])


def _prepared_context_result(
    *,
    tree_name: str = "Biomodelo_GN",
    parameter_name: str = "Palm Width",
    region_name: str = "Metacarpos",
) -> dict[str, Any]:
    return {
        "tree_name": tree_name,
        "workspace": {
            "selected_tree": tree_name,
            "selected_binding": {"object_name": "HandMesh", "modifier_name": "OrthosisGN"},
            "selection_reason": "test_fixture",
            "confidence": {"level": "high", "score": 0.9},
            "warnings": [],
        },
        "structural_memory": {
            "tree_name": tree_name,
            "node_count": 64,
            "frame_count": 5,
            "group_count": 3,
            "phase_dominant": "phase_2",
            "organization_assessment": {"level": "good"},
            "key_outputs": ["Group Output"],
            "key_joins": ["Join Geometry"],
            "major_regions": [{"name": region_name, "type": "frame"}],
            "parameters": {"measures": [{"name": parameter_name}]},
            "memory_meta": {"source": "test_fixture", "reused": True},
        },
        "live_parameters": {
            "tree": tree_name,
            "object": "HandMesh",
            "modifier": "OrthosisGN",
            "parameters": [{"name": parameter_name, "identifier": "palm_width"}],
        },
        "phase_classification": {
            "tree_phase": "phase_2",
            "confidence": {"level": "high", "score": 0.84},
            "unresolved_regions": [],
            "transition_regions": [{"region": region_name}],
        },
        "clinical_parameter_roles": {
            "summary": {"measurement_count": 1, "positioning_count": 0, "uncertain_count": 0},
            "measurement_parameters": [{"name": parameter_name, "identifier": "palm_width"}],
            "positioning_parameters": [],
            "likely_affected_regions": [{"region": region_name}],
        },
        "orthosis_interpretation": {
            "functional_summary": "Palm width drives the metacarpal orthosis support.",
            "workflow_stage_summary": {"orthosis_region_count": 1},
            "suggested_focus_regions": [{"region": region_name}],
            "next_structural_targets": [region_name],
            "organization_observations": ["keep living draft scope"],
        },
        "write_requirements": {
            "resolved_target_tree": True,
            "structural_memory_available": True,
            "parameter_context_available": True,
            "workflow_interpretation_available": True,
            "can_write_safely": True,
            "recommended_next_step": "revise_existing_draft_using_context",
            "blockers": [],
            "validation_checks": ["Preserve the canonical GN_Agent_Draft."],
        },
        "context_ready": True,
        "warnings": [],
        "prompt_context": "Prepared deterministic draft context for tests.",
    }


class FoundationStabilizationTests(unittest.TestCase):
    def setUp(self):
        _install_fake_bpy()

    def test_slim_runtime_routes_execution_result_prefix_with_revision_label(self):
        from blender_addon.core.runtime import AgentRuntime
        from blender_addon.runtime.router import TurnClass

        turn_class, meta, goal_mode = AgentRuntime._infer_turn_intent(
            _FakeSession(),
            "[RESULTADO DE EXECUÇÃO — Revisão v38]\nResultado: FALHOU\nDescrição: nada aconteceu",
        )

        self.assertEqual(TurnClass.EXECUTION_FEEDBACK, turn_class)
        self.assertEqual("feedback_fix", goal_mode)
        self.assertEqual("feedback_fix", meta.goal_mode)

    def test_slim_runtime_routes_escrever_as_write_intent(self):
        from blender_addon.core.runtime import AgentRuntime
        from blender_addon.runtime.router import TurnClass

        session = _FakeSession()
        session.execution_state.current_draft = types.SimpleNamespace(block_name="GN_Agent_Draft")
        turn_class, meta, goal_mode = AgentRuntime._infer_turn_intent(
            session,
            "o draft nao foi, tenta vc escrever ele novamente",
        )

        self.assertEqual(TurnClass.DRAFT_WORKSPACE, turn_class)
        self.assertEqual("focal_correction", goal_mode)
        self.assertEqual("draft_refinement", meta.turn_intent)

    def test_workspace_feedback_fix_records_feedback_without_writing(self):
        from blender_addon.handler import TurnContext
        from blender_addon.handler.workspace import GOAL_CONFIGS, handle
        from blender_addon.runtime.router import ClassifierMeta, TurnClass

        self.assertTrue(GOAL_CONFIGS["feedback_fix"].read_only)
        self.assertIn("write_script_draft", GOAL_CONFIGS["feedback_fix"].excluded_tools)

        session = _FakeSession()
        session.execution_state.current_draft = types.SimpleNamespace(
            block_name="GN_Agent_Draft",
            tree_name="Biomodelo_GN",
            version=7,
            last_written_chars=1200,
        )

        class _FeedbackRuntime:
            def __init__(self):
                self._messages = []
                self._current_turn_tools = []
                self._session_state = {"tree_structural_memory": {}}
                self._session_memory = {"target_tree": "Biomodelo_GN"}
                self.journal = types.SimpleNamespace(log_runtime_event=lambda **_: None)
                self.tools = []
                self.model = "claude-sonnet-4-6"

            def _execute_tool(self, name, tool_input, api_elapsed_ms):
                self._current_turn_tools.append({"name": name, "status": "success", "input": tool_input})
                if name == "read_script_draft":
                    return json.dumps({
                        "result": {
                            "block_name": "GN_Agent_Draft",
                            "content": "import bpy\nprint('old draft')\n",
                            "version": 7,
                            "char_count": 30,
                        },
                        "status": "success",
                    })
                return json.dumps({"result": {"memory": {"tree_name": "Biomodelo_GN", "node_count": 1}}, "status": "success"})

            def _request_text_response(self, **kwargs):
                return (
                    "Sintoma: nada aconteceu.\n"
                    "Hipotese: o script alterou valor sem efeito visivel.\n"
                    "Evidencia: draft v7 foi lido.\n"
                    "Confianca: media.\n"
                    "Limitacoes: preciso confirmar a estrategia.\n"
                    "Opcoes: A) revisar alvo do socket. B) investigar outro no.\n"
                    "Pergunta: voce prefere A ou B?"
                )

        runtime = _FeedbackRuntime()
        ctx = TurnContext(
            session=session,
            message="[RESULTADO DE EXECUÇÃO — Revisão v7]\nResultado: FALHOU\nDescrição: nada aconteceu",
            meta=ClassifierMeta(turn_class=TurnClass.EXECUTION_FEEDBACK, goal_mode="feedback_fix"),
            blend_path="",
            _runtime=runtime,
            knowledge_dir=Path("/nonexistent/knowledge/domain"),
        )

        result = handle(ctx, "feedback_fix")
        tool_names = [item["name"] for item in runtime._current_turn_tools]

        self.assertNotIn("write_script_draft", tool_names)
        self.assertIn("Diagnóstico", result.response_text)
        self.assertIsNotNone(session.execution_state.pending_user_decision)
        self.assertEqual("pending", session.execution_state.pending_user_decision.status)

    def test_execution_feedback_classifier_handles_real_journal_symptoms(self):
        from blender_addon.handler.feedback import _classify_execution_feedback

        self.assertEqual(
            ("reverted_by_user", True),
            _classify_execution_feedback("Dei control+z, nao deu certo. Nenhum slider funcionou e a palma ainda sumiu"),
        )
        self.assertEqual(
            ("executed_no_effect", False),
            _classify_execution_feedback("Nenhum slider funcionou"),
        )
        self.assertEqual(
            ("executed_failed", False),
            _classify_execution_feedback("a palma sumiu e o metacarpo desapareceu"),
        )

    def test_short_confirmation_reuses_pending_draft_action(self):
        from blender_addon.handler._drafting_support import _pending_action_instruction

        session = _FakeSession()
        session.execution_state.pending_draft_action = "write_confirmed_draft_revision"
        session.execution_state.pending_draft_prompt = "Posso escrever uma nova revisao do draft corrigindo os sliders."

        instruction = _pending_action_instruction(session.execution_state, session, "Pode")

        self.assertIn("confirms the pending action", instruction)
        self.assertIn("write_script_draft", instruction)

    def test_retry_phrase_reuses_pending_draft_action(self):
        from blender_addon.handler._drafting_support import _pending_action_instruction

        session = _FakeSession()
        session.execution_state.pending_draft_action = "write_confirmed_draft_revision"
        session.execution_state.pending_draft_prompt = "Escrita anterior falhou com Empty script."

        instruction = _pending_action_instruction(session.execution_state, session, "consegue tentar denovo entao?")

        self.assertIn("confirms the pending action", instruction)
        self.assertIn("write_script_draft", instruction)

    def test_execution_state_roundtrip_persists_draft_edit_mode(self):
        from blender_addon.session.schema import ExecutionState

        state = ExecutionState(
            pending_draft_action="write_confirmed_draft_revision",
            pending_draft_prompt="Previous rebuild proposal.",
            draft_edit_mode="intentional_retarget",
            post_failure_state="STRATEGY_APPROVED",
            proposed_strategy_count=2,
            proposed_strategy_revision=4,
            approved_strategy_label="B",
            approved_strategy_prompt="usa a abordagem B",
            session_state="STRATEGY_APPROVED",
        )

        restored = ExecutionState.from_dict(state.to_dict())
        invalid = ExecutionState.from_dict({"draft_edit_mode": "unexpected_mode", "post_failure_state": "UNKNOWN"})

        self.assertEqual("intentional_retarget", restored.draft_edit_mode)
        self.assertEqual("STRATEGY_APPROVED", restored.post_failure_state)
        self.assertEqual(2, restored.proposed_strategy_count)
        self.assertEqual(4, restored.proposed_strategy_revision)
        self.assertEqual("B", restored.approved_strategy_label)
        self.assertEqual("usa a abordagem B", restored.approved_strategy_prompt)
        self.assertEqual("STRATEGY_APPROVED", restored.session_state)
        self.assertEqual("preserve_and_refine", invalid.draft_edit_mode)
        self.assertEqual("", invalid.post_failure_state)

    def test_detect_draft_edit_mode_reuses_persisted_mode_on_short_confirmation(self):
        from blender_addon.handler._drafting_support import _detect_draft_edit_mode

        session = _FakeSession()
        session.execution_state.pending_draft_action = "write_confirmed_draft_revision"
        session.execution_state.pending_draft_prompt = "Previous rebuild proposal."
        session.execution_state.draft_edit_mode = "intentional_rebuild"

        mode = _detect_draft_edit_mode(
            session.execution_state,
            session,
            "pode",
            _complete_validation_code("existing draft"),
        )

        self.assertEqual("intentional_rebuild", mode)

    def test_detect_draft_edit_mode_reuses_persisted_draft_metadata_on_short_retry(self):
        from blender_addon.handler._drafting_support import _detect_draft_edit_mode_from_source

        session = _FakeSession()
        session.execution_state.draft_edit_mode = "preserve_and_refine"

        mode = _detect_draft_edit_mode_from_source(
            session.execution_state,
            session,
            "consegue tentar denovo entao?",
            _complete_validation_code("existing draft"),
            stored_edit_mode="intentional_retarget",
        )

        self.assertEqual("intentional_retarget", mode)

    def test_detect_draft_goal_mode_prefers_diagnosis_without_write_intent(self):
        from blender_addon.handler._drafting_support import _detect_draft_goal_mode

        session = _FakeSession()

        mode = _detect_draft_goal_mode(
            session.execution_state,
            session,
            "faz um diagnostico e me explica por que esse draft nao funcionou",
            _complete_validation_code("existing draft"),
        )

        self.assertEqual("diagnose_only", mode)

    def test_detect_draft_goal_mode_distinguishes_expansion_from_correction(self):
        from blender_addon.handler._drafting_support import _detect_draft_goal_mode

        session = _FakeSession()

        expansion = _detect_draft_goal_mode(
            session.execution_state,
            session,
            "adiciona suporte para a fase do punho nesse mesmo draft",
            _complete_validation_code("existing draft"),
        )
        correction = _detect_draft_goal_mode(
            session.execution_state,
            session,
            "corrige esse draft sem quebrar o que ja funciona",
            _complete_validation_code("existing draft"),
        )

        self.assertEqual("functional_expansion", expansion)
        self.assertEqual("focal_correction", correction)

    def test_detect_draft_goal_mode_treats_explicit_write_as_correction(self):
        from blender_addon.handler._drafting_support import _detect_draft_goal_mode

        session = _FakeSession()

        mode = _detect_draft_goal_mode(
            session.execution_state,
            session,
            "ok entao escreva",
            _complete_validation_code("existing draft"),
        )

        self.assertEqual("focal_correction", mode)

    def test_detect_draft_goal_mode_treats_functional_mismatch_as_correction(self):
        from blender_addon.handler._drafting_support import _detect_draft_goal_mode

        session = _FakeSession()

        mode = _detect_draft_goal_mode(
            session.execution_state,
            session,
            (
                "O comprimento do metacarpo está parametrizado, todavia o acompanhamento "
                "das falanges nao acontece grudado na face frontal do cubo dos metacarpos. "
                "Ele avança e recua nao de maneira linear, colada nos metacarpos"
            ),
            _complete_validation_code("existing draft"),
        )

        self.assertEqual("focal_correction", mode)

    def test_tree_change_message_requests_fresh_draft_context(self):
        from blender_addon.handler import TurnContext
        from blender_addon.handler._drafting_support import (
            DraftWorkspacePipelineState,
            _read_prepare_draft_context,
        )
        from blender_addon.runtime.router import ClassifierMeta, TurnClass

        class _Runtime:
            def __init__(self):
                self.tool_inputs: list[dict[str, Any]] = []
                self.journal = _FakeJournal()

            def _execute_tool(self, name, tool_input, _elapsed):
                self.tool_inputs.append({"name": name, "input": dict(tool_input)})
                return json.dumps({
                    "status": "success",
                    "result": {"tree_name": "Biomodelo_GN", "structural_memory": {}},
                })

        runtime = _Runtime()
        ctx = TurnContext(
            session=_FakeSession(),
            message="eu voltei a arvore biomodelo para antes da parametrizacao",
            meta=ClassifierMeta(turn_class=TurnClass.DRAFT_WORKSPACE),
            blend_path="",
            _runtime=runtime,
            knowledge_dir=Path("/nonexistent/knowledge/domain"),
        )
        state = DraftWorkspacePipelineState(
            es=ctx.session.execution_state,
            draft=None,
            economy_retry=False,
            block_name="GN_Agent_Draft",
            draft_payload={},
            info={},
            content=_complete_validation_code("existing draft"),
            draft_obj=None,
            tree_name_hint="Biomodelo_GN",
            runtime_memory={},
            relevant_nodes=[],
            edit_mode="preserve_and_refine",
            goal_mode="focal_correction",
            goal_guidance={},
            stored_edit_mode="preserve_and_refine",
            stored_live_node_refs=[],
            stored_expected_parameter_refs=[],
            stored_expected_focus_regions=[],
        )

        _read_prepare_draft_context(ctx, state)

        self.assertTrue(runtime.tool_inputs[0]["input"]["force_refresh"])
        self.assertTrue(any(e["event_type"] == "draft_context_force_refresh_requested" for e in runtime.journal.events))

    def test_detect_draft_goal_mode_reuses_persisted_draft_goal_mode_on_short_retry(self):
        from blender_addon.handler._drafting_support import _detect_draft_goal_mode_from_source

        session = _FakeSession()

        mode = _detect_draft_goal_mode_from_source(
            session.execution_state,
            session,
            "consegue tentar denovo entao?",
            _complete_validation_code("existing draft"),
            stored_goal_mode="functional_expansion",
        )

        self.assertEqual("functional_expansion", mode)

    def test_model_policy_has_no_legacy_turn_classes(self):
        from blender_addon.model_policy import select_max_tokens

        self.assertEqual(6000, select_max_tokens("draft_workspace"))
        self.assertEqual(4096, select_max_tokens("removed_turn_class"))

    def test_partial_draft_write_is_blocked_before_overwriting_text_block(self):
        from blender_addon.tools.handlers import handle_read_script_draft, handle_write_script_draft

        result = handle_write_script_draft({
            "block_name": "GN_Agent_Draft",
            "code": "print()",
            "description": "Tiny accidental write",
            "tree_name": "Biomodelo_GN",
        })

        self.assertEqual("blocked", result["status"])
        self.assertIsNone(sys.modules["bpy"].data.texts.get("GN_Agent_Draft"))

        valid_code = _complete_validation_code()

        written = handle_write_script_draft({
            "block_name": "GN_Agent_Draft",
            "code": valid_code,
            "description": "Complete revision",
            "tree_name": "Biomodelo_GN",
        })

        self.assertEqual("success", written["status"])
        read = handle_read_script_draft({"block_name": "GN_Agent_Draft"})
        self.assertEqual("success", read["status"])
        self.assertEqual("valid", read["result"]["current_revision_validity"])

    def test_write_script_draft_updates_single_canonical_text_block_only(self):
        from blender_addon.tools.handlers import handle_write_script_draft

        result = handle_write_script_draft({
            "block_name": "GN_Agent_Draft",
            "code": _complete_validation_code("Single living draft"),
            "description": "Complete revision",
            "tree_name": "Biomodelo_GN",
        })

        self.assertEqual("success", result["status"])
        self.assertIsNotNone(sys.modules["bpy"].data.texts.get("GN_Agent_Draft"))
        self.assertIsNone(sys.modules["bpy"].data.texts.get("GN_Agent_Draft__rev_000001"))
        self.assertNotIn("revision_block_name", result["result"])

    def test_write_script_draft_archives_full_revision_to_disk(self):
        from blender_addon.tools.handlers import handle_read_script_draft, handle_write_script_draft

        with tempfile.TemporaryDirectory() as tmp:
            result = handle_write_script_draft({
                "block_name": "GN_Agent_Draft",
                "code": _complete_validation_code("Archived living draft"),
                "description": "Archived complete revision",
                "tree_name": "Biomodelo_GN",
                "session_id": "sess-test-drafts",
                "project_root": tmp,
            })

            self.assertEqual("success", result["status"])
            archive_path = Path(result["result"]["draft_archive_path"])
            self.assertTrue(archive_path.exists())
            self.assertEqual(Path(tmp) / "runtime" / "draft_history" / "sess-test-drafts", archive_path.parent)
            archived = archive_path.read_text(encoding="utf-8")
            self.assertIn("# revision: 1", archived)
            self.assertIn("Archived living draft", archived)

            read = handle_read_script_draft({"block_name": "GN_Agent_Draft"})
            self.assertEqual(str(archive_path), read["result"]["draft_archive_path"])

    def test_read_script_draft_returns_persisted_goal_metadata(self):
        from blender_addon.tools.handlers import handle_read_script_draft, handle_write_script_draft

        written = handle_write_script_draft({
            "block_name": "GN_Agent_Draft",
            "code": _complete_validation_code("Expansion draft"),
            "description": "Expansion draft",
            "tree_name": "Biomodelo_GN",
            "goal_mode": "functional_expansion",
            "goal_guidance": {
                "summary": "Extend the same living draft with the next capability.",
                "suggested_output": "incremental_feature_expansion",
                "focus_priorities": ["Metacarpos"],
            },
        })

        self.assertEqual("success", written["status"])
        read = handle_read_script_draft({"block_name": "GN_Agent_Draft"})

        self.assertEqual("success", read["status"])
        self.assertEqual("functional_expansion", read["result"]["goal_mode"])
        self.assertEqual(
            "incremental_feature_expansion",
            read["result"]["goal_guidance"]["suggested_output"],
        )

    def test_read_script_draft_returns_persisted_edit_metadata(self):
        from blender_addon.tools.handlers import handle_read_script_draft, handle_write_script_draft

        written = handle_write_script_draft({
            "block_name": "GN_Agent_Draft",
            "code": _complete_validation_code("Retarget draft"),
            "description": "Retarget draft",
            "tree_name": "Biomodelo_GN",
            "edit_mode": "intentional_retarget",
        })

        self.assertEqual("success", written["status"])
        read = handle_read_script_draft({"block_name": "GN_Agent_Draft"})

        self.assertEqual("success", read["status"])
        self.assertEqual("intentional_retarget", read["result"]["edit_mode"])

    def test_read_script_draft_returns_persisted_semantic_metadata(self):
        from blender_addon.tools.handlers import handle_read_script_draft, handle_write_script_draft

        written = handle_write_script_draft({
            "block_name": "GN_Agent_Draft",
            "code": _code_with_semantic_expectations(
                "ORTHOSIS_CONTEXT",
                parameter_name="Palm Width",
                region_name="Metacarpos",
            ),
            "description": "Semantic living draft",
            "tree_name": "Biomodelo_GN",
            "expected_parameter_refs": ["Palm Width"],
            "expected_focus_regions": ["Metacarpos"],
        })

        self.assertEqual("success", written["status"])
        read = handle_read_script_draft({"block_name": "GN_Agent_Draft"})

        self.assertEqual("success", read["status"])
        self.assertEqual(["Palm Width"], read["result"]["expected_parameter_refs"])
        self.assertEqual(["Metacarpos"], read["result"]["expected_focus_regions"])
        self.assertIn("ORTHOSIS_CONTEXT", read["result"]["live_node_refs"])

    def test_write_script_draft_blocks_when_target_tree_is_missing(self):
        from blender_addon.tools.handlers import handle_write_script_draft

        result = handle_write_script_draft({
            "block_name": "GN_Agent_Draft",
            "code": _complete_validation_code("Missing tree should block"),
            "description": "Complete revision",
            "tree_name": "Tree_That_Does_Not_Exist",
        })

        self.assertEqual("blocked", result["status"])
        self.assertIn("target_tree_missing:Tree_That_Does_Not_Exist", result["error"])
        self.assertIsNone(sys.modules["bpy"].data.texts.get("GN_Agent_Draft"))

    def test_write_script_draft_blocks_when_live_node_reference_is_missing(self):
        from blender_addon.tools.handlers import handle_write_script_draft

        result = handle_write_script_draft({
            "block_name": "GN_Agent_Draft",
            "code": _code_referencing_existing_tree_node("MISSING_ORTHOSIS_NODE"),
            "description": "Complete revision",
            "tree_name": "Biomodelo_GN",
        })

        self.assertEqual("blocked", result["status"])
        self.assertIn("missing_live_nodes:MISSING_ORTHOSIS_NODE", result["error"])
        self.assertIsNone(sys.modules["bpy"].data.texts.get("GN_Agent_Draft"))

    def test_write_script_draft_blocks_when_candidate_drops_existing_live_node_refs(self):
        from blender_addon.tools.handlers import handle_write_script_draft

        first = handle_write_script_draft({
            "block_name": "GN_Agent_Draft",
            "code": _code_referencing_existing_tree_node("ORTHOSIS_CONTEXT"),
            "description": "Existing anchored living draft",
            "tree_name": "Biomodelo_GN",
        })
        self.assertEqual("success", first["status"])

        second = handle_write_script_draft({
            "block_name": "GN_Agent_Draft",
            "code": _complete_validation_code("Regression candidate without live refs"),
            "description": "Rewrite that loses live anchors",
            "tree_name": "Biomodelo_GN",
        })

        self.assertEqual("blocked", second["status"])
        self.assertIn("regression_lost_live_node_refs", second["error"])
        text_block = sys.modules["bpy"].data.texts.get("GN_Agent_Draft")
        self.assertIsNotNone(text_block)
        self.assertIn("ORTHOSIS_CONTEXT", text_block.as_string())

    def test_write_script_draft_blocks_when_candidate_drops_expected_parameters(self):
        from blender_addon.tools.handlers import handle_write_script_draft

        first = handle_write_script_draft({
            "block_name": "GN_Agent_Draft",
            "code": _code_with_semantic_expectations(
                "ORTHOSIS_CONTEXT",
                parameter_name="Palm Width",
                region_name="Metacarpos",
            ),
            "description": "Existing living draft with semantic scope",
            "tree_name": "Biomodelo_GN",
            "expected_parameter_refs": ["Palm Width"],
            "expected_focus_regions": ["Metacarpos"],
        })
        self.assertEqual("success", first["status"])

        second = handle_write_script_draft({
            "block_name": "GN_Agent_Draft",
            "code": _code_referencing_existing_tree_node("ORTHOSIS_CONTEXT"),
            "description": "Rewrite that silently drops parameter coverage",
            "tree_name": "Biomodelo_GN",
            "expected_parameter_refs": ["Palm Width"],
            "expected_focus_regions": ["Metacarpos"],
        })

        self.assertEqual("blocked", second["status"])
        self.assertIn("regression_lost_expected_parameters", second["error"])
        self.assertIn("Palm Width", second["result"]["previous_parameter_refs"])

    def test_write_script_draft_blocks_when_candidate_drops_focus_regions(self):
        from blender_addon.tools.handlers import handle_write_script_draft

        first = handle_write_script_draft({
            "block_name": "GN_Agent_Draft",
            "code": _code_with_semantic_expectations(
                "ORTHOSIS_CONTEXT",
                parameter_name="Palm Width",
                region_name="Metacarpos",
            ),
            "description": "Existing living draft with region scope",
            "tree_name": "Biomodelo_GN",
            "expected_parameter_refs": ["Palm Width"],
            "expected_focus_regions": ["Metacarpos"],
        })
        self.assertEqual("success", first["status"])

        second = handle_write_script_draft({
            "block_name": "GN_Agent_Draft",
            "code": _code_with_semantic_expectations(
                "ORTHOSIS_CONTEXT",
                parameter_name="Palm Width",
                region_name="Punho",
            ),
            "description": "Rewrite that drifts to another region",
            "tree_name": "Biomodelo_GN",
            "expected_parameter_refs": ["Palm Width"],
            "expected_focus_regions": ["Metacarpos"],
        })

        self.assertEqual("blocked", second["status"])
        self.assertIn("regression_lost_focus_regions", second["error"])

    def test_write_script_draft_ignores_generic_frame_focus_regions(self):
        from blender_addon.tools.handlers import handle_write_script_draft

        first = handle_write_script_draft({
            "block_name": "GN_Agent_Draft",
            "code": _code_with_semantic_expectations("ORTHOSIS_CONTEXT", region_name="Frame"),
            "description": "Existing draft with generic frame metadata",
            "tree_name": "Biomodelo_GN",
            "expected_focus_regions": ["Frame", "Frame.004", "unknown_structural_region"],
        })
        second = handle_write_script_draft({
            "block_name": "GN_Agent_Draft",
            "code": _code_with_semantic_expectations("ORTHOSIS_CONTEXT", region_name="Metacarpos"),
            "description": "Focal correction that does not mention generic frame labels",
            "tree_name": "Biomodelo_GN",
            "expected_focus_regions": ["Frame", "Frame.004", "unknown_structural_region"],
        })

        self.assertEqual("success", first["status"])
        self.assertEqual("success", second["status"])

    def test_write_script_draft_blocks_when_living_draft_changes_target_tree(self):
        from blender_addon.tools.handlers import handle_write_script_draft

        sys.modules["bpy"].data.node_groups.new("Other_Orthosis_Tree", "GeometryNodeTree")

        first = handle_write_script_draft({
            "block_name": "GN_Agent_Draft",
            "code": _complete_validation_code("Existing biomodel draft"),
            "description": "Existing biomodel draft",
            "tree_name": "Biomodelo_GN",
        })
        self.assertEqual("success", first["status"])

        second = handle_write_script_draft({
            "block_name": "GN_Agent_Draft",
            "code": _complete_validation_code("Candidate changing tree"),
            "description": "Attempt to repoint living draft",
            "tree_name": "Other_Orthosis_Tree",
        })

        self.assertEqual("blocked", second["status"])
        self.assertIn("target_tree_changed:Biomodelo_GN->Other_Orthosis_Tree", second["error"])
        text_block = sys.modules["bpy"].data.texts.get("GN_Agent_Draft")
        self.assertIsNotNone(text_block)
        self.assertEqual("Biomodelo_GN", text_block.get("_draft_tree_name"))

    def test_read_script_draft_prefers_canonical_block_over_legacy_revision_blocks(self):
        from blender_addon.tools.handlers import handle_read_script_draft

        canonical = sys.modules["bpy"].data.texts.new("GN_Agent_Draft")
        canonical.write(_complete_validation_code("Canonical source"))
        canonical["_draft_version"] = 3
        canonical["_draft_revision_validity"] = "valid"
        canonical["_draft_description"] = "Canonical current draft"
        canonical["_draft_tree_name"] = "Biomodelo_GN"

        legacy = sys.modules["bpy"].data.texts.new("GN_Agent_Draft__rev_000004")
        legacy.write(_complete_validation_code("Legacy backup"))
        legacy["_draft_base_block_name"] = "GN_Agent_Draft"
        legacy["_draft_version"] = 4
        legacy["_draft_revision_validity"] = "valid"
        legacy["_draft_description"] = "Legacy backup"
        legacy["_draft_tree_name"] = "Biomodelo_GN"

        read = handle_read_script_draft({"block_name": "GN_Agent_Draft"})

        self.assertEqual("success", read["status"])
        self.assertEqual("text_block", read["result"]["source"])
        self.assertFalse(bool(read["result"].get("legacy_fallback_used", False)))
        self.assertEqual("Canonical current draft", read["result"]["description"])
        self.assertEqual(3, int(read["result"]["version"]))

    def test_read_script_draft_can_fallback_to_legacy_revision_when_main_block_is_missing(self):
        from blender_addon.tools.handlers import handle_read_script_draft

        legacy = sys.modules["bpy"].data.texts.new("GN_Agent_Draft__rev_000007")
        legacy.write(_complete_validation_code("Legacy recovery source"))
        legacy["_draft_base_block_name"] = "GN_Agent_Draft"
        legacy["_draft_version"] = 7
        legacy["_draft_revision_validity"] = "valid"
        legacy["_draft_description"] = "Legacy recovery source"
        legacy["_draft_tree_name"] = "Biomodelo_GN"

        read = handle_read_script_draft({"block_name": "GN_Agent_Draft"})

        self.assertEqual("success", read["status"])
        self.assertEqual("legacy_revision_fallback", read["result"]["source"])
        self.assertTrue(bool(read["result"].get("legacy_fallback_used", False)))
        self.assertEqual("GN_Agent_Draft__rev_000007", read["result"]["legacy_block_name"])
        self.assertEqual(7, int(read["result"]["version"]))

    def test_dashboard_treats_memory_event_without_used_flag_as_used(self):
        from blender_addon.operation_journal import OperationJournal

        with tempfile.TemporaryDirectory() as tmp:
            journal = OperationJournal(Path(tmp))
            journal.start_goal(user_message="meta", tree_name="Biomodelo_GN", blend_file="")
            journal.log_runtime_event(
                event_type="session_memory_used",
                payload={"source": "draft_workspace", "has_goal": False, "has_hypothesis": False, "relevant_nodes_count": 3},
            )
            journal.end_goal()
            dashboard = {}
            for line in journal.session_file.read_text(encoding="utf-8").splitlines():
                entry = json.loads(line)
                if entry.get("type") == "goal_end":
                    dashboard = entry.get("dashboard", {})
            self.assertTrue(dashboard.get("session_memory_used"))

    def test_chat_session_blocks_code_like_streaming_text(self):
        from blender_addon.ui.chat_session import _ChatSession

        session = _ChatSession()
        session.append_stream_chunk("Vou verificar isso.\n")
        session.append_stream_chunk("import bpy\n")
        session.append_stream_chunk("tree = bpy.data.node_groups['Biomodelo_GN']\n")
        session.append_stream_chunk("nodes = tree.nodes\n")
        session.append_stream_chunk("links = tree.links\n")

        self.assertIn("codigo omitido", session.streaming_text)
        self.assertTrue(session.stream_blocked)
        self.assertNotIn("import bpy", session.streaming_text)

    def test_chat_session_sanitizes_final_assistant_code_fence(self):
        from blender_addon.ui.chat_session import _ChatSession

        session = _ChatSession()
        session.add(
            "assistant",
            "Vou gerar o draft:\n```python\nimport bpy\nprint('x')\n```\nPronto.",
        )

        text = session.get_messages()[0]["text"]
        self.assertIn("codigo omitido", text)
        self.assertNotIn("import bpy", text)

    def test_tree_renderer_keeps_exact_node_names_sockets_and_parameters(self):
        from blender_addon.runtime.tree_renderer import render_compact_tree

        rendered = render_compact_tree({
            "tree_name": "Biomodelo",
            "node_count": 4,
            "nodes": [
                {"name": "Frame.001", "label": "Metacarpos", "type": "NodeFrame"},
                {"name": "Cube_Metacarpo1.001", "label": "Cube_Metacarpo1", "type": "GeometryNodeMeshCube"},
                {"name": "TF_Metacarpo1.001", "label": "TG_Metacarpo1", "type": "FunctionNodeTransform"},
            ],
            "interface": {
                "inputs": [{"name": "Comp Metacarpo", "identifier": "Socket_29", "type": "NodeSocketFloat"}],
                "outputs": [{"name": "Geometry", "identifier": "Socket_7", "type": "NodeSocketGeometry"}],
            },
            "links": [
                {
                    "from_node": "Group Input",
                    "from_socket": "Comp Metacarpo",
                    "to_node": "SizeY_MC1",
                    "to_socket": "Value",
                }
            ],
            "parameters": {
                "measures": [{"name": "Comp Metacarpo", "identifier": "Socket_29", "value": 83.0}],
            },
        })

        self.assertIn("Cube_Metacarpo1.001", rendered)
        self.assertIn("TF_Metacarpo1.001", rendered)
        self.assertIn("Comp Metacarpo id=Socket_29", rendered)
        self.assertIn("Group Input:Comp Metacarpo -> SizeY_MC1:Value", rendered)

    def test_prompt_builder_injects_baseline_tree_render(self):
        from blender_addon.runtime.prompt_builder import build_system_prompt
        from blender_addon.runtime.tree_renderer import compact_tree_summary_for_baseline

        memory = {
            "tree_name": "Biomodelo",
            "node_count": 2,
            "frame_count": 1,
            "major_regions": [
                {"name": "Frame.001", "label": "Metacarpos", "key_nodes": ["Cube_Metacarpo1.001"]},
            ],
            "marker": {"node_names": ["Cube_Metacarpo1.001", "TF_Metacarpo1.001"], "links": []},
            "parameters": {"measures": [{"name": "Comp Metacarpo", "identifier": "Socket_29", "value": 83.0}]},
        }
        session = types.SimpleNamespace(
            focus=types.SimpleNamespace(tree_name="Biomodelo", blend_path="C:/tmp/test.blend"),
            identity=types.SimpleNamespace(blend_path="C:/tmp/test.blend"),
            baseline_workspace=types.SimpleNamespace(
                stale=False,
                structural_summary=compact_tree_summary_for_baseline(memory),
            ),
            execution_state=types.SimpleNamespace(phase="idle", current_draft=None, draft_revision=0),
        )

        prompt = build_system_prompt(session, "draft_workspace", knowledge=[])

        self.assertIn("[Tree Snapshot Render]", prompt)
        self.assertIn("Frame.001 label=Metacarpos", prompt)
        self.assertIn("Cube_Metacarpo1.001", prompt)
        self.assertIn("Comp Metacarpo id=Socket_29", prompt)

    def test_agent_loop_stops_after_successful_draft_write(self):
        from blender_addon.core.agent_loop import agent_loop

        runtime = _FakeLoopRuntime(_FakeResponse([
            _FakeToolUseBlock(
                "write_script_draft",
                {"block_name": "GN_Agent_Draft", "code": "print('ok')"},
                "toolu_write",
            ),
            _FakeToolUseBlock("read_script_draft", {"block_name": "GN_Agent_Draft"}, "toolu_read"),
        ]))

        result = agent_loop(runtime, "system", [{"role": "user", "content": "corrige o draft"}], max_rounds=5)

        self.assertEqual(["write_script_draft"], runtime.executed_tools)
        self.assertIn("Draft salvo com sucesso", result)
        self.assertFalse(runtime._last_agent_loop_round_limit_hit)
        self.assertTrue(any(e["event_type"] == "agent_loop_halted_after_draft_write" for e in runtime.journal.events))

    def test_agent_loop_stops_after_real_write_result_shape(self):
        from blender_addon.core.agent_loop import agent_loop

        runtime = _FakeLoopRuntime(_FakeResponse([
            _FakeToolUseBlock(
                "write_script_draft",
                {"block_name": "GN_Agent_Draft", "code": "print('ok')"},
                "toolu_write",
            ),
            _FakeToolUseBlock("read_script_draft", {"block_name": "GN_Agent_Draft"}, "toolu_read"),
        ]))

        def _real_shape_execute(tool_name: str, tool_input: dict[str, Any], api_elapsed_ms: int) -> str:
            runtime.executed_tools.append(tool_name)
            if tool_name == "write_script_draft":
                return json.dumps({"block_name": "GN_Agent_Draft", "version": 11, "char_count": 1234})
            return json.dumps({"block_name": "GN_Agent_Draft", "content": "old"})

        runtime._execute_tool = _real_shape_execute

        result = agent_loop(runtime, "system", [{"role": "user", "content": "corrige o draft"}], max_rounds=5)

        self.assertEqual(["write_script_draft"], runtime.executed_tools)
        self.assertIn("Draft salvo com sucesso", result)
        self.assertTrue(any(e["event_type"] == "agent_loop_halted_after_draft_write" for e in runtime.journal.events))

    def test_agent_loop_stops_after_blocked_draft_write(self):
        from blender_addon.core.agent_loop import agent_loop

        runtime = _FakeLoopRuntime(_FakeResponse([
            _FakeToolUseBlock(
                "write_script_draft",
                {"block_name": "GN_Agent_Draft", "code": "print('bad')"},
                "toolu_write",
            ),
            _FakeToolUseBlock("read_script_draft", {"block_name": "GN_Agent_Draft"}, "toolu_read"),
        ]))

        def _blocked_execute(tool_name: str, tool_input: dict[str, Any], api_elapsed_ms: int) -> str:
            runtime.executed_tools.append(tool_name)
            if tool_name == "write_script_draft":
                return json.dumps({"status": "blocked", "error": "regression_lost_focus_regions:Frame"})
            return json.dumps({"block_name": "GN_Agent_Draft", "content": "old"})

        runtime._execute_tool = _blocked_execute

        result = agent_loop(runtime, "system", [{"role": "user", "content": "corrige o draft"}], max_rounds=5)

        self.assertEqual(["write_script_draft"], runtime.executed_tools)
        self.assertIn("Draft bloqueado", result)
        self.assertTrue(any(e["event_type"] == "agent_loop_halted_after_draft_write_blocked" for e in runtime.journal.events))

    def test_draft_policy_blocks_duplicate_read_script_draft_when_preloaded(self):
        from blender_addon.core.runtime import AgentRuntime

        runtime = types.SimpleNamespace(
            _draft_tool_policy={
                "turn_class": "draft_workspace",
                "existing_draft_loaded": True,
                "tree_name": "Biomodelo",
                "fresh_structural_memory": True,
                "focal_used": 0,
                "focal_budget": 3,
            },
            _draft_attempt_state=None,
            journal=types.SimpleNamespace(log_runtime_event=lambda **_: None),
        )
        runtime._block_draft_tool = lambda tool_name, reason, policy: AgentRuntime._block_draft_tool(
            runtime,
            tool_name,
            reason,
            policy,
        )

        blocked = AgentRuntime._enforce_draft_tool_policy(runtime, "read_script_draft")

        self.assertIn("draft_source_already_read", blocked)

    def test_runtime_agent_loop_4d_truncation_budgets(self):
        import blender_addon.core.agent_loop as loop

        self.assertEqual(6000, loop._MAX_TOOL_RESULT_CHARS)
        self.assertEqual(4000, loop._MAX_READ_RESULT_CHARS)
        self.assertNotIn("build_tree_structural_memory", loop._HEAVY_READ_TOOLS)
        self.assertIn("get_scene_summary", loop._HEAVY_READ_TOOLS)
        self.assertIn("get_gn_hosts", loop._HEAVY_READ_TOOLS)

    def test_compress_tool_inputs_preserves_draft_tool_context(self):
        from blender_addon.core.agent_loop import _compress_tool_inputs_in_history

        messages = [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_read",
                        "name": "read_script_draft",
                        "input": {
                            "block_name": "GN_Agent_Draft",
                            "tree_name": "Biomodelo",
                            "extra": "x" * 500,
                        },
                    }
                ],
            },
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "toolu_read", "content": "{}"}],
            },
        ]

        _compress_tool_inputs_in_history(messages)

        compressed = messages[0]["content"][0]["input"]
        self.assertEqual("GN_Agent_Draft", compressed["block_name"])
        self.assertEqual("Biomodelo", compressed["tree_name"])
        self.assertNotIn("extra", compressed)

    def test_brief_chat_summary_sanitizes_and_truncates_diagnosis(self):
        from blender_addon.handler._drafting_support import _brief_chat_summary

        raw = "Diagnostico:\n```python\nimport bpy\nprint('x')\n```\n" + ("frase longa. " * 120)

        text = _brief_chat_summary(raw, max_chars=240)

        self.assertLessEqual(len(text), 260)
        self.assertNotIn("import bpy", text)
        self.assertNotIn("print(", text)
        self.assertIn("codigo omitido", text)

    def test_draft_workspace_does_not_report_success_after_blocked_write(self):
        from blender_addon.handler import TurnContext
        from blender_addon.handler._drafting_support import handle_draft_workspace
        from blender_addon.runtime.router import ClassifierMeta, TurnClass
        from blender_addon.tools.handlers import handle_write_script_draft

        class _FakeRuntime:
            def __init__(self):
                self._messages = []
                self._session_memory = {
                    "last_goal": "Fazer uma ortese a partir de biomodelo de palma/metacarpos.",
                    "last_hypothesis": "O draft precisa ser completo antes de ir para o Text Editor.",
                    "target_tree": "Biomodelo_GN",
                    "relevant_nodes": [],
                }
                self._session_state = {"tree_structural_memory": {}}
                self._draft_tool_policy = {}
                self._current_turn_tools = []
                self.journal = types.SimpleNamespace(log_runtime_event=lambda **_: None)

            def _agent_loop(self, *_args, **_kwargs):
                self._execute_tool("write_script_draft", {
                    "block_name": "GN_Agent_Draft",
                    "code": "print()",
                    "description": "Tiny accidental draft",
                    "tree_name": "Biomodelo_GN",
                }, 0)
                return "Ok, draft criado."

            def _execute_tool(self, name, tool_input, _elapsed):
                from blender_addon.tools.handlers import handle_read_script_draft, handle_write_script_draft
                if name == "write_script_draft":
                    raw = handle_write_script_draft(tool_input)
                elif name == "read_script_draft":
                    raw = handle_read_script_draft(tool_input)
                else:
                    raw = {"status": "success", "result": {"memory": {"node_count": 1}}}
                result_payload = raw.get("result", {}) if isinstance(raw, dict) else {}
                self._current_turn_tools.append({
                    "name": name,
                    "input": tool_input,
                    "result": json.dumps(raw, ensure_ascii=False)[:300],
                    "status": str(raw.get("status", "")),
                    "result_payload": result_payload if isinstance(result_payload, dict) else {},
                })
                return json.dumps(raw, ensure_ascii=False)

        existing = handle_write_script_draft({
            "block_name": "GN_Agent_Draft",
            "code": _complete_validation_code("Existing source draft"),
            "description": "Existing source draft",
            "tree_name": "Biomodelo_GN",
        })
        session = _FakeSession()
        ctx = TurnContext(
            session=session,
            message="corrige esse draft",
            meta=ClassifierMeta(turn_class=TurnClass.DRAFT_WORKSPACE),
            blend_path="",
            _runtime=_FakeRuntime(),
            knowledge_dir=Path("/nonexistent/knowledge/domain"),
        )

        result = handle_draft_workspace(ctx)

        self.assertIn("escrita foi bloqueada", result.response_text)
        text_block = sys.modules["bpy"].data.texts.get("GN_Agent_Draft")
        self.assertIsNotNone(text_block)
        self.assertEqual(int(existing["result"]["char_count"]), len(text_block.as_string()))
        self.assertEqual("write_confirmed_draft_revision", session.execution_state.pending_draft_action)

    def test_semantic_regression_block_becomes_preservation_retry_instruction(self):
        from blender_addon.handler import TurnContext
        from blender_addon.handler._drafting_support import handle_draft_workspace
        from blender_addon.runtime.router import ClassifierMeta, TurnClass
        from blender_addon.core.runtime import AgentRuntime
        from blender_addon.tools.handlers import handle_write_script_draft

        class _FakeRuntime:
            def __init__(self):
                self._messages = []
                self._session_memory = {
                    "last_goal": "Corrigir o mesmo draft vivo da ortese.",
                    "last_hypothesis": "A proxima revisao precisa preservar os anchors existentes.",
                    "target_tree": "Biomodelo_GN",
                    "relevant_nodes": ["ORTHOSIS_CONTEXT"],
                }
                self._session_state = {"tree_structural_memory": {}}
                self._draft_tool_policy = {
                    "goal_mode": "focal_correction",
                    "goal_guidance": {
                        "summary": "Apply the smallest safe correction to the current living draft.",
                        "suggested_output": "single_targeted_revision",
                        "focus_priorities": ["ORTHOSIS_CONTEXT", "Palm Width"],
                    },
                }
                self._current_turn_tools = []
                self.journal = types.SimpleNamespace(log_runtime_event=lambda **_: None)

            def _agent_loop(self, *_args, **_kwargs):
                self._execute_tool("write_script_draft", {
                    "block_name": "GN_Agent_Draft",
                    "code": _complete_validation_code("Regression candidate without anchors"),
                    "description": "Rewrite that loses anchors",
                    "tree_name": "Biomodelo_GN",
                }, 0)
                return "Ok, draft corrigido."

            def _execute_tool(self, name, tool_input, _elapsed):
                from blender_addon.tools.handlers import handle_read_script_draft, handle_write_script_draft
                if name == "write_script_draft":
                    tool_input = AgentRuntime._normalize_tool_input(self, name, tool_input)
                    raw = handle_write_script_draft(tool_input)
                elif name == "read_script_draft":
                    raw = handle_read_script_draft(tool_input)
                else:
                    raw = {"status": "success", "result": {"memory": {"node_count": 1}}}
                result_payload = raw.get("result", {}) if isinstance(raw, dict) else {}
                self._current_turn_tools.append({
                    "name": name,
                    "input": tool_input,
                    "result": json.dumps(raw, ensure_ascii=False)[:300],
                    "status": str(raw.get("status", "")),
                    "result_payload": result_payload if isinstance(result_payload, dict) else {},
                })
                return json.dumps(raw, ensure_ascii=False)

        existing = handle_write_script_draft({
            "block_name": "GN_Agent_Draft",
            "code": _code_referencing_existing_tree_node("ORTHOSIS_CONTEXT"),
            "description": "Existing anchored living draft",
            "tree_name": "Biomodelo_GN",
        })
        self.assertEqual("success", existing["status"])

        session = _FakeSession()
        ctx = TurnContext(
            session=session,
            message="corrige esse draft",
            meta=ClassifierMeta(turn_class=TurnClass.DRAFT_WORKSPACE),
            blend_path="",
            _runtime=_FakeRuntime(),
            knowledge_dir=Path("/nonexistent/knowledge/domain"),
        )

        result = handle_draft_workspace(ctx)

        self.assertIn("regrediu capacidades", result.response_text)
        self.assertEqual("write_confirmed_draft_revision", session.execution_state.pending_draft_action)
        self.assertIn("preserve the existing live node anchors", session.execution_state.pending_draft_prompt.lower())
        self.assertIn("ORTHOSIS_CONTEXT", session.execution_state.pending_draft_prompt)
        self.assertIn("smallest safe correction", session.execution_state.pending_draft_prompt)
        self.assertIn("single_targeted_revision", session.execution_state.pending_draft_prompt)

    def test_explicit_rebuild_mode_can_replace_living_draft_anchors_on_same_tree(self):
        from blender_addon.handler import TurnContext
        from blender_addon.handler._drafting_support import handle_draft_workspace
        from blender_addon.runtime.router import ClassifierMeta, TurnClass
        from blender_addon.core.runtime import AgentRuntime
        from blender_addon.tools.handlers import handle_write_script_draft

        class _FakeRuntime:
            def __init__(self):
                self._messages = []
                self._session_memory = {
                    "last_goal": "Reconstruir o mesmo draft vivo sem criar outro arquivo.",
                    "last_hypothesis": "O usuario autorizou um rebuild explicito do script atual.",
                    "target_tree": "Biomodelo_GN",
                    "relevant_nodes": ["ORTHOSIS_CONTEXT"],
                }
                self._session_state = {"tree_structural_memory": {}}
                self._draft_tool_policy = {}
                self._current_turn_tools = []
                self.journal = types.SimpleNamespace(log_runtime_event=lambda **_: None)

            def _agent_loop(self, *_args, **_kwargs):
                self._execute_tool("write_script_draft", {
                    "block_name": "GN_Agent_Draft",
                    "code": _complete_validation_code("Intentional rebuild on same tree"),
                    "description": "Intentional rebuild",
                    "tree_name": "Biomodelo_GN",
                }, 0)
                return "feito"

            def _execute_tool(self, name, tool_input, _elapsed):
                from blender_addon.tools.handlers import handle_read_script_draft, handle_write_script_draft
                if name == "write_script_draft":
                    tool_input = AgentRuntime._normalize_tool_input(self, name, tool_input)
                    raw = handle_write_script_draft(tool_input)
                elif name == "read_script_draft":
                    raw = handle_read_script_draft(tool_input)
                else:
                    raw = {"status": "success", "result": {"memory": {"node_count": 1}}}
                result_payload = raw.get("result", {}) if isinstance(raw, dict) else {}
                self._current_turn_tools.append({
                    "name": name,
                    "input": tool_input,
                    "result": json.dumps(raw, ensure_ascii=False)[:300],
                    "status": str(raw.get("status", "")),
                    "result_payload": result_payload if isinstance(result_payload, dict) else {},
                })
                return json.dumps(raw, ensure_ascii=False)

        existing = handle_write_script_draft({
            "block_name": "GN_Agent_Draft",
            "code": _code_referencing_existing_tree_node("ORTHOSIS_CONTEXT"),
            "description": "Existing anchored living draft",
            "tree_name": "Biomodelo_GN",
        })
        self.assertEqual("success", existing["status"])

        session = _FakeSession()
        ctx = TurnContext(
            session=session,
            message="pode reconstruir esse draft do zero, mas no mesmo arquivo",
            meta=ClassifierMeta(turn_class=TurnClass.DRAFT_WORKSPACE),
            blend_path="",
            _runtime=_FakeRuntime(),
            knowledge_dir=Path("/nonexistent/knowledge/domain"),
        )

        result = handle_draft_workspace(ctx)

        self.assertIn("Text Editor", result.response_text)
        text_block = sys.modules["bpy"].data.texts.get("GN_Agent_Draft")
        self.assertIsNotNone(text_block)
        self.assertNotIn("ORTHOSIS_CONTEXT", text_block.as_string())
        self.assertEqual("Biomodelo_GN", text_block.get("_draft_tree_name"))

    def test_short_confirmation_reuses_persisted_rebuild_mode_for_living_draft(self):
        from blender_addon.handler import TurnContext
        from blender_addon.handler._drafting_support import handle_draft_workspace
        from blender_addon.runtime.router import ClassifierMeta, TurnClass
        from blender_addon.core.runtime import AgentRuntime
        from blender_addon.tools.handlers import handle_write_script_draft

        class _FakeRuntime:
            def __init__(self):
                self._messages = []
                self._session_memory = {
                    "last_goal": "Reconstruir o mesmo draft vivo sem criar outro arquivo.",
                    "last_hypothesis": "O rebuild explicito ja foi aprovado no turno anterior.",
                    "target_tree": "Biomodelo_GN",
                    "relevant_nodes": ["ORTHOSIS_CONTEXT"],
                }
                self._session_state = {"tree_structural_memory": {}}
                self._draft_tool_policy = {}
                self._current_turn_tools = []
                self.journal = types.SimpleNamespace(log_runtime_event=lambda **_: None)

            def _agent_loop(self, *_args, **_kwargs):
                self._execute_tool("write_script_draft", {
                    "block_name": "GN_Agent_Draft",
                    "code": _complete_validation_code("Rebuild after short confirmation"),
                    "description": "Intentional rebuild after confirmation",
                    "tree_name": "Biomodelo_GN",
                }, 0)
                return "feito"

            def _execute_tool(self, name, tool_input, _elapsed):
                from blender_addon.tools.handlers import handle_read_script_draft, handle_write_script_draft
                if name == "write_script_draft":
                    tool_input = AgentRuntime._normalize_tool_input(self, name, tool_input)
                    raw = handle_write_script_draft(tool_input)
                elif name == "read_script_draft":
                    raw = handle_read_script_draft(tool_input)
                else:
                    raw = {"status": "success", "result": {"memory": {"node_count": 1}}}
                result_payload = raw.get("result", {}) if isinstance(raw, dict) else {}
                self._current_turn_tools.append({
                    "name": name,
                    "input": tool_input,
                    "result": json.dumps(raw, ensure_ascii=False)[:300],
                    "status": str(raw.get("status", "")),
                    "result_payload": result_payload if isinstance(result_payload, dict) else {},
                })
                return json.dumps(raw, ensure_ascii=False)

        existing = handle_write_script_draft({
            "block_name": "GN_Agent_Draft",
            "code": _code_referencing_existing_tree_node("ORTHOSIS_CONTEXT"),
            "description": "Existing anchored living draft",
            "tree_name": "Biomodelo_GN",
        })
        self.assertEqual("success", existing["status"])

        session = _FakeSession()
        session.execution_state.pending_draft_action = "write_confirmed_draft_revision"
        session.execution_state.pending_draft_prompt = "Assistant proposal: posso reconstruir o draft atual do zero no mesmo arquivo."
        session.execution_state.draft_edit_mode = "intentional_rebuild"
        ctx = TurnContext(
            session=session,
            message="pode",
            meta=ClassifierMeta(turn_class=TurnClass.DRAFT_WORKSPACE),
            blend_path="",
            _runtime=_FakeRuntime(),
            knowledge_dir=Path("/nonexistent/knowledge/domain"),
        )

        result = handle_draft_workspace(ctx)

        self.assertIn("Text Editor", result.response_text)
        text_block = sys.modules["bpy"].data.texts.get("GN_Agent_Draft")
        self.assertIsNotNone(text_block)
        self.assertNotIn("ORTHOSIS_CONTEXT", text_block.as_string())
        self.assertEqual("preserve_and_refine", session.execution_state.draft_edit_mode)

    def test_draft_workspace_diagnose_only_blocks_write_and_returns_analysis(self):
        from blender_addon.handler import TurnContext
        from blender_addon.handler._drafting_support import handle_draft_workspace
        from blender_addon.runtime.router import ClassifierMeta, TurnClass
        from blender_addon.core.runtime import AgentRuntime
        from blender_addon.tools.handlers import handle_write_script_draft

        class _FakeRuntime:
            def __init__(self):
                self._messages = []
                self._session_memory = {
                    "last_goal": "Entender por que o draft vivo da ortese nao funcionou.",
                    "last_hypothesis": "Talvez os anchors ou sockets estejam incorretos.",
                    "target_tree": "Biomodelo_GN",
                    "relevant_nodes": ["ORTHOSIS_CONTEXT"],
                }
                self._session_state = {"tree_structural_memory": {}}
                self._draft_tool_policy = {}
                self._draft_attempt_state = None
                self._current_turn_tools = []
                self.journal = types.SimpleNamespace(log_runtime_event=lambda **_: None)

            def _agent_loop(self, *_args, **_kwargs):
                self._execute_tool("write_script_draft", {
                    "block_name": "GN_Agent_Draft",
                    "code": _complete_validation_code("Should not be written during diagnosis"),
                    "description": "Unexpected diagnosis write",
                    "tree_name": "Biomodelo_GN",
                }, 0)
                return "Ainda nao tenho um diagnostico bom."

            def _execute_tool(self, name, tool_input, _elapsed):
                from blender_addon.tools.handlers import handle_read_script_draft, handle_write_script_draft
                block_reason = AgentRuntime._enforce_draft_tool_policy(self, name)
                if block_reason:
                    raw = {"status": "blocked", "error": block_reason, "result": {}}
                elif name == "write_script_draft":
                    tool_input = AgentRuntime._normalize_tool_input(self, name, tool_input)
                    raw = handle_write_script_draft(tool_input)
                elif name == "read_script_draft":
                    raw = handle_read_script_draft(tool_input)
                elif name == "prepare_draft_context":
                    raw = {"status": "success", "result": _prepared_context_result()}
                else:
                    raw = {"status": "success", "result": {"memory": {"node_count": 1}}}
                AgentRuntime._record_draft_attempt_tool_result(
                    self,
                    tool_name=name,
                    tool_input=tool_input,
                    runtime_raw=raw,
                )
                result_payload = raw.get("result", {}) if isinstance(raw, dict) else {}
                self._current_turn_tools.append({
                    "name": name,
                    "input": tool_input,
                    "result": json.dumps(raw, ensure_ascii=False)[:300],
                    "status": str(raw.get("status", "")),
                    "result_payload": result_payload if isinstance(result_payload, dict) else {},
                })
                return json.dumps(raw, ensure_ascii=False)

            def _block_draft_tool(self, tool_name, reason, policy):
                return AgentRuntime._block_draft_tool(self, tool_name, reason, policy)

        existing = handle_write_script_draft({
            "block_name": "GN_Agent_Draft",
            "code": _code_with_semantic_expectations(
                "ORTHOSIS_CONTEXT",
                parameter_name="Palm Width",
                region_name="Metacarpos",
            ),
            "description": "Existing living draft for diagnosis",
            "tree_name": "Biomodelo_GN",
        })
        self.assertEqual("success", existing["status"])

        session = _FakeSession()
        session.execution_state.last_execution_outcome = "executed_no_effect"
        session.execution_state.last_execution_notes = "Nenhum slider funcionou na palma e nos metacarpos."
        session.execution_state.current_draft = types.SimpleNamespace(
            block_name="GN_Agent_Draft",
            tree_name="Biomodelo_GN",
            version=int(existing["result"]["version"]),
            last_written_chars=int(existing["result"]["char_count"]),
        )
        ctx = TurnContext(
            session=session,
            message="faz um diagnostico e me explica por que esse draft nao funcionou antes de mexer nele",
            meta=ClassifierMeta(turn_class=TurnClass.DRAFT_WORKSPACE),
            blend_path="",
            _runtime=_FakeRuntime(),
            knowledge_dir=Path("/nonexistent/knowledge/domain"),
        )

        result = handle_draft_workspace(ctx)
        tool_status = {call["name"]: call["status"] for call in ctx._runtime._current_turn_tools}

        self.assertEqual("blocked", tool_status.get("write_script_draft"))
        self.assertIn("Likely failure", result.response_text)
        self.assertIn("Direcao de reparo", result.response_text)
        self.assertIn("Next step", result.response_text)
        self.assertNotIn("Strategy A", result.response_text)
        self.assertNotIn("Text Editor", result.response_text)

    def test_execution_feedback_retry_cycle_updates_same_draft_and_clears_retry_state(self):
        from blender_addon.handler import TurnContext
        from blender_addon.handler._drafting_support import handle_draft_workspace
        from blender_addon.handler.feedback import handle_execution_feedback
        from blender_addon.runtime.router import ClassifierMeta, TurnClass
        from blender_addon.core.runtime import AgentRuntime
        from blender_addon.tools.handlers import handle_write_script_draft

        class _RetryRuntime:
            def __init__(self):
                self._messages = []
                self._session_memory = {
                    "last_goal": "Fazer a fase da ortese para palma e metacarpos.",
                    "last_hypothesis": "O retry deve evoluir o mesmo draft vivo.",
                    "target_tree": "Biomodelo_GN",
                    "relevant_nodes": ["ORTHOSIS_CONTEXT"],
                }
                self._session_state = {"tree_structural_memory": {}}
                self._draft_tool_policy = {}
                self._draft_attempt_state = None
                self._current_turn_tools = []
                self.journal = types.SimpleNamespace(log_runtime_event=lambda **_: None)

            def _agent_loop(self, *_args, **_kwargs):
                self._execute_tool("write_script_draft", {
                    "block_name": "GN_Agent_Draft",
                    "code": _code_with_semantic_expectations(
                        "ORTHOSIS_CONTEXT",
                        parameter_name="Palm Width",
                        region_name="Metacarpos",
                    ),
                    "description": "Retry revision preserving palm/metacarpal scope",
                    "tree_name": "Biomodelo_GN",
                }, 0)
                return "feito"

            def _execute_tool(self, name, tool_input, _elapsed):
                from blender_addon.tools.handlers import handle_read_script_draft, handle_write_script_draft
                block_reason = AgentRuntime._enforce_draft_tool_policy(self, name)
                if block_reason:
                    raw = {"status": "blocked", "error": block_reason, "result": {}}
                elif name == "write_script_draft":
                    tool_input = AgentRuntime._normalize_tool_input(self, name, tool_input)
                    raw = handle_write_script_draft(tool_input)
                elif name == "read_script_draft":
                    raw = handle_read_script_draft(tool_input)
                elif name == "prepare_draft_context":
                    raw = {"status": "success", "result": _prepared_context_result()}
                else:
                    raw = {"status": "success", "result": {"memory": {"node_count": 1}}}
                AgentRuntime._record_draft_attempt_tool_result(
                    self,
                    tool_name=name,
                    tool_input=tool_input,
                    runtime_raw=raw,
                )
                result_payload = raw.get("result", {}) if isinstance(raw, dict) else {}
                self._current_turn_tools.append({
                    "name": name,
                    "input": tool_input,
                    "result": json.dumps(raw, ensure_ascii=False)[:300],
                    "status": str(raw.get("status", "")),
                    "result_payload": result_payload if isinstance(result_payload, dict) else {},
                })
                return json.dumps(raw, ensure_ascii=False)

            def _block_draft_tool(self, tool_name, reason, policy):
                return AgentRuntime._block_draft_tool(self, tool_name, reason, policy)

        first = handle_write_script_draft({
            "block_name": "GN_Agent_Draft",
            "code": _code_with_semantic_expectations(
                "ORTHOSIS_CONTEXT",
                parameter_name="Palm Width",
                region_name="Metacarpos",
            ),
            "description": "Initial palm/metacarpal living draft",
            "tree_name": "Biomodelo_GN",
            "expected_parameter_refs": ["Palm Width"],
            "expected_focus_regions": ["Metacarpos"],
        })
        self.assertEqual("success", first["status"])

        session = _FakeSession()
        session.execution_state.current_draft = types.SimpleNamespace(
            block_name="GN_Agent_Draft",
            tree_name="Biomodelo_GN",
            version=int(first["result"]["version"]),
            last_written_chars=int(first["result"]["char_count"]),
        )
        feedback_ctx = TurnContext(
            session=session,
            message="Nenhum slider funcionou na palma e nos metacarpos",
            meta=ClassifierMeta(turn_class=TurnClass.EXECUTION_FEEDBACK),
            blend_path="",
            _runtime=_RetryRuntime(),
            knowledge_dir=Path("/nonexistent/knowledge/domain"),
        )

        feedback = handle_execution_feedback(feedback_ctx)

        self.assertIn("Registrei o resultado", feedback.response_text)
        self.assertTrue(session.execution_state.retry_requires_draft_change)
        self.assertEqual("executed_no_effect", session.execution_state.last_execution_outcome)

        retry_ctx = TurnContext(
            session=session,
            message="consegue tentar denovo entao?",
            meta=ClassifierMeta(turn_class=TurnClass.DRAFT_WORKSPACE),
            blend_path="",
            _runtime=_RetryRuntime(),
            knowledge_dir=Path("/nonexistent/knowledge/domain"),
        )

        result = handle_draft_workspace(retry_ctx)

        self.assertIn("Text Editor", result.response_text)
        self.assertFalse(session.execution_state.retry_requires_draft_change)
        self.assertFalse(session.execution_state.scene_reverted_by_user)
        text_block = sys.modules["bpy"].data.texts.get("GN_Agent_Draft")
        self.assertIsNotNone(text_block)
        self.assertIn("Palm Width", text_block.as_string())
        self.assertIn("Metacarpos", text_block.as_string())

    def test_execution_feedback_diagnosis_prefers_archived_failed_draft(self):
        from blender_addon.handler import TurnContext
        from blender_addon.handler.feedback import handle_execution_feedback
        from blender_addon.runtime.router import ClassifierMeta, TurnClass

        class _FeedbackRuntime:
            def __init__(self, project_root: str):
                self.project_root = Path(project_root)
                self._messages = [{"role": "assistant", "content": "old"}]
                self._session_state = {
                    "tree_structural_memory": {
                        "tree_name": "Biomodelo_GN",
                        "node_count": 3,
                        "nodes": [
                            {"name": "TF_Metacarpo1.001", "parent_frame": "Metacarpos"},
                            {"name": "TF_Metacarpo2", "parent_frame": "Falanges1"},
                            {"name": "Cube_Metacarpo1.001", "parent_frame": "Metacarpos"},
                        ],
                        "marker": {"node_names": ["TF_Metacarpo1.001", "TF_Metacarpo2", "Cube_Metacarpo1.001"]},
                    }
                }
                self.tool_calls: list[str] = []
                self.last_prompt = ""
                self.journal = _FakeJournal()

            def _execute_tool(self, name, tool_input, _elapsed):
                self.tool_calls.append(name)
                if name == "read_script_draft":
                    return json.dumps({
                        "status": "success",
                        "result": {
                            "block_name": "GN_Agent_Draft",
                            "version": 4,
                            "content": "# TEXT_EDITOR_DRAFT_SHOULD_NOT_BE_USED\nprint('live')",
                            "char_count": 48,
                        },
                    })
                return json.dumps({"status": "success", "result": {"memory": self._session_state["tree_structural_memory"]}})

            def _request_text_response(self, *, system, messages, max_tokens):
                content = messages[0]["content"]
                self.last_prompt = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
                return (
                    "Sintoma:\nMexeu uma falange.\n\n"
                    "Hipotese:\nO draft falho usou o alvo errado.\n\n"
                    "Evidencia:\nLi a revisão arquivada.\n\n"
                    "Confianca:\nMedia.\n\n"
                    "Limitacoes:\nPrecisa confirmar o subgrafo.\n\n"
                    "Opcoes:\nA. Conservadora.\nB. Robusta.\n\n"
                    "Pergunta:\nQual opção seguimos?"
                )

        session = _FakeSession()
        session.identity = types.SimpleNamespace(session_id="sess-post-failure")
        session.execution_state.current_draft = types.SimpleNamespace(
            block_name="GN_Agent_Draft",
            tree_name="Biomodelo_GN",
            version=4,
            last_written_chars=46,
        )
        runtime = _FeedbackRuntime("C:\\not-used")
        ctx = TurnContext(
            session=session,
            message="Mexeu uma falange, nada a ver. Reverti.",
            meta=ClassifierMeta(turn_class=TurnClass.EXECUTION_FEEDBACK),
            blend_path="",
            _runtime=runtime,
            knowledge_dir=Path("/nonexistent/knowledge/domain"),
        )

        with patch(
            "blender_addon.handler.feedback_evidence._read_archived_draft_revision",
            return_value={
                "block_name": "GN_Agent_Draft",
                "content": (
                    "# ARCHIVED_FAILED_DRAFT\n"
                    "nodes = tree.nodes\n"
                    "mc1_tf = nodes.get('TF_Metacarpo1.001')\n"
                    "mc2_tf = nodes.get('TF_Metacarpo2')\n"
                    "disconnect_translation(mc2_tf)\n"
                    "mc2_tf.inputs['Translation'].default_value = (1, 0, 0)\n"
                    "print('Nenhuma falange alterada')\n"
                ),
                "version": 4,
                "char_count": 48,
                "draft_archive_path": "runtime/draft_history/sess-post-failure/r000004_GN_Agent_Draft.py",
                "source": "draft_history",
            },
        ):
            result = handle_execution_feedback(ctx)

        self.assertIn("ARCHIVED_FAILED_DRAFT", runtime.last_prompt)
        self.assertIn("Failed draft static evidence", runtime.last_prompt)
        self.assertIn("TF_Metacarpo2.Translation", runtime.last_prompt)
        self.assertIn("Falanges1", runtime.last_prompt)
        self.assertNotIn("TEXT_EDITOR_DRAFT_SHOULD_NOT_BE_USED", runtime.last_prompt)
        self.assertIn("[Repair conversation guidance]", runtime.last_prompt)
        self.assertNotIn("write_script_draft", runtime.tool_calls)
        self.assertIn("draft claims no falanges changed, but touched nodes/frames include falange-related names", result.response_text)
        self.assertIn("Quer que eu siga por essa direção", result.response_text)
        self.assertIn("só vou escrever uma nova revisão depois dessa confirmação", result.response_text)
        self.assertEqual(4, session.execution_state.last_failed_revision)
        self.assertEqual("STRATEGY_PROPOSED", session.execution_state.post_failure_state)
        self.assertEqual("STRATEGY_PROPOSED", session.execution_state.session_state)
        self.assertIsNotNone(getattr(session.execution_state, "pending_user_decision", None))
        self.assertEqual(["sim"], session.execution_state.pending_user_decision.options)
        self.assertEqual(4, session.execution_state.proposed_strategy_revision)
        diagnosis_events = [event for event in runtime.journal.events if event["event_type"] == "script_draft_execution_diagnosis"]
        self.assertEqual("draft_history", diagnosis_events[-1]["payload"]["failed_draft_source"])
        self.assertTrue(diagnosis_events[-1]["payload"]["diagnosis_contract_satisfied"])
        self.assertEqual([], diagnosis_events[-1]["payload"]["diagnosis_missing_sections"])
        self.assertEqual("STRATEGY_PROPOSED", diagnosis_events[-1]["payload"]["post_failure_state"])
        self.assertTrue(diagnosis_events[-1]["payload"]["static_evidence_available"])
        self.assertIn("TF_Metacarpo2", diagnosis_events[-1]["payload"]["static_evidence_touched_nodes"])

    def test_failed_draft_static_evidence_detects_touched_nodes_and_semantic_mismatch(self):
        from blender_addon.handler._drafting_support import (
            _extract_failed_draft_static_evidence,
            _render_failed_draft_evidence_pack,
        )

        content = (
            "nodes = tree.nodes\n"
            "mc1_tf = nodes.get('TF_Metacarpo1.001')\n"
            "mc2_tf = nodes.get('TF_Metacarpo2')\n"
            "for item in tree.interface.items_tree:\n"
            "    if getattr(item, 'identifier', None) == 'Socket_30':\n"
            "        largura = item.default_value\n"
            "disconnect_translation(mc2_tf)\n"
            "mc1_tf.inputs['Translation'].default_value = (-1, 0, 0)\n"
            "mc2_tf.inputs['Translation'].default_value = (1, 0, 0)\n"
            "print('Nenhuma falange alterada')\n"
        )
        structural_memory = {
            "node_count": 3,
            "nodes": [
                {"name": "TF_Metacarpo1.001", "parent_frame": "Metacarpos"},
                {"name": "TF_Metacarpo2", "parent_frame": "Falanges1"},
                {"name": "Group Input", "parent_frame": ""},
            ],
        }

        evidence = _extract_failed_draft_static_evidence(content, structural_memory)
        rendered = _render_failed_draft_evidence_pack(evidence)

        self.assertIn({"node": "TF_Metacarpo2", "socket": "Translation"}, evidence["socket_writes"])
        self.assertIn("TF_Metacarpo2", evidence["disconnect_translation_targets"])
        self.assertIn("Socket_30", evidence["interface_socket_reads"])
        self.assertTrue(any("TF_Metacarpo2" in item and "Falanges1" in item for item in evidence["semantic_mismatches"]))
        self.assertIn("TF_Metacarpo2.Translation", rendered)
        self.assertIn("suspicious_mismatches", rendered)

    def test_execution_feedback_diagnosis_enforces_contract_when_model_is_sparse(self):
        from blender_addon.handler import TurnContext
        from blender_addon.handler.feedback import handle_execution_feedback
        from blender_addon.runtime.router import ClassifierMeta, TurnClass

        class _SparseDiagnosisRuntime:
            def __init__(self):
                self._messages = [{"role": "assistant", "content": "old"}]
                self._session_state = {
                    "tree_structural_memory": {
                        "tree_name": "Biomodelo_GN",
                        "node_count": 3,
                    }
                }
                self.tool_calls: list[str] = []
                self.last_prompt = ""
                self.journal = _FakeJournal()

            def _execute_tool(self, name, tool_input, _elapsed):
                self.tool_calls.append(name)
                if name == "read_script_draft":
                    return json.dumps({
                        "status": "success",
                        "result": {
                            "block_name": "GN_Agent_Draft",
                            "version": 7,
                            "content": "# failed slider draft\nslider = 'Palm Width'\n",
                            "char_count": 43,
                        },
                    })
                return json.dumps({"status": "success", "result": {"memory": self._session_state["tree_structural_memory"]}})

            def _request_text_response(self, *, system, messages, max_tokens):
                content = messages[0]["content"]
                self.last_prompt = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
                return "ok"

        session = _FakeSession()
        session.execution_state.current_draft = types.SimpleNamespace(
            block_name="GN_Agent_Draft",
            tree_name="Biomodelo_GN",
            version=7,
            last_written_chars=43,
        )
        runtime = _SparseDiagnosisRuntime()
        ctx = TurnContext(
            session=session,
            message="Rodei e nada aconteceu.",
            meta=ClassifierMeta(turn_class=TurnClass.EXECUTION_FEEDBACK),
            blend_path="",
            _runtime=runtime,
            knowledge_dir=Path("/nonexistent/knowledge/domain"),
        )

        result = handle_execution_feedback(ctx)

        self.assertIn("[Repair conversation guidance]", runtime.last_prompt)
        self.assertNotIn("write_script_draft", runtime.tool_calls)
        self.assertIn("Quer que eu siga por essa direção", result.response_text)
        self.assertIn("só vou escrever uma nova revisão depois dessa confirmação", result.response_text)
        self.assertEqual("STRATEGY_PROPOSED", session.execution_state.post_failure_state)
        self.assertIsNotNone(getattr(session.execution_state, "pending_user_decision", None))
        self.assertEqual(["sim"], session.execution_state.pending_user_decision.options)
        self.assertEqual(7, session.execution_state.proposed_strategy_revision)
        diagnosis_events = [event for event in runtime.journal.events if event["event_type"] == "script_draft_execution_diagnosis"]
        payload = diagnosis_events[-1]["payload"]
        self.assertTrue(payload["diagnosis_contract_satisfied"])
        self.assertEqual([], payload["diagnosis_missing_sections"])

    def test_semantic_retry_guidance_survives_full_living_draft_cycle(self):
        from blender_addon.handler import TurnContext
        from blender_addon.handler._drafting_support import handle_draft_workspace
        from blender_addon.handler.feedback import handle_execution_feedback
        from blender_addon.runtime.router import ClassifierMeta, TurnClass
        from blender_addon.core.runtime import AgentRuntime
        from blender_addon.tools.handlers import handle_write_script_draft

        class _SequenceRuntime:
            def __init__(self, codes: list[str]):
                self._messages = []
                self._session_memory = {
                    "last_goal": "Evoluir a fase da ortese para palma e metacarpos no mesmo script.",
                    "last_hypothesis": "A revisao precisa preservar semantica e escopo clinico.",
                    "target_tree": "Biomodelo_GN",
                    "relevant_nodes": ["ORTHOSIS_CONTEXT"],
                }
                self._session_state = {"tree_structural_memory": {}}
                self._draft_tool_policy = {}
                self._draft_attempt_state = None
                self._current_turn_tools = []
                self._codes = list(codes)
                self.journal = types.SimpleNamespace(log_runtime_event=lambda **_: None)

            def _agent_loop(self, *_args, **_kwargs):
                candidate = self._codes.pop(0)
                self._execute_tool("write_script_draft", {
                    "block_name": "GN_Agent_Draft",
                    "code": candidate,
                    "description": "Draft revision from retry sequence",
                    "tree_name": "Biomodelo_GN",
                }, 0)
                return "feito"

            def _execute_tool(self, name, tool_input, _elapsed):
                from blender_addon.tools.handlers import handle_read_script_draft, handle_write_script_draft
                block_reason = AgentRuntime._enforce_draft_tool_policy(self, name)
                if block_reason:
                    raw = {"status": "blocked", "error": block_reason, "result": {}}
                elif name == "write_script_draft":
                    tool_input = AgentRuntime._normalize_tool_input(self, name, tool_input)
                    raw = handle_write_script_draft(tool_input)
                elif name == "read_script_draft":
                    raw = handle_read_script_draft(tool_input)
                elif name == "prepare_draft_context":
                    raw = {"status": "success", "result": _prepared_context_result()}
                else:
                    raw = {"status": "success", "result": {"memory": {"node_count": 1}}}
                AgentRuntime._record_draft_attempt_tool_result(
                    self,
                    tool_name=name,
                    tool_input=tool_input,
                    runtime_raw=raw,
                )
                result_payload = raw.get("result", {}) if isinstance(raw, dict) else {}
                self._current_turn_tools.append({
                    "name": name,
                    "input": tool_input,
                    "result": json.dumps(raw, ensure_ascii=False)[:300],
                    "status": str(raw.get("status", "")),
                    "result_payload": result_payload if isinstance(result_payload, dict) else {},
                })
                return json.dumps(raw, ensure_ascii=False)

            def _block_draft_tool(self, tool_name, reason, policy):
                return AgentRuntime._block_draft_tool(self, tool_name, reason, policy)

        first = handle_write_script_draft({
            "block_name": "GN_Agent_Draft",
            "code": _code_with_semantic_expectations(
                "ORTHOSIS_CONTEXT",
                parameter_name="Palm Width",
                region_name="Metacarpos",
            ),
            "description": "Initial semantic living draft",
            "tree_name": "Biomodelo_GN",
            "expected_parameter_refs": ["Palm Width"],
            "expected_focus_regions": ["Metacarpos"],
        })
        self.assertEqual("success", first["status"])

        session = _FakeSession()
        session.execution_state.current_draft = types.SimpleNamespace(
            block_name="GN_Agent_Draft",
            tree_name="Biomodelo_GN",
            version=int(first["result"]["version"]),
            last_written_chars=int(first["result"]["char_count"]),
        )
        feedback_ctx = TurnContext(
            session=session,
            message="Nenhum slider funcionou na palma e nos metacarpos",
            meta=ClassifierMeta(turn_class=TurnClass.EXECUTION_FEEDBACK),
            blend_path="",
            _runtime=_SequenceRuntime([]),
            knowledge_dir=Path("/nonexistent/knowledge/domain"),
        )
        handle_execution_feedback(feedback_ctx)

        blocked_ctx = TurnContext(
            session=session,
            message="consegue tentar denovo entao?",
            meta=ClassifierMeta(turn_class=TurnClass.DRAFT_WORKSPACE),
            blend_path="",
            _runtime=_SequenceRuntime([
                _code_referencing_existing_tree_node("ORTHOSIS_CONTEXT"),
            ]),
            knowledge_dir=Path("/nonexistent/knowledge/domain"),
        )
        blocked = handle_draft_workspace(blocked_ctx)

        self.assertIn("regrediu capacidades", blocked.response_text)
        self.assertTrue(session.execution_state.retry_requires_draft_change)
        self.assertIn("Palm Width", session.execution_state.pending_draft_prompt)
        self.assertIn("preservation fix", session.execution_state.pending_draft_prompt)

        success_ctx = TurnContext(
            session=session,
            message="tenta de novo preservando isso",
            meta=ClassifierMeta(turn_class=TurnClass.DRAFT_WORKSPACE),
            blend_path="",
            _runtime=_SequenceRuntime([
                _code_with_semantic_expectations(
                    "ORTHOSIS_CONTEXT",
                    parameter_name="Palm Width",
                    region_name="Metacarpos",
                ),
            ]),
            knowledge_dir=Path("/nonexistent/knowledge/domain"),
        )
        success = handle_draft_workspace(success_ctx)

        self.assertIn("Text Editor", success.response_text)
        self.assertFalse(session.execution_state.retry_requires_draft_change)
        self.assertEqual("", session.execution_state.pending_draft_action)
        self.assertEqual("", session.execution_state.pending_draft_prompt)

    def test_explicit_retarget_mode_can_move_living_draft_to_other_tree(self):
        from blender_addon.handler import TurnContext
        from blender_addon.handler._drafting_support import handle_draft_workspace
        from blender_addon.runtime.router import ClassifierMeta, TurnClass
        from blender_addon.core.runtime import AgentRuntime
        from blender_addon.tools.handlers import handle_write_script_draft

        sys.modules["bpy"].data.node_groups.new("Other_Orthosis_Tree", "GeometryNodeTree")

        class _FakeRuntime:
            def __init__(self):
                self._messages = []
                self._session_memory = {
                    "last_goal": "Retarget do mesmo draft vivo para outra arvore.",
                    "last_hypothesis": "O usuario pediu explicitamente para mover o draft para outro target.",
                    "target_tree": "Biomodelo_GN",
                    "relevant_nodes": [],
                }
                self._session_state = {"tree_structural_memory": {}}
                self._draft_tool_policy = {}
                self._current_turn_tools = []
                self.journal = types.SimpleNamespace(log_runtime_event=lambda **_: None)

            def _agent_loop(self, *_args, **_kwargs):
                self._execute_tool("write_script_draft", {
                    "block_name": "GN_Agent_Draft",
                    "code": _complete_validation_code("Retargeted living draft"),
                    "description": "Intentional retarget",
                    "tree_name": "Other_Orthosis_Tree",
                }, 0)
                return "feito"

            def _execute_tool(self, name, tool_input, _elapsed):
                from blender_addon.tools.handlers import handle_read_script_draft, handle_write_script_draft
                if name == "write_script_draft":
                    tool_input = AgentRuntime._normalize_tool_input(self, name, tool_input)
                    raw = handle_write_script_draft(tool_input)
                elif name == "read_script_draft":
                    raw = handle_read_script_draft(tool_input)
                else:
                    raw = {"status": "success", "result": {"memory": {"node_count": 1}}}
                result_payload = raw.get("result", {}) if isinstance(raw, dict) else {}
                self._current_turn_tools.append({
                    "name": name,
                    "input": tool_input,
                    "result": json.dumps(raw, ensure_ascii=False)[:300],
                    "status": str(raw.get("status", "")),
                    "result_payload": result_payload if isinstance(result_payload, dict) else {},
                })
                return json.dumps(raw, ensure_ascii=False)

        existing = handle_write_script_draft({
            "block_name": "GN_Agent_Draft",
            "code": _complete_validation_code("Existing biomodel draft"),
            "description": "Existing biomodel draft",
            "tree_name": "Biomodelo_GN",
        })
        self.assertEqual("success", existing["status"])

        session = _FakeSession()
        ctx = TurnContext(
            session=session,
            message="pode retarget esse mesmo draft para a arvore Other_Orthosis_Tree",
            meta=ClassifierMeta(turn_class=TurnClass.DRAFT_WORKSPACE),
            blend_path="",
            _runtime=_FakeRuntime(),
            knowledge_dir=Path("/nonexistent/knowledge/domain"),
        )

        result = handle_draft_workspace(ctx)

        self.assertIn("Text Editor", result.response_text)
        text_block = sys.modules["bpy"].data.texts.get("GN_Agent_Draft")
        self.assertIsNotNone(text_block)
        self.assertEqual("Other_Orthosis_Tree", text_block.get("_draft_tree_name"))

    def test_economy_retry_stops_early_when_draft_block_is_missing(self):
        from blender_addon.handler import TurnContext
        from blender_addon.handler._drafting_support import handle_draft_workspace
        from blender_addon.runtime.router import ClassifierMeta, TurnClass

        class _FakeRuntime:
            def __init__(self):
                self._messages = []
                self._session_memory = {
                    "last_goal": "Corrigir draft existente.",
                    "last_hypothesis": "Usar o draft salvo como fonte de verdade.",
                    "target_tree": "Biomodelo_GN",
                    "relevant_nodes": ["ORTHOSIS_CONTEXT"],
                }
                self._session_state = {"tree_structural_memory": {}}
                self._draft_tool_policy = {}
                self._current_turn_tools = []
                self.journal = types.SimpleNamespace(log_runtime_event=lambda **_: None)
                self.agent_loop_called = False

            def _agent_loop(self, *_args, **_kwargs):
                self.agent_loop_called = True
                return "nao deveria chegar aqui"

            def _execute_tool(self, name, tool_input, _elapsed):
                if name == "read_script_draft":
                    raw = {"status": "error", "error": "Text block 'GN_Agent_Draft' not found.", "result": {"available_text_blocks": ["GN Chat Prompt"]}}
                else:
                    raw = {"status": "success", "result": {"memory": {"node_count": 1}}}
                payload = raw.get("result", {}) if isinstance(raw, dict) else {}
                self._current_turn_tools.append({
                    "name": name,
                    "input": tool_input,
                    "result": json.dumps(raw, ensure_ascii=False)[:300],
                    "status": str(raw.get("status", "")),
                    "result_payload": payload if isinstance(payload, dict) else {},
                })
                return json.dumps(raw, ensure_ascii=False)

        session = _FakeSession()
        ctx = TurnContext(
            session=session,
            message="Vamos tentar escrever esse draft denovo?",
            meta=ClassifierMeta(turn_class=TurnClass.DRAFT_WORKSPACE),
            blend_path="",
            _runtime=_FakeRuntime(),
            knowledge_dir=Path("/nonexistent/knowledge/domain"),
        )

        result = handle_draft_workspace(ctx)

        self.assertIn("Nao encontrei o bloco", result.response_text)
        self.assertFalse(ctx._runtime.agent_loop_called)

    def test_economy_retry_blocks_investigation_and_writes_once(self):
        from blender_addon.handler import TurnContext
        from blender_addon.handler._drafting_support import handle_draft_workspace
        from blender_addon.runtime.router import ClassifierMeta, TurnClass
        from blender_addon.tools.handlers import handle_write_script_draft

        class _FakeRuntime:
            def __init__(self):
                self._messages = []
                self._session_memory = {
                    "last_goal": "Corrigir draft da ortese sem gastar rounds investigando de novo.",
                    "last_hypothesis": "A escrita anterior falhou; a proxima deve ser uma revisao completa.",
                    "target_tree": "Biomodelo_GN",
                    "relevant_nodes": ["ORTHOSIS_CONTEXT"],
                }
                self._session_state = {
                    "tree_structural_memory": {
                        "Biomodelo_GN": {
                            "tree_name": "Biomodelo_GN",
                            "node_count": 12,
                            "stale": False,
                        }
                    }
                }
                self._draft_tool_policy = {}
                self._current_turn_tools = []
                self.journal = types.SimpleNamespace(log_runtime_event=lambda **_: None)

            def _agent_loop(self, system, *_args, **_kwargs):
                self._execute_tool("get_active_frame_context", {
                    "tree_name": "Biomodelo_GN",
                    "frame_name": "Metacarpos",
                }, 0)
                self._execute_tool("write_script_draft", {
                    "block_name": "GN_Agent_Draft",
                    "code": _complete_validation_code("Economy retry saved"),
                    "description": "Economy retry complete revision",
                    "tree_name": "Biomodelo_GN",
                }, 0)
                return "feito"

            def _execute_tool(self, name, tool_input, _elapsed):
                from blender_addon.core.runtime import AgentRuntime
                from blender_addon.tools.handlers import handle_read_script_draft, handle_write_script_draft
                block_reason = AgentRuntime._enforce_draft_tool_policy(self, name)
                if block_reason:
                    raw = {"status": "blocked", "error": block_reason}
                elif name == "write_script_draft":
                    raw = handle_write_script_draft(tool_input)
                elif name == "read_script_draft":
                    raw = handle_read_script_draft(tool_input)
                else:
                    raw = {"status": "success", "result": {"memory": {"node_count": 1}}}
                payload = raw.get("result", {}) if isinstance(raw, dict) else {}
                self._current_turn_tools.append({
                    "name": name,
                    "input": tool_input,
                    "result": json.dumps(raw, ensure_ascii=False)[:300],
                    "status": str(raw.get("status", "")),
                    "result_payload": payload if isinstance(payload, dict) else {},
                })
                return json.dumps(raw, ensure_ascii=False)

            def _block_draft_tool(self, tool_name, reason, policy):
                return f"BLOCKED: {tool_name} ({reason})"

        handle_write_script_draft({
            "block_name": "GN_Agent_Draft",
            "code": _complete_validation_code("Existing source draft"),
            "description": "Existing source draft",
            "tree_name": "Biomodelo_GN",
        })
        session = _FakeSession()
        session.execution_state.pending_draft_action = "write_confirmed_draft_revision"
        session.execution_state.pending_draft_prompt = "Escrita anterior falhou."
        ctx = TurnContext(
            session=session,
            message="consegue tentar denovo entao?",
            meta=ClassifierMeta(turn_class=TurnClass.DRAFT_WORKSPACE),
            blend_path="",
            _runtime=_FakeRuntime(),
            knowledge_dir=Path("/nonexistent/knowledge/domain"),
        )

        result = handle_draft_workspace(ctx)
        tool_status = {call["name"]: call["status"] for call in ctx._runtime._current_turn_tools}

        self.assertEqual("success", tool_status.get("get_active_frame_context"))
        self.assertEqual("success", tool_status.get("write_script_draft"))
        self.assertIn("Text Editor", result.response_text)

    def test_draft_workspace_turns_raw_chat_code_into_text_editor_write(self):
        from blender_addon.handler import TurnContext
        from blender_addon.handler._drafting_support import handle_draft_workspace
        from blender_addon.runtime.router import ClassifierMeta, TurnClass

        class _FakeRuntime:
            def __init__(self):
                self._messages = []
                self._session_memory = {"last_goal": "Fazer uma ortese de palma/metacarpos."}
                self._session_state = {"tree_structural_memory": {}}
                self._draft_tool_policy = {}
                self._current_turn_tools = []
                self.journal = types.SimpleNamespace(log_runtime_event=lambda **_: None)

            def _agent_loop(self, *_args, **_kwargs):
                return _complete_validation_code("Raw chat code should be saved")

            def _execute_tool(self, name, tool_input, _elapsed):
                from blender_addon.tools.handlers import handle_read_script_draft, handle_write_script_draft
                if name == "write_script_draft":
                    raw = handle_write_script_draft(tool_input)
                elif name == "read_script_draft":
                    raw = handle_read_script_draft(tool_input)
                else:
                    raw = {"status": "success", "result": {"memory": {"node_count": 1}}}
                payload = raw.get("result", {}) if isinstance(raw, dict) else {}
                self._current_turn_tools.append({
                    "name": name,
                    "input": tool_input,
                    "result": json.dumps(raw, ensure_ascii=False)[:300],
                    "status": str(raw.get("status", "")),
                    "result_payload": payload if isinstance(payload, dict) else {},
                })
                return json.dumps(raw, ensure_ascii=False)

        ctx = TurnContext(
            session=_FakeSession(),
            message="corrige esse draft",
            meta=ClassifierMeta(turn_class=TurnClass.DRAFT_WORKSPACE),
            blend_path="",
            _runtime=_FakeRuntime(),
            knowledge_dir=Path("/nonexistent/knowledge/domain"),
        )

        result = handle_draft_workspace(ctx)

        self.assertIn("Text Editor", result.response_text)
        self.assertNotIn("import bpy", result.response_text)
        self.assertIsNotNone(sys.modules["bpy"].data.texts.get("GN_Agent_Draft"))

    def test_draft_workspace_does_not_salvage_raw_chat_code_after_truncation(self):
        from blender_addon.handler import TurnContext
        from blender_addon.handler._drafting_support import handle_draft_workspace
        from blender_addon.runtime.router import ClassifierMeta, TurnClass

        class _FakeRuntime:
            def __init__(self):
                self._messages = []
                self._session_memory = {"last_goal": "Fazer uma ortese de palma/metacarpos."}
                self._session_state = {"tree_structural_memory": {}}
                self._draft_tool_policy = {}
                self._current_turn_tools = []
                self._last_agent_loop_truncated = False
                self._last_agent_loop_round_limit_hit = False
                self.journal = types.SimpleNamespace(log_runtime_event=lambda **_: None)

            def _agent_loop(self, *_args, **_kwargs):
                self._last_agent_loop_truncated = True
                return _complete_validation_code("Truncated raw code must not be saved")

            def _execute_tool(self, name, tool_input, _elapsed):
                from blender_addon.tools.handlers import handle_read_script_draft, handle_write_script_draft
                if name == "write_script_draft":
                    raw = handle_write_script_draft(tool_input)
                elif name == "read_script_draft":
                    raw = handle_read_script_draft(tool_input)
                else:
                    raw = {"status": "success", "result": {"memory": {"node_count": 1}}}
                payload = raw.get("result", {}) if isinstance(raw, dict) else {}
                self._current_turn_tools.append({
                    "name": name,
                    "input": tool_input,
                    "result": json.dumps(raw, ensure_ascii=False)[:300],
                    "status": str(raw.get("status", "")),
                    "result_payload": payload if isinstance(payload, dict) else {},
                })
                return json.dumps(raw, ensure_ascii=False)

        ctx = TurnContext(
            session=_FakeSession(),
            message="corrige esse draft",
            meta=ClassifierMeta(turn_class=TurnClass.DRAFT_WORKSPACE),
            blend_path="",
            _runtime=_FakeRuntime(),
            knowledge_dir=Path("/nonexistent/knowledge/domain"),
        )

        result = handle_draft_workspace(ctx)

        self.assertIn("foi truncada", result.response_text)
        self.assertIsNone(sys.modules["bpy"].data.texts.get("GN_Agent_Draft"))
        write_calls = [call for call in ctx._runtime._current_turn_tools if call.get("name") == "write_script_draft"]
        self.assertEqual([], write_calls)
        self.assertEqual("write_confirmed_draft_revision", ctx.session.execution_state.pending_draft_action)

    def test_draft_chat_response_sanitizes_code_when_write_is_not_valid(self):
        from blender_addon.handler._drafting_support import _sanitize_draft_chat_response

        raw = "import bpy\nprint('tentativa curta')"
        fenced = "```python\nimport bpy\nprint('tentativa curta')\n```"

        self.assertNotIn("import bpy", _sanitize_draft_chat_response(raw))
        self.assertNotIn("print(", _sanitize_draft_chat_response(raw))
        self.assertNotIn("import bpy", _sanitize_draft_chat_response(fenced))

    def test_draft_tool_policy_allows_single_workspace_resolution_when_tree_is_missing(self):
        from blender_addon.core.runtime import AgentRuntime

        class _FakeRuntime:
            def __init__(self):
                self._draft_tool_policy = {
                    "turn_class": "draft_workspace",
                    "write_allowed": True,
                    "tree_name": "",
                    "workspace_resolution_budget": 1,
                    "workspace_resolution_used": 0,
                    "recovery_structural_budget": 0,
                    "recovery_structural_used": 0,
                    "focal_budget": 4,
                    "focal_used": 0,
                    "economy_retry": False,
                    "fresh_structural_memory": False,
                }
                self.journal = types.SimpleNamespace(log_runtime_event=lambda **_: None)

            def _block_draft_tool(self, tool_name, reason, _policy):
                return f"BLOCKED: {tool_name} ({reason})"

        runtime = _FakeRuntime()

        first = AgentRuntime._enforce_draft_tool_policy(runtime, "resolve_gn_workspace")
        second = AgentRuntime._enforce_draft_tool_policy(runtime, "resolve_gn_workspace")

        self.assertEqual("", first)
        self.assertEqual("BLOCKED: resolve_gn_workspace (broad_or_rebuild_read_disallowed)", second)
        self.assertEqual(1, runtime._draft_tool_policy["workspace_resolution_used"])

    def test_diagnose_only_allows_get_tree_parameters_without_economy_retry(self):
        from blender_addon.core.runtime import AgentRuntime

        class _FakeRuntime:
            def __init__(self):
                self._draft_tool_policy = {
                    "turn_class": "draft_workspace",
                    "goal_mode": "diagnose_only",
                    "write_allowed": False,
                    "tree_name": "Biomodelo_GN",
                    "fresh_structural_memory": True,
                    "economy_retry": False,
                    "focal_used": 0,
                    "focal_budget": 0,
                }
                self.journal = types.SimpleNamespace(log_runtime_event=lambda **_: None)

            def _block_draft_tool(self, tool_name, reason, _policy):
                return f"BLOCKED: {tool_name} ({reason})"

        runtime = _FakeRuntime()

        allowed = AgentRuntime._enforce_draft_tool_policy(runtime, "get_tree_parameters")
        still_blocked = AgentRuntime._enforce_draft_tool_policy(runtime, "resolve_gn_workspace")

        self.assertEqual("", allowed)
        self.assertEqual("BLOCKED: resolve_gn_workspace (broad_or_rebuild_read_disallowed)", still_blocked)

    def test_clear_history_resolves_session_by_blend_path_and_clears_persisted_history(self):
        from blender_addon.core.runtime import AgentRuntime

        session = types.SimpleNamespace(
            identity=types.SimpleNamespace(session_id="sess-clear"),
            history=types.SimpleNamespace(messages=[object(), object()]),
        )

        class _Runtime:
            def __init__(self):
                self.cleared: list[str] = []
                self.saved: list[Any] = []
                self.loaded_paths: list[str] = []

            def v1_session_for(self, blend_path):
                self.loaded_paths.append(blend_path)
                return session

            def clear_chat_history(self, session_id):
                self.cleared.append(session_id)

            def save_v1_session(self, saved_session):
                self.saved.append(saved_session)

        class _FakeRuntime:
            def __init__(self):
                self._messages = [{"role": "user", "content": "old"}]
                self._active_v1_session = None
                self.runtime = _Runtime()

        runtime = _FakeRuntime()

        AgentRuntime.clear_history(runtime, blend_path="C:/tmp/test.blend")

        self.assertEqual([], runtime._messages)
        self.assertEqual(["C:/tmp/test.blend"], runtime.runtime.loaded_paths)
        self.assertEqual(["sess-clear"], runtime.runtime.cleared)
        self.assertEqual([], session.history.messages)
        self.assertEqual([session], runtime.runtime.saved)

    def test_clear_runtime_context_does_not_clear_persisted_history(self):
        from blender_addon.core.runtime import AgentRuntime

        class _Runtime:
            def __init__(self):
                self.cleared: list[str] = []
                self.saved: list[Any] = []

            def clear_chat_history(self, session_id):
                self.cleared.append(session_id)

            def save_v1_session(self, session):
                self.saved.append(session)

        class _FakeRuntime:
            def __init__(self):
                self._messages = [{"role": "assistant", "content": "old"}]
                self._active_v1_session = types.SimpleNamespace(
                    identity=types.SimpleNamespace(session_id="sess-keep"),
                    history=types.SimpleNamespace(messages=[object()]),
                )
                self.runtime = _Runtime()

        runtime = _FakeRuntime()

        AgentRuntime.clear_runtime_context(runtime)

        self.assertEqual([], runtime._messages)
        self.assertIsNone(runtime._active_v1_session)
        self.assertEqual([], runtime.runtime.cleared)
        self.assertEqual([], runtime.runtime.saved)

    def test_draft_write_contract_requires_source_read_before_write(self):
        from blender_addon.core.runtime import AgentRuntime

        class _FakeRuntime:
            def __init__(self):
                self._draft_tool_policy = {
                    "turn_class": "draft_workspace",
                    "write_allowed": True,
                    "tree_name": "Biomodelo_GN",
                    "fresh_structural_memory": True,
                    "economy_retry": False,
                    "require_read_before_write": True,
                    "allow_write_when_source_missing": False,
                    "require_target_tree_for_write": False,
                    "require_context_evidence_for_write": False,
                    "focal_used": 0,
                    "focal_budget": 3,
                }
                self._draft_attempt_state = None
                self.journal = types.SimpleNamespace(log_runtime_event=lambda **_: None)

            def _block_draft_tool(self, tool_name, reason, policy):
                return AgentRuntime._block_draft_tool(self, tool_name, reason, policy)

        runtime = _FakeRuntime()

        blocked = AgentRuntime._enforce_draft_tool_policy(runtime, "write_script_draft")
        self.assertIn("draft_source_not_read", blocked)

        AgentRuntime._record_draft_attempt_tool_result(
            runtime,
            tool_name="read_script_draft",
            tool_input={"block_name": "GN_Agent_Draft"},
            runtime_raw={"status": "success", "result": {"block_name": "GN_Agent_Draft", "char_count": 1200}},
        )

        allowed = AgentRuntime._enforce_draft_tool_policy(runtime, "write_script_draft")
        self.assertEqual("", allowed)

    def test_draft_write_contract_can_require_target_resolution_for_new_draft(self):
        from blender_addon.core.runtime import AgentRuntime

        class _FakeRuntime:
            def __init__(self):
                self._draft_tool_policy = {
                    "turn_class": "draft_workspace",
                    "write_allowed": True,
                    "tree_name": "",
                    "fresh_structural_memory": False,
                    "economy_retry": False,
                    "require_read_before_write": True,
                    "allow_write_when_source_missing": True,
                    "require_target_tree_for_write": True,
                    "require_context_evidence_for_write": False,
                    "focal_used": 0,
                    "focal_budget": 3,
                }
                self._draft_attempt_state = None
                self.journal = types.SimpleNamespace(log_runtime_event=lambda **_: None)

            def _block_draft_tool(self, tool_name, reason, policy):
                return AgentRuntime._block_draft_tool(self, tool_name, reason, policy)

        runtime = _FakeRuntime()

        AgentRuntime._record_draft_attempt_tool_result(
            runtime,
            tool_name="read_script_draft",
            tool_input={"block_name": "GN_Agent_Draft"},
            runtime_raw={"status": "error", "error": "Text block 'GN_Agent_Draft' not found.", "result": {}},
        )

        blocked = AgentRuntime._enforce_draft_tool_policy(runtime, "write_script_draft")
        self.assertIn("draft_target_not_resolved", blocked)

        AgentRuntime._record_draft_attempt_tool_result(
            runtime,
            tool_name="resolve_gn_workspace",
            tool_input={},
            runtime_raw={"status": "success", "result": {"selected_tree": "Biomodelo_GN"}},
        )

        allowed = AgentRuntime._enforce_draft_tool_policy(runtime, "write_script_draft")
        self.assertEqual("", allowed)

    def test_draft_write_contract_blocks_when_prepared_context_reports_hard_blocker(self):
        from blender_addon.core.runtime import AgentRuntime

        class _FakeRuntime:
            def __init__(self):
                self._draft_tool_policy = {
                    "turn_class": "draft_workspace",
                    "write_allowed": True,
                    "tree_name": "Biomodelo_GN",
                    "existing_draft_loaded": True,
                    "require_read_before_write": True,
                    "require_prepared_context_for_write": True,
                    "block_when_prepared_context_has_blockers": True,
                }
                self._draft_attempt_state = None
                self.journal = types.SimpleNamespace(log_runtime_event=lambda **_: None)

            def _block_draft_tool(self, tool_name, reason, policy):
                return AgentRuntime._block_draft_tool(self, tool_name, reason, policy)

        runtime = _FakeRuntime()

        AgentRuntime._record_draft_attempt_tool_result(
            runtime,
            tool_name="prepare_draft_context",
            tool_input={"tree_name": "Biomodelo_GN"},
            runtime_raw={
                "status": "success",
                "result": {
                    "tree_name": "Biomodelo_GN",
                    "context_ready": False,
                    "write_requirements": {
                        "can_write_safely": False,
                        "structural_memory_available": True,
                        "blockers": ["tree_parameters_unavailable"],
                    },
                },
            },
        )

        blocked = AgentRuntime._enforce_draft_tool_policy(runtime, "write_script_draft")

        self.assertIn("prepared draft-context gate", blocked)
        self.assertIn("tree_parameters_unavailable", blocked)

    def test_execute_tool_records_blocked_write_attempt_in_turn_history(self):
        from blender_addon.core.runtime import AgentRuntime

        class _FakeRuntime:
            def __init__(self):
                self._current_turn_tools = []
                self._draft_tool_policy = {"turn_class": "draft_workspace"}
                self._draft_attempt_state = None
                self.journal = types.SimpleNamespace(log_runtime_event=lambda **_: None)

            def _enforce_draft_tool_policy(self, _tool_name):
                return "BLOCKED: write_script_draft failed the prepared draft-context gate (tree_parameters_unavailable)."

            def _record_draft_attempt_tool_result(self, *, tool_name, tool_input, runtime_raw):
                return AgentRuntime._record_draft_attempt_tool_result(
                    self,
                    tool_name=tool_name,
                    tool_input=tool_input,
                    runtime_raw=runtime_raw,
                )

        runtime = _FakeRuntime()

        result = AgentRuntime._execute_tool(
            runtime,
            "write_script_draft",
            {"block_name": "GN_Agent_Draft", "code": _complete_validation_code("blocked"), "description": "blocked"},
            0,
        )

        self.assertIn("prepared draft-context gate", result)
        self.assertEqual(1, len(runtime._current_turn_tools))
        self.assertEqual("write_script_draft", runtime._current_turn_tools[0]["name"])
        self.assertEqual("blocked", runtime._current_turn_tools[0]["status"])

    def test_normalize_write_script_draft_enables_intentional_rebuild_mode(self):
        from blender_addon.core.runtime import AgentRuntime

        class _FakeRuntime:
            def __init__(self, edit_mode: str):
                self._draft_tool_policy = {
                    "edit_mode": edit_mode,
                    "goal_mode": "focal_correction",
                    "goal_guidance": {
                        "summary": "Apply the smallest safe correction to the current living draft.",
                        "suggested_output": "single_targeted_revision",
                    },
                    "expected_parameter_refs": ["Palm Width"],
                    "expected_focus_regions": ["Metacarpos"],
                }

        rebuild_runtime = _FakeRuntime("intentional_rebuild")
        retarget_runtime = _FakeRuntime("intentional_retarget")
        preserve_runtime = _FakeRuntime("preserve_and_refine")

        rebuild_input = AgentRuntime._normalize_tool_input(
            rebuild_runtime,
            "write_script_draft",
            {"code": _complete_validation_code("rebuild"), "description": "rebuild"},
        )
        retarget_input = AgentRuntime._normalize_tool_input(
            retarget_runtime,
            "write_script_draft",
            {"code": _complete_validation_code("retarget"), "description": "retarget"},
        )
        preserve_input = AgentRuntime._normalize_tool_input(
            preserve_runtime,
            "write_script_draft",
            {"code": _complete_validation_code("preserve"), "description": "preserve"},
        )

        self.assertTrue(rebuild_input.get("allow_capability_regression", False))
        self.assertTrue(retarget_input.get("allow_capability_regression", False))
        self.assertTrue(retarget_input.get("allow_tree_change", False))
        self.assertFalse(preserve_input.get("allow_capability_regression", False))
        self.assertEqual("focal_correction", preserve_input.get("goal_mode"))
        self.assertEqual("single_targeted_revision", preserve_input.get("goal_guidance", {}).get("suggested_output"))
        self.assertEqual(["Palm Width"], preserve_input.get("expected_parameter_refs"))
        self.assertEqual(["Metacarpos"], preserve_input.get("expected_focus_regions"))

    def test_prepare_draft_context_aggregates_deterministic_write_context(self):
        from blender_addon.tools.server_dispatch import RuntimeDispatcher

        dispatcher = RuntimeDispatcher()
        dispatcher._resolve_gn_workspace = lambda tool_input, session_state=None: {
            "status": "success",
            "result": {
                "selected_tree": "Biomodelo_GN",
                "selected_binding": {"object_name": "HandMesh", "modifier_name": "OrthosisGN"},
                "selection_reason": "session_memory_target_tree_valid",
                "confidence": {"level": "high", "score": 0.88},
                "warnings": [],
            },
        }
        dispatcher._load_tree_structural_memory = lambda tool_input, session_state=None: (
            {
                "tree_name": "Biomodelo_GN",
                "node_count": 64,
                "frame_count": 5,
                "group_count": 3,
                "phase_dominant": "phase_2",
                "organization_assessment": {"level": "good"},
                "key_outputs": ["Group Output"],
                "key_joins": ["Join Geometry"],
                "major_regions": [{"name": "Metacarpos", "type": "frame"}],
                "parameters": {"measures": [{"name": "Palm Width"}]},
                "marker": {
                    "tree_hash": "treehash-64",
                    "node_names": ["Group Input", "Cube_Metacarpo1", "Join Geometry"],
                    "links": ["Group Input.Palm Width -> Cube_Metacarpo1.Size"],
                },
                "freshness": {"snapshot_truncated": False},
                "structural_hash": "abc123",
                "built_at": "2026-04-23T12:00:00+00:00",
            },
            {"source": "tree_structural_memory", "reused": True},
            [],
        )
        dispatcher._get_tree_parameters = lambda tree_name: {
            "status": "success",
            "result": {
                "tree": tree_name,
                "object": "HandMesh",
                "modifier": "OrthosisGN",
                "parameters": [{"name": "Palm Width", "identifier": "palm_width"}],
            },
        }
        dispatcher._classify_tree_phases = lambda tool_input, session_state=None: {
            "status": "success",
            "result": {
                "tree_phase": "phase_2",
                "confidence": {"level": "medium", "score": 0.66},
                "unresolved_regions": [{"name": "Curva Palma"}],
                "transition_regions": [],
            },
        }
        dispatcher._map_clinical_parameter_roles = lambda tool_input, session_state=None: {
            "status": "success",
            "result": {
                "summary": {
                    "measurement_count": 1,
                    "positioning_count": 0,
                    "uncertain_count": 0,
                },
                "measurement_parameters": [{"name": "Palm Width"}],
                "positioning_parameters": [],
                "likely_affected_regions": [{"region": "Metacarpos"}],
            },
        }
        dispatcher._interpret_orthosis_tree_logic = lambda tool_input, session_state=None: {
            "status": "success",
            "result": {
                "functional_summary": "Tree appears centered on path/profile curve generation.",
                "workflow_stage_summary": {
                    "biomodel_region_count": 2,
                    "curve_region_count": 1,
                    "orthosis_region_count": 0,
                },
                "suggested_focus_regions": [{"region": "Curva Palma"}],
                "next_structural_targets": ["Refinar a curva principal da palma."],
                "organization_observations": [{"type": "organization_level", "level": "good"}],
            },
        }

        result = dispatcher.execute(
            "prepare_draft_context",
            {"user_message": "corrige o draft atual da ortese", "has_existing_draft": True},
            session_state={"session_memory": {"target_tree": "Biomodelo_GN"}},
        )

        self.assertEqual("success", result["status"])
        payload = result["result"]
        self.assertEqual("Biomodelo_GN", payload["tree_name"])
        self.assertEqual("functional_expansion", payload["goal_mode"])
        self.assertTrue(payload["context_ready"])
        self.assertTrue(payload["write_requirements"]["can_write_safely"])
        self.assertTrue(payload["coverage"]["coverage_confirmed_this_turn"])
        self.assertFalse(payload["coverage"]["coverage_refresh_needed"])
        self.assertTrue(payload["write_requirements"]["coverage_confirmed_this_turn"])
        self.assertEqual(
            "extend_existing_draft_with_new_capability",
            payload["write_requirements"]["recommended_next_step"],
        )
        self.assertEqual(64, payload["structural_memory"]["node_count"])
        self.assertEqual(
            ["Group Input", "Cube_Metacarpo1", "Join Geometry"],
            payload["structural_memory"]["marker"]["node_names"],
        )
        self.assertEqual(
            ["Group Input.Palm Width -> Cube_Metacarpo1.Size"],
            payload["structural_memory"]["marker"]["links"],
        )
        self.assertEqual("treehash-64", payload["structural_memory"]["marker"]["tree_hash"])
        self.assertIn("Prepared deterministic draft context", payload["prompt_context"])
        self.assertIn("goal_mode: functional_expansion", payload["prompt_context"])
        self.assertIn("write_gate", payload["prompt_context"])
        self.assertIn("coverage_refresh", payload["prompt_context"])

    def test_prepare_draft_context_reports_blockers_when_target_is_unresolved(self):
        from blender_addon.tools.server_dispatch import RuntimeDispatcher

        dispatcher = RuntimeDispatcher()
        dispatcher._resolve_gn_workspace = lambda tool_input, session_state=None: {
            "status": "success",
            "result": {
                "selected_tree": "",
                "selected_binding": {},
                "selection_reason": "no_geometry_nodes_tree_found",
                "confidence": {"level": "low", "score": 0.0},
                "warnings": ["No Geometry Nodes tree or bound modifier was found in the scene."],
            },
        }

        result = dispatcher.execute("prepare_draft_context", {"user_message": "cria um draft novo"})

        self.assertEqual("success", result["status"])
        payload = result["result"]
        self.assertFalse(payload["context_ready"])
        self.assertIn("target_tree_unresolved", payload["write_requirements"]["blockers"])
        self.assertFalse(payload["write_requirements"]["can_write_safely"])
        self.assertIn("target_tree", payload["prompt_context"])

    def test_prepare_draft_context_specializes_diagnosis_mode(self):
        from blender_addon.tools.server_dispatch import RuntimeDispatcher

        dispatcher = RuntimeDispatcher()
        dispatcher._resolve_gn_workspace = lambda tool_input, session_state=None: {
            "status": "success",
            "result": {
                "selected_tree": "Biomodelo_GN",
                "selected_binding": {"object_name": "HandMesh", "modifier_name": "OrthosisGN"},
                "selection_reason": "session_memory_target_tree_valid",
                "confidence": {"level": "high", "score": 0.88},
                "warnings": [],
            },
        }
        dispatcher._load_tree_structural_memory = lambda tool_input, session_state=None: (
            {"tree_name": "Biomodelo_GN", "node_count": 64, "frame_count": 5, "group_count": 3, "phase_dominant": "phase_2"},
            {"source": "tree_structural_memory", "reused": True},
            [],
        )
        dispatcher._get_tree_parameters = lambda tree_name: {
            "status": "success",
            "result": {"tree": tree_name, "object": "HandMesh", "modifier": "OrthosisGN", "parameters": [{"name": "Palm Width"}]},
        }
        dispatcher._classify_tree_phases = lambda tool_input, session_state=None: {
            "status": "success",
            "result": {"tree_phase": "phase_2", "confidence": {"level": "medium", "score": 0.66}},
        }
        dispatcher._map_clinical_parameter_roles = lambda tool_input, session_state=None: {
            "status": "success",
            "result": {"summary": {"measurement_count": 1, "positioning_count": 0, "uncertain_count": 0}, "measurement_parameters": [{"name": "Palm Width"}]},
        }
        dispatcher._interpret_orthosis_tree_logic = lambda tool_input, session_state=None: {
            "status": "success",
            "result": {"suggested_focus_regions": [{"region": "Metacarpos"}], "next_structural_targets": ["Revisar o frame principal."]},
        }

        result = dispatcher.execute(
            "prepare_draft_context",
            {"user_message": "faz um diagnostico primeiro", "goal_mode": "diagnose_only", "has_existing_draft": True},
            session_state={"session_memory": {"target_tree": "Biomodelo_GN"}},
        )

        self.assertEqual("success", result["status"])
        payload = result["result"]
        self.assertEqual("diagnose_only", payload["goal_mode"])
        self.assertEqual("diagnose_current_draft_before_writing", payload["write_requirements"]["recommended_next_step"])
        self.assertFalse(payload["write_requirements"]["mode_allows_write"])
        self.assertFalse(payload["write_requirements"]["can_write_safely"])
        self.assertTrue(payload["coverage"]["coverage_confirmed_this_turn"])
        self.assertIn("likely_failure", payload["goal_guidance"]["suggested_output"])
        self.assertIn("goal_mode: diagnose_only", payload["prompt_context"])

    def test_prepare_draft_context_specializes_focal_correction_mode(self):
        from blender_addon.tools.server_dispatch import RuntimeDispatcher

        dispatcher = RuntimeDispatcher()
        dispatcher._resolve_gn_workspace = lambda tool_input, session_state=None: {
            "status": "success",
            "result": {
                "selected_tree": "Biomodelo_GN",
                "selected_binding": {"object_name": "HandMesh", "modifier_name": "OrthosisGN"},
                "selection_reason": "session_memory_target_tree_valid",
                "confidence": {"level": "high", "score": 0.88},
                "warnings": [],
            },
        }
        dispatcher._load_tree_structural_memory = lambda tool_input, session_state=None: (
            {"tree_name": "Biomodelo_GN", "node_count": 64, "frame_count": 5, "group_count": 3, "phase_dominant": "phase_2"},
            {"source": "tree_structural_memory", "reused": True},
            [],
        )
        dispatcher._get_tree_parameters = lambda tree_name: {
            "status": "success",
            "result": {"tree": tree_name, "object": "HandMesh", "modifier": "OrthosisGN", "parameters": [{"name": "Palm Width"}]},
        }
        dispatcher._classify_tree_phases = lambda tool_input, session_state=None: {
            "status": "success",
            "result": {"tree_phase": "phase_2", "confidence": {"level": "medium", "score": 0.66}},
        }
        dispatcher._map_clinical_parameter_roles = lambda tool_input, session_state=None: {
            "status": "success",
            "result": {"summary": {"measurement_count": 1, "positioning_count": 0, "uncertain_count": 0}, "measurement_parameters": [{"name": "Palm Width"}]},
        }
        dispatcher._interpret_orthosis_tree_logic = lambda tool_input, session_state=None: {
            "status": "success",
            "result": {"suggested_focus_regions": [{"region": "Metacarpos"}], "next_structural_targets": ["Revisar o frame principal."]},
        }

        result = dispatcher.execute(
            "prepare_draft_context",
            {"user_message": "corrige a parte da palma sem quebrar o resto", "goal_mode": "focal_correction", "has_existing_draft": True},
            session_state={"session_memory": {"target_tree": "Biomodelo_GN"}},
        )

        self.assertEqual("success", result["status"])
        payload = result["result"]
        self.assertEqual("focal_correction", payload["goal_mode"])
        self.assertEqual(
            "apply_smallest_safe_correction_to_existing_draft",
            payload["write_requirements"]["recommended_next_step"],
        )
        self.assertTrue(payload["write_requirements"]["mode_allows_write"])
        self.assertTrue(payload["write_requirements"]["can_write_safely"])
        self.assertTrue(payload["coverage"]["coverage_confirmed_this_turn"])
        self.assertIn("smallest safe correction", payload["goal_guidance"]["summary"])
        self.assertIn("goal_mode: focal_correction", payload["prompt_context"])

    def test_prepare_draft_context_reports_coverage_refresh_when_only_persisted_metadata_exists(self):
        from blender_addon.tools.server_dispatch import RuntimeDispatcher

        dispatcher = RuntimeDispatcher()
        dispatcher._resolve_gn_workspace = lambda tool_input, session_state=None: {
            "status": "success",
            "result": {
                "selected_tree": "Biomodelo_GN",
                "selected_binding": {"object_name": "HandMesh", "modifier_name": "OrthosisGN"},
                "selection_reason": "session_memory_target_tree_valid",
                "confidence": {"level": "high", "score": 0.88},
                "warnings": [],
            },
        }
        dispatcher._load_tree_structural_memory = lambda tool_input, session_state=None: ({}, {"source": "", "reused": False}, [])
        dispatcher._get_tree_parameters = lambda tree_name: {
            "status": "error",
            "error": f"No object found using tree '{tree_name}'.",
        }
        dispatcher._classify_tree_phases = lambda tool_input, session_state=None: {
            "status": "error",
            "error": "Phase classification unavailable.",
        }
        dispatcher._map_clinical_parameter_roles = lambda tool_input, session_state=None: {
            "status": "success",
            "result": {"summary": {"measurement_count": 0, "positioning_count": 0, "uncertain_count": 0}},
        }
        dispatcher._interpret_orthosis_tree_logic = lambda tool_input, session_state=None: {
            "status": "success",
            "result": {"suggested_focus_regions": [], "next_structural_targets": []},
        }

        result = dispatcher.execute(
            "prepare_draft_context",
            {
                "user_message": "corrige esse draft",
                "goal_mode": "focal_correction",
                "has_existing_draft": True,
                "stored_live_node_refs": ["ORTHOSIS_CONTEXT"],
                "stored_expected_parameter_refs": ["Palm Width"],
                "stored_expected_focus_regions": ["Metacarpos"],
            },
            session_state={"session_memory": {"target_tree": "Biomodelo_GN"}},
        )

        self.assertEqual("success", result["status"])
        payload = result["result"]
        self.assertFalse(payload["coverage"]["coverage_confirmed_this_turn"])
        self.assertTrue(payload["coverage"]["coverage_refresh_needed"])
        self.assertEqual(["Palm Width"], payload["coverage"]["persisted_expected_parameter_refs"])
        self.assertEqual(["Metacarpos"], payload["coverage"]["persisted_expected_focus_regions"])
        self.assertTrue(payload["write_requirements"]["coverage_refresh_needed"])
        self.assertIn("coverage_refresh", payload["prompt_context"])

    def test_draft_workspace_tool_policy_falls_back_to_persisted_semantics(self):
        from blender_addon.handler._drafting_support import _draft_workspace_tool_policy

        policy = _draft_workspace_tool_policy(
            tree_name_hint="Biomodelo_GN",
            structural_memory={},
            relevant_nodes=[],
            economy_retry=False,
            has_existing_draft_content=True,
            prepared_context={},
            edit_mode="preserve_and_refine",
            goal_mode="focal_correction",
            stored_goal_guidance={},
            stored_expected_parameter_refs=["Palm Width"],
            stored_expected_focus_regions=["Metacarpos"],
        )

        self.assertEqual(["Palm Width"], policy["expected_parameter_refs"])
        self.assertEqual(["Metacarpos"], policy["expected_focus_regions"])

    def test_draft_workspace_tool_policy_allows_minimum_focal_reads_in_economy_retry(self):
        from blender_addon.handler._drafting_support import _draft_workspace_tool_policy

        policy = _draft_workspace_tool_policy(
            tree_name_hint="Biomodelo_GN",
            structural_memory={"tree_name": "Biomodelo_GN", "node_count": 64},
            relevant_nodes=[],
            economy_retry=True,
            has_existing_draft_content=True,
            prepared_context={},
            edit_mode="preserve_and_refine",
            goal_mode="focal_correction",
            stored_goal_guidance={},
            stored_expected_parameter_refs=["Palm Width"],
            stored_expected_focus_regions=["Metacarpos"],
            stored_live_node_refs=["ORTHOSIS_CONTEXT"],
        )

        self.assertEqual(3, policy["focal_budget"])
        self.assertEqual(3, policy["economy_retry_focal_budget"])
        self.assertTrue(policy["coverage_has_semantic_memory"])
        self.assertFalse(policy["coverage_refresh_needed"])

    def test_draft_workspace_tool_policy_keeps_minimum_focal_reads_for_unconfirmed_persisted_coverage(self):
        from blender_addon.handler._drafting_support import _draft_workspace_tool_policy

        policy = _draft_workspace_tool_policy(
            tree_name_hint="Biomodelo_GN",
            structural_memory={},
            relevant_nodes=[],
            economy_retry=True,
            has_existing_draft_content=True,
            prepared_context={},
            edit_mode="preserve_and_refine",
            goal_mode="focal_correction",
            stored_goal_guidance={},
            stored_expected_parameter_refs=["Palm Width"],
            stored_expected_focus_regions=["Metacarpos"],
            stored_live_node_refs=["ORTHOSIS_CONTEXT"],
        )

        self.assertEqual(3, policy["focal_budget"])
        self.assertEqual(3, policy["economy_retry_focal_budget"])
        self.assertTrue(policy["coverage_has_semantic_memory"])
        self.assertFalse(policy["coverage_confirmed_this_turn"])
        self.assertTrue(policy["coverage_refresh_needed"])

    def test_economy_retry_allows_three_focal_reads_when_coverage_is_weak(self):
        from blender_addon.core.runtime import AgentRuntime

        class _FakeRuntime:
            def __init__(self):
                self._draft_tool_policy = {
                    "turn_class": "draft_workspace",
                    "write_allowed": True,
                    "tree_name": "Biomodelo_GN",
                    "fresh_structural_memory": False,
                    "economy_retry": True,
                    "coverage_has_semantic_memory": False,
                    "focal_budget": 3,
                    "focal_used": 0,
                }
                self.journal = types.SimpleNamespace(log_runtime_event=lambda **_: None)

            def _block_draft_tool(self, tool_name, reason, policy):
                return AgentRuntime._block_draft_tool(self, tool_name, reason, policy)

        runtime = _FakeRuntime()

        first = AgentRuntime._enforce_draft_tool_policy(runtime, "get_active_frame_context")
        second = AgentRuntime._enforce_draft_tool_policy(runtime, "get_active_frame_context")
        third = AgentRuntime._enforce_draft_tool_policy(runtime, "get_active_frame_context")
        fourth = AgentRuntime._enforce_draft_tool_policy(runtime, "get_active_frame_context")

        self.assertEqual("", first)
        self.assertEqual("", second)
        self.assertEqual("", third)
        self.assertIn("economy_retry_focal_budget_exhausted", fourth)
        self.assertEqual(3, runtime._draft_tool_policy["focal_used"])


if __name__ == "__main__":
    unittest.main()
