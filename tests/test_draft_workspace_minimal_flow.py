from __future__ import annotations

import json
import sys
import types
import unittest
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))


def _install_fake_bpy() -> None:
    if "bpy" in sys.modules:
        return
    bpy = types.ModuleType("bpy")
    bpy.app = types.SimpleNamespace(
        handlers=types.SimpleNamespace(persistent=lambda fn: fn, load_post=[], save_post=[]),
        timers=types.SimpleNamespace(register=lambda fn: fn()),
    )
    bpy.data = types.SimpleNamespace(filepath="", texts={}, node_groups={})
    sys.modules["bpy"] = bpy


_install_fake_bpy()

from blender_addon.handler import TurnContext
from blender_addon.handler._drafting_support import handle_draft_workspace
from blender_addon.runtime.router import ClassifierMeta, TurnClass, TurnRouter
from blender_addon.session.schema import Session


class _FakeJournal:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def log_runtime_event(self, *, event_type: str, payload: dict[str, Any] | None = None, status: str = "success") -> None:
        self.events.append({
            "event_type": event_type,
            "payload": dict(payload or {}),
            "status": status,
        })


class _FakeDraftRuntime:
    def __init__(self) -> None:
        self._messages: list[dict[str, Any]] = []
        self._session_memory = {
            "last_goal": "Criar um draft para a Biomodelo.",
            "last_hypothesis": "Com contexto suficiente, o agente deve escrever no GN_Agent_Draft.",
            "target_tree": "Biomodelo_GN",
            "relevant_nodes": ["Metacarpo_1", "Metacarpo_2"],
        }
        self._session_state = {"tree_structural_memory": {}}
        self._draft_tool_policy: dict[str, Any] = {}
        self._draft_attempt_state = None
        self._current_turn_tools: list[dict[str, Any]] = []
        self._last_agent_loop_truncated = False
        self._last_agent_loop_round_limit_hit = False
        self.last_excluded_tools: frozenset[str] = frozenset()
        self.last_max_rounds: int | None = None
        self.journal = _FakeJournal()

    def _agent_loop(
        self,
        _system: str,
        _messages: list[dict[str, Any]],
        *,
        excluded_tools: frozenset[str] | None = None,
        max_rounds: int | None = None,
        **_kwargs,
    ) -> str:
        self.last_excluded_tools = excluded_tools or frozenset()
        self.last_max_rounds = max_rounds
        return "Li o contexto necessario e parei sem salvar."

    def _execute_tool(self, name: str, tool_input: dict[str, Any], _elapsed_ms: int) -> str:
        if name == "read_script_draft":
            raw = {
                "status": "error",
                "error": "Text block 'GN_Agent_Draft' not found.",
                "result": {},
            }
        elif name == "prepare_draft_context":
            raw = {
                "status": "success",
                "result": {
                    "tree_name": "Biomodelo_GN",
                    "goal_mode": "functional_expansion",
                    "context_ready": True,
                    "prompt_context": "Prepared deterministic draft context for Biomodelo_GN.",
                    "structural_memory": {"tree_name": "Biomodelo_GN", "node_count": 12},
                    "coverage": {
                        "coverage_confirmed_this_turn": True,
                        "coverage_refresh_needed": False,
                    },
                    "write_requirements": {
                        "mode_allows_write": True,
                        "can_write_safely": True,
                        "recommended_next_step": "extend_existing_draft_with_new_capability",
                        "coverage_confirmed_this_turn": True,
                        "coverage_refresh_needed": False,
                        "structural_memory_available": True,
                        "blockers": [],
                    },
                    "goal_guidance": {
                        "summary": "Adicionar a parametrizacao pedida.",
                        "suggested_output": "complete_draft_revision",
                    },
                },
            }
        else:
            raw = {"status": "success", "result": {}}

        payload = raw.get("result", {}) if isinstance(raw, dict) else {}
        self._current_turn_tools.append({
            "name": name,
            "input": dict(tool_input),
            "result": json.dumps(raw, ensure_ascii=False),
            "status": str(raw.get("status", "")),
            "result_payload": dict(payload) if isinstance(payload, dict) else {},
        })
        return json.dumps(raw, ensure_ascii=False)


class _FakeDiagnoseRuntime(_FakeDraftRuntime):
    def _agent_loop(
        self,
        _system: str,
        _messages: list[dict[str, Any]],
        *,
        excluded_tools: frozenset[str] | None = None,
        max_rounds: int | None = None,
        **_kwargs,
    ) -> str:
        self.last_excluded_tools = excluded_tools or frozenset()
        self.last_max_rounds = max_rounds
        return "Nao salvei o draft porque este turno estava em modo de diagnostico; primeiro eu precisava analisar antes de propor uma revisao."

    def _execute_tool(self, name: str, tool_input: dict[str, Any], _elapsed_ms: int) -> str:
        if name == "read_script_draft":
            raw = {
                "status": "success",
                "result": {
                    "block_name": "GN_Agent_Draft",
                    "version": 44,
                    "char_count": 380,
                    "content": (
                        "import bpy\n"
                        "tree = bpy.data.node_groups.get('Biomodelo')\n"
                        "node = tree.nodes.get('TF_Metacarpo1.001')\n"
                        "node.inputs['Translation'].default_value[0] = -60\n"
                    ),
                },
            }
            payload = raw["result"]
            self._current_turn_tools.append({
                "name": name,
                "input": dict(tool_input),
                "result": json.dumps(raw, ensure_ascii=False),
                "status": "success",
                "result_payload": dict(payload),
            })
            return json.dumps(raw, ensure_ascii=False)
        return super()._execute_tool(name, tool_input, _elapsed_ms)


def _complete_leaked_chat_code() -> str:
    return (
        "import bpy\n"
        "\n"
        "def main():\n"
        "    tree = bpy.data.node_groups.get('Biomodelo_GN')\n"
        "    if tree is None:\n"
        "        raise RuntimeError('Biomodelo_GN not found')\n"
        "    socket_width = 30.99\n"
        "    half_width = socket_width / 2.0\n"
        "    mc1 = tree.nodes.get('TF_Metacarpo1.001')\n"
        "    mc2 = tree.nodes.get('TF_Metacarpo2.001')\n"
        "    if mc1 is None or mc2 is None:\n"
        "        raise RuntimeError('Metacarpal nodes not found')\n"
        "    mc1.inputs['Translation'].default_value = (-half_width, -67.8, 0.0)\n"
        "    mc2.inputs['Translation'].default_value = (half_width, -67.8, 0.0)\n"
        "    print('Palm width draft updated from central axis')\n"
        "\n"
        "main()\n"
    )


class _FakeLeakedCodeRuntime(_FakeDraftRuntime):
    def __init__(self) -> None:
        super().__init__()
        self._last_agent_loop_round_limit_hit = True
        self.written_code = ""

    def _agent_loop(
        self,
        _system: str,
        _messages: list[dict[str, Any]],
        *,
        excluded_tools: frozenset[str] | None = None,
        max_rounds: int | None = None,
        **_kwargs,
    ) -> str:
        self.last_excluded_tools = excluded_tools or frozenset()
        self.last_max_rounds = max_rounds
        return (
            "Tudo confirmado. Escrevo o draft agora:\n\n"
            + _complete_leaked_chat_code()
            + "\nAqui esta o draft completo para testar manualmente."
        )

    def _execute_tool(self, name: str, tool_input: dict[str, Any], _elapsed_ms: int) -> str:
        if name == "read_script_draft":
            raw = {
                "status": "success",
                "result": {
                    "block_name": "GN_Agent_Draft",
                    "version": 3 if self.written_code else 2,
                    "char_count": len(self.written_code),
                    "content": self.written_code,
                },
            }
        elif name == "prepare_draft_context":
            raw = {
                "status": "success",
                "result": {
                    "tree_name": "Biomodelo_GN",
                    "goal_mode": "functional_expansion",
                    "context_ready": True,
                    "prompt_context": "Prepared context.",
                    "structural_memory": {"tree_name": "Biomodelo_GN", "node_count": 12},
                    "coverage": {"coverage_confirmed_this_turn": True, "coverage_refresh_needed": False},
                    "write_requirements": {
                        "mode_allows_write": True,
                        "can_write_safely": True,
                        "recommended_next_step": "write_complete_draft_revision",
                        "coverage_confirmed_this_turn": True,
                        "coverage_refresh_needed": False,
                        "structural_memory_available": True,
                        "blockers": [],
                    },
                    "goal_guidance": {"summary": "Write.", "suggested_output": "complete_draft_revision"},
                },
            }
        elif name == "write_script_draft":
            self.written_code = str(tool_input.get("code") or "")
            raw = {
                "status": "success",
                "result": {
                    "block_name": str(tool_input.get("block_name") or "GN_Agent_Draft"),
                    "version": 3,
                    "char_count": len(self.written_code),
                    "description": str(tool_input.get("description") or ""),
                },
            }
        else:
            raw = {"status": "success", "result": {}}

        payload = raw.get("result", {}) if isinstance(raw, dict) else {}
        self._current_turn_tools.append({
            "name": name,
            "input": dict(tool_input),
            "result": json.dumps(raw, ensure_ascii=False),
            "status": str(raw.get("status", "")),
            "result_payload": dict(payload) if isinstance(payload, dict) else {},
        })
        return json.dumps(raw, ensure_ascii=False)


class TestDraftWorkspaceMinimalFlow(unittest.TestCase):

    def test_idle_explicit_draft_refinement_routes_to_workspace(self):
        session = Session.new()
        message = (
            "ajusta o draft da Biomodelo para parametrizar a angulacao dos metacarpos 1 e 2 "
            "em graus no objeto devbiomodelo.001"
        )

        turn_class, meta = TurnRouter().classify(session, message)

        self.assertEqual(TurnClass.DRAFT_WORKSPACE, turn_class)
        self.assertIn("draft_refinement_write_pattern", meta.signals)
        self.assertIn(meta.turn_intent, ("draft_write", "draft_refinement"))

    def test_draft_workspace_reports_explicit_reason_when_no_write_happens(self):
        runtime = _FakeDraftRuntime()
        session = Session.new()
        ctx = TurnContext(
            session=session,
            message=(
                "cria um draft para a arvore Biomodelo no objeto devbiomodelo.001 "
                "parametrizando a angulacao dos metacarpos 1 e 2 em graus e mantendo as falanges acompanhando"
            ),
            meta=ClassifierMeta(turn_class=TurnClass.DRAFT_WORKSPACE),
            blend_path="",
            _runtime=runtime,
            knowledge_dir=Path("/nonexistent/knowledge/domain"),
        )

        result = handle_draft_workspace(ctx)

        self.assertIn("Nao salvei o draft porque o agente ficou em leitura", result.response_text)
        self.assertIn("execute_code", runtime.last_excluded_tools)
        self.assertNotIn("write_script_draft", [call["name"] for call in runtime._current_turn_tools])

        outcome_events = [
            event for event in runtime.journal.events
            if event.get("event_type") == "draft_workspace_outcome"
        ]
        self.assertTrue(outcome_events)
        payload = outcome_events[-1]["payload"]
        self.assertEqual("draft_workspace", payload["handler"])
        self.assertEqual("draft_workspace", payload["turn_class"])
        self.assertTrue(payload["write_script_draft_exposed"])
        self.assertFalse(payload["write_script_draft_called"])
        self.assertEqual(["read_script_draft", "prepare_draft_context"], payload["tools_called"])
        self.assertEqual("analyzed_only", payload["outcome"])
        self.assertEqual("write_not_attempted", payload["reason"])

    def test_diagnose_only_replaces_no_save_fallback_with_useful_analysis(self):
        from blender_addon.handler.workspace import handle

        runtime = _FakeDiagnoseRuntime()
        session = Session.new()
        session.execution_state.last_execution_outcome = "executed_no_effect"
        session.execution_state.last_execution_notes = "Nao aconteceu nada."
        ctx = TurnContext(
            session=session,
            message="Faz um diagnostico geral primeiro, analise a arvore profundamente antes de escrever.",
            meta=ClassifierMeta(turn_class=TurnClass.DRAFT_WORKSPACE, goal_mode="diagnose_only"),
            blend_path="",
            _runtime=runtime,
            knowledge_dir=Path("/nonexistent/knowledge/domain"),
        )

        result = handle(ctx, "diagnose_only")

        self.assertIn("Draft read", result.response_text)
        self.assertIn("Likely failure", result.response_text)
        self.assertIn("Direcao de reparo", result.response_text)
        self.assertNotEqual(
            "Nao salvei o draft porque este turno estava em modo de diagnostico; primeiro eu precisava analisar antes de propor uma revisao.",
            result.response_text,
        )
        self.assertIn("write_script_draft", runtime.last_excluded_tools)
        self.assertNotIn("write_script_draft", [call["name"] for call in runtime._current_turn_tools])

    def test_leaked_complete_code_is_saved_before_round_limit_fallback(self):
        from blender_addon.handler.workspace import handle

        runtime = _FakeLeakedCodeRuntime()
        session = Session.new()
        ctx = TurnContext(
            session=session,
            message="Confirmo, pode escrever o draft da largura da palma.",
            meta=ClassifierMeta(turn_class=TurnClass.DRAFT_WORKSPACE, goal_mode="functional_expansion"),
            blend_path="",
            _runtime=runtime,
            knowledge_dir=Path("/nonexistent/knowledge/domain"),
        )

        result = handle(ctx, "functional_expansion")
        tool_names = [call["name"] for call in runtime._current_turn_tools]

        self.assertIn("write_script_draft", tool_names)
        self.assertIn("Text Editor", result.response_text)
        self.assertNotIn("limite de rounds", result.response_text)
        self.assertIn("TF_Metacarpo1.001", runtime.written_code)
        self.assertGreaterEqual(runtime.last_max_rounds or 0, 10)


if __name__ == "__main__":
    unittest.main()
