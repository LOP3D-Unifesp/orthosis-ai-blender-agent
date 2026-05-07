"""Smoke tests for the slim single-handler dispatch surface."""

from __future__ import annotations

import sys
import types
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _install_fake_bpy():
    bpy = types.ModuleType("bpy")
    bpy.app = types.SimpleNamespace(
        handlers=types.SimpleNamespace(persistent=lambda fn: fn, load_post=[], save_post=[]),
        timers=types.SimpleNamespace(register=lambda fn: fn()),
    )
    bpy.data = types.SimpleNamespace(filepath="")
    sys.modules["bpy"] = bpy


_install_fake_bpy()

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))


@dataclass
class _FakeExecutionState:
    phase: str = "idle"
    current_draft: Any = None
    pending_user_decision: Any = None
    session_state: str = "IDLE"


@dataclass
class _FakeHistory:
    messages: list = field(default_factory=list)


@dataclass
class _FakeSession:
    execution_state: _FakeExecutionState = field(default_factory=_FakeExecutionState)
    history: _FakeHistory = field(default_factory=_FakeHistory)
    focus: Any = None
    baseline_workspace: Any = None


class SlimHandlerSmokeTests(unittest.TestCase):
    def test_runtime_intent_rules_route_to_single_workspace_modes(self):
        from blender_addon.core.runtime import AgentRuntime
        from blender_addon.runtime.router import TurnClass

        session = _FakeSession()
        turn_class, meta, goal_mode = AgentRuntime._infer_turn_intent(session, "qual o estado da arvore?")
        self.assertEqual(TurnClass.CONTEXT_INQUIRY, turn_class)
        self.assertEqual("inquiry", goal_mode)
        self.assertEqual("inquiry", meta.goal_mode)

        turn_class, meta, goal_mode = AgentRuntime._infer_turn_intent(
            session,
            "[RESULTADO DE EXECUÇÃO — Revisão v38]\nResultado: FALHOU",
        )
        self.assertEqual(TurnClass.EXECUTION_FEEDBACK, turn_class)
        self.assertEqual("feedback_fix", goal_mode)
        self.assertEqual("feedback_fix", meta.goal_mode)

        session.execution_state.current_draft = types.SimpleNamespace(block_name="GN_Agent_Draft")
        turn_class, meta, goal_mode = AgentRuntime._infer_turn_intent(
            session,
            "o draft nao foi, tenta escrever novamente",
        )
        self.assertEqual(TurnClass.DRAFT_WORKSPACE, turn_class)
        self.assertEqual("focal_correction", goal_mode)
        self.assertEqual("draft_refinement", meta.turn_intent)

    def test_diagnosis_before_write_routes_read_only_even_with_write_word(self):
        from blender_addon.core.runtime import AgentRuntime
        from blender_addon.runtime.router import TurnClass

        session = _FakeSession()
        session.execution_state.current_draft = types.SimpleNamespace(block_name="GN_Agent_Draft")

        turn_class, meta, goal_mode = AgentRuntime._infer_turn_intent(
            session,
            "Faz um diagnostico geral primeiro, analise a arvore profundamente e pegue todas as certezas que vc precisa antes de escrever.",
        )

        self.assertEqual(TurnClass.DRAFT_WORKSPACE, turn_class)
        self.assertEqual("diagnose_only", goal_mode)
        self.assertEqual("diagnose_only", meta.turn_intent)
        self.assertIn("diagnose_only_request", meta.signals)

    def test_pending_repair_continua_routes_to_read_only_diagnosis(self):
        from blender_addon.core.runtime import AgentRuntime
        from blender_addon.runtime.router import TurnClass

        session = _FakeSession()
        session.execution_state.current_draft = types.SimpleNamespace(block_name="GN_Agent_Draft")
        session.execution_state.session_state = "STRATEGY_PROPOSED"
        session.execution_state.pending_user_decision = types.SimpleNamespace(
            status="pending",
            kind="repair_direction",
            options=["sim", "não"],
        )

        turn_class, meta, goal_mode = AgentRuntime._infer_turn_intent(session, "continua")

        self.assertEqual(TurnClass.DRAFT_WORKSPACE, turn_class)
        self.assertEqual("diagnose_only", goal_mode)
        self.assertEqual("diagnose_only", meta.turn_intent)
        self.assertIn("pending_diagnosis_continuation", meta.signals)

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


if __name__ == "__main__":
    unittest.main()
