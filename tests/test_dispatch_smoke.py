"""Smoke tests for the live draft-first dispatch surface."""

from __future__ import annotations

import sys
import types
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch


def _install_fake_bpy():
    bpy = types.ModuleType("bpy")
    handlers = types.SimpleNamespace(
        persistent=lambda fn: fn,
        load_post=[],
        save_post=[],
    )
    timers = types.SimpleNamespace(register=lambda fn: fn())
    bpy.app = types.SimpleNamespace(handlers=handlers, timers=timers)
    bpy.data = types.SimpleNamespace(filepath="")
    sys.modules["bpy"] = bpy


_install_fake_bpy()

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))


@dataclass
class _FakeExecutionState:
    phase: str = "idle"
    current_draft: Any = None
    session_state: str = "IDLE"
    retry_requires_draft_change: bool = False
    pending_draft_action: str = ""
    pending_draft_prompt: str = ""
    post_failure_state: str = ""
    proposed_strategy_count: int = 0
    proposed_strategy_revision: int = 0
    approved_strategy_label: str = ""
    approved_strategy_prompt: str = ""


@dataclass
class _FakeHistory:
    messages: list = field(default_factory=list)


@dataclass
class _FakeSession:
    execution_state: _FakeExecutionState = field(default_factory=_FakeExecutionState)
    history: _FakeHistory = field(default_factory=_FakeHistory)
    focus: Any = None
    baseline_workspace: Any = None


def _make_ctx(message: str = "ola", session: Any = None) -> Any:
    from blender_addon.runtime.handlers import TurnContext
    from blender_addon.runtime.router import ClassifierMeta, TurnClass

    rt = MagicMock()
    rt._messages = []
    rt._agent_loop = MagicMock(return_value="stub response")
    rt._request_text_response = MagicMock(return_value="stub response")
    rt._execute_tool = MagicMock(return_value='{"result": {}}')
    rt.journal = None
    rt.tools = []
    rt.model = "claude-sonnet-4-6"

    return TurnContext(
        session=session or _FakeSession(),
        message=message,
        meta=ClassifierMeta(turn_class=TurnClass.CONTEXT_INQUIRY),
        blend_path="",
        _runtime=rt,
        knowledge_dir=Path("/nonexistent/knowledge/domain"),
    )


class DraftFirstDispatchSmokeTests(unittest.TestCase):
    def test_live_turn_classes_are_the_only_dispatch_surface(self):
        from blender_addon.runtime.router import TurnClass

        self.assertEqual(
            {tc.value for tc in TurnClass},
            {
                "trivial_chat",
                "context_inquiry",
                "draft_workspace",
                "execution_feedback",
                "state_control",
            },
        )

    def test_all_live_turn_classes_have_dispatch_entry(self):
        from blender_addon.runtime.handlers import HandlerResult, dispatch_turn
        from blender_addon.runtime.router import ClassifierMeta, TurnClass

        with patch("blender_addon.runtime.handlers.greeting", create=True) as mock_greeting, \
             patch("blender_addon.runtime.handlers.workspace", create=True) as mock_workspace, \
             patch("blender_addon.runtime.handlers.drafting", create=True) as mock_drafting:
            stub = HandlerResult(response_text="stub")
            mock_greeting.handle = MagicMock(return_value=stub)
            mock_workspace.handle = MagicMock(return_value=stub)
            mock_drafting.handle_draft_workspace = MagicMock(return_value=stub)
            mock_drafting.handle_execution_feedback = MagicMock(return_value=stub)
            mock_drafting.handle_state_control = MagicMock(return_value=stub)

            missing: list[str] = []
            for turn_class in TurnClass:
                ctx = _make_ctx()
                ctx.meta = ClassifierMeta(turn_class=turn_class)
                result = dispatch_turn(turn_class, ctx)
                if "not sure how to handle" in (result.response_text or "").lower():
                    missing.append(turn_class.value)

        self.assertEqual([], missing)

    def test_dispatch_does_not_import_legacy_mutation_handlers(self):
        import inspect
        import blender_addon.runtime.handlers as handlers

        source = inspect.getsource(handlers.dispatch_turn)
        self.assertNotIn("mutation" + "_request", source)
        self.assertNotIn("mutation" + "_confirmation", source)
        self.assertNotIn("mutation" + "_denial", source)
        self.assertNotIn("make_plan", source)
        self.assertNotIn("execute_code", source)

    def test_context_inquiry_dispatches_to_workspace_inquiry_goal(self):
        from blender_addon.runtime.handlers import HandlerResult, dispatch_turn
        from blender_addon.runtime.router import ClassifierMeta, TurnClass

        with patch("blender_addon.runtime.handlers.workspace", create=True) as mock_workspace:
            stub = HandlerResult(response_text="workspace")
            mock_workspace.handle = MagicMock(return_value=stub)
            ctx = _make_ctx("qual o estado da arvore?")
            ctx.meta = ClassifierMeta(turn_class=TurnClass.CONTEXT_INQUIRY)

            result = dispatch_turn(TurnClass.CONTEXT_INQUIRY, ctx)

        self.assertEqual("workspace", result.response_text)
        mock_workspace.handle.assert_called_once()
        self.assertEqual("inquiry", mock_workspace.handle.call_args.args[1])

    def test_draft_workspace_dispatch_passes_explicit_goal_mode(self):
        from blender_addon.runtime.handlers import HandlerResult, dispatch_turn
        from blender_addon.runtime.router import ClassifierMeta, TurnClass

        with patch("blender_addon.runtime.handlers.workspace", create=True) as mock_workspace:
            stub = HandlerResult(response_text="workspace")
            mock_workspace.handle = MagicMock(return_value=stub)
            ctx = _make_ctx("corrige o draft")
            ctx.meta = ClassifierMeta(
                turn_class=TurnClass.DRAFT_WORKSPACE,
                turn_intent="draft_refinement",
            )

            result = dispatch_turn(TurnClass.DRAFT_WORKSPACE, ctx)

        self.assertEqual("workspace", result.response_text)
        mock_workspace.handle.assert_called_once()
        self.assertEqual("focal_correction", mock_workspace.handle.call_args.args[1])

    def test_draft_workspace_correction_question_is_diagnose_only(self):
        from blender_addon.runtime.handlers import HandlerResult, dispatch_turn
        from blender_addon.runtime.router import ClassifierMeta, TurnClass

        with patch("blender_addon.runtime.handlers.workspace", create=True) as mock_workspace:
            stub = HandlerResult(response_text="workspace")
            mock_workspace.handle = MagicMock(return_value=stub)
            ctx = _make_ctx("Podemos tentar corrigir?")
            ctx.meta = ClassifierMeta(
                turn_class=TurnClass.DRAFT_WORKSPACE,
                turn_intent="pure_inquiry",
            )

            dispatch_turn(TurnClass.DRAFT_WORKSPACE, ctx)

        self.assertEqual("diagnose_only", mock_workspace.handle.call_args.args[1])

    def test_draft_workspace_revision_proposal_is_diagnose_only(self):
        from blender_addon.runtime.handlers import HandlerResult, dispatch_turn
        from blender_addon.runtime.router import ClassifierMeta, TurnClass

        with patch("blender_addon.runtime.handlers.workspace", create=True) as mock_workspace:
            stub = HandlerResult(response_text="workspace")
            mock_workspace.handle = MagicMock(return_value=stub)
            ctx = _make_ctx("certo proponha entao a revisao")
            ctx.meta = ClassifierMeta(
                turn_class=TurnClass.DRAFT_WORKSPACE,
                turn_intent="pure_inquiry",
            )

            dispatch_turn(TurnClass.DRAFT_WORKSPACE, ctx)

        self.assertEqual("diagnose_only", mock_workspace.handle.call_args.args[1])

    def test_draft_workspace_move_fix_is_focal_correction(self):
        from blender_addon.runtime.handlers import HandlerResult, dispatch_turn
        from blender_addon.runtime.router import ClassifierMeta, TurnClass

        with patch("blender_addon.runtime.handlers.workspace", create=True) as mock_workspace:
            stub = HandlerResult(response_text="workspace")
            mock_workspace.handle = MagicMock(return_value=stub)
            ctx = _make_ctx("basta mover o que ja estava bom para a ponta da esfera do punho")
            ctx.meta = ClassifierMeta(
                turn_class=TurnClass.DRAFT_WORKSPACE,
                turn_intent="pure_inquiry",
            )

            dispatch_turn(TurnClass.DRAFT_WORKSPACE, ctx)

        self.assertEqual("focal_correction", mock_workspace.handle.call_args.args[1])

    def test_workspace_diagnose_only_is_read_only_and_not_legacy(self):
        from blender_addon.runtime.handlers.workspace import GOAL_CONFIGS

        config = GOAL_CONFIGS["diagnose_only"]

        self.assertTrue(config.read_only)
        self.assertEqual("", config.legacy_handler)
        self.assertIn("write_script_draft", config.excluded_tools)

    def test_workspace_focal_correction_is_migrated_write_goal(self):
        from blender_addon.runtime.handlers.workspace import GOAL_CONFIGS

        config = GOAL_CONFIGS["focal_correction"]

        self.assertFalse(config.read_only)
        self.assertEqual("", config.legacy_handler)
        self.assertNotIn("write_script_draft", config.excluded_tools)
        self.assertEqual(4, config.max_rounds)

    def test_workspace_goal_mode_treats_explicit_write_text_as_focal_correction(self):
        from blender_addon.runtime.handlers import TurnContext, _workspace_goal_mode
        from blender_addon.runtime.router import ClassifierMeta, TurnClass

        ctx = TurnContext(
            session=object(),
            message="ok entao escreva",
            meta=ClassifierMeta(turn_class=TurnClass.DRAFT_WORKSPACE, turn_intent="pure_inquiry"),
            blend_path="",
            _runtime=None,
        )

        self.assertEqual("focal_correction", _workspace_goal_mode(ctx, TurnClass.DRAFT_WORKSPACE))

    def test_workspace_goal_mode_keeps_pure_inquiry_read_only(self):
        from blender_addon.runtime.handlers import TurnContext, _workspace_goal_mode
        from blender_addon.runtime.router import ClassifierMeta, TurnClass

        ctx = TurnContext(
            session=object(),
            message="Bora la, vamos tentar denovo. A arvore esta funcionando bem, eu so esperava outro resultado.",
            meta=ClassifierMeta(turn_class=TurnClass.DRAFT_WORKSPACE, turn_intent="pure_inquiry"),
            blend_path="",
            _runtime=None,
        )

        self.assertEqual("diagnose_only", _workspace_goal_mode(ctx, TurnClass.DRAFT_WORKSPACE))

    def test_workspace_goal_mode_keeps_repairing_draft_question_read_only(self):
        from blender_addon.runtime.handlers import TurnContext, _workspace_goal_mode
        from blender_addon.runtime.router import ClassifierMeta, TurnClass

        session = _FakeSession()
        session.execution_state.retry_requires_draft_change = True
        ctx = TurnContext(
            session=session,
            message="o draft aparentemente nao criou nem manipulou nenhum no. Isso condiz?",
            meta=ClassifierMeta(
                turn_class=TurnClass.DRAFT_WORKSPACE,
                turn_intent="pure_inquiry",
                session_state="REPAIRING",
            ),
            blend_path="",
            _runtime=None,
        )

        self.assertEqual("diagnose_only", _workspace_goal_mode(ctx, TurnClass.DRAFT_WORKSPACE))

    def test_workspace_goal_mode_treats_functional_mismatch_as_correction(self):
        from blender_addon.runtime.handlers import TurnContext, _workspace_goal_mode
        from blender_addon.runtime.router import ClassifierMeta, TurnClass

        ctx = TurnContext(
            session=object(),
            message=(
                "O comprimento do metacarpo está parametrizado, todavia o acompanhamento "
                "das falanges nao acontece grudado na face frontal do cubo dos metacarpos. "
                "Ele avança e recua nao de maneira linear, colada nos metacarpos"
            ),
            meta=ClassifierMeta(turn_class=TurnClass.DRAFT_WORKSPACE, turn_intent="pure_inquiry"),
            blend_path="",
            _runtime=None,
        )

        self.assertEqual("focal_correction", _workspace_goal_mode(ctx, TurnClass.DRAFT_WORKSPACE))

    def test_workspace_goal_mode_keeps_explicit_diagnosis_read_only(self):
        from blender_addon.runtime.handlers import TurnContext, _workspace_goal_mode
        from blender_addon.runtime.router import ClassifierMeta, TurnClass

        ctx = TurnContext(
            session=object(),
            message="faz um diagnostico antes de escrever",
            meta=ClassifierMeta(turn_class=TurnClass.DRAFT_WORKSPACE, turn_intent="pure_inquiry"),
            blend_path="",
            _runtime=None,
        )

        self.assertEqual("diagnose_only", _workspace_goal_mode(ctx, TurnClass.DRAFT_WORKSPACE))

    def test_workspace_goal_mode_repairing_soft_continuation_stays_read_only(self):
        from blender_addon.runtime.handlers import TurnContext, _workspace_goal_mode
        from blender_addon.runtime.router import ClassifierMeta, TurnClass

        session = _FakeSession()
        session.execution_state.phase = "drafting"
        session.execution_state.retry_requires_draft_change = True
        session.execution_state.pending_draft_action = "write_confirmed_draft_revision"
        ctx = TurnContext(
            session=session,
            message="vc consegue seguir agora?",
            meta=ClassifierMeta(
                turn_class=TurnClass.DRAFT_WORKSPACE,
                turn_intent="pure_inquiry",
                session_state="REPAIRING",
            ),
            blend_path="",
            _runtime=None,
        )

        self.assertEqual("diagnose_only", _workspace_goal_mode(ctx, TurnClass.DRAFT_WORKSPACE))

    def test_workspace_goal_mode_repairing_approved_strategy_writes(self):
        from blender_addon.runtime.handlers import TurnContext, _workspace_goal_mode
        from blender_addon.runtime.router import ClassifierMeta, TurnClass

        session = _FakeSession()
        session.execution_state.phase = "drafting"
        session.execution_state.retry_requires_draft_change = True
        session.execution_state.post_failure_state = "STRATEGY_PROPOSED"
        session.execution_state.session_state = "STRATEGY_PROPOSED"
        session.execution_state.proposed_strategy_count = 2
        ctx = TurnContext(
            session=session,
            message="segue com a opção A e reescreve o draft",
            meta=ClassifierMeta(
                turn_class=TurnClass.DRAFT_WORKSPACE,
                turn_intent="pure_inquiry",
                session_state="REPAIRING",
            ),
            blend_path="",
            _runtime=None,
        )

        self.assertEqual("focal_correction", _workspace_goal_mode(ctx, TurnClass.DRAFT_WORKSPACE))
        self.assertEqual("STRATEGY_APPROVED", session.execution_state.post_failure_state)
        self.assertEqual("A", session.execution_state.approved_strategy_label)
        self.assertEqual("write_approved_strategy_revision", session.execution_state.pending_draft_action)

    def test_workspace_goal_mode_option_without_proposed_strategy_stays_read_only(self):
        from blender_addon.runtime.handlers import TurnContext, _workspace_goal_mode
        from blender_addon.runtime.router import ClassifierMeta, TurnClass

        session = _FakeSession()
        session.execution_state.phase = "drafting"
        session.execution_state.retry_requires_draft_change = True
        ctx = TurnContext(
            session=session,
            message="segue com a opção A",
            meta=ClassifierMeta(
                turn_class=TurnClass.DRAFT_WORKSPACE,
                turn_intent="pure_inquiry",
                session_state="REPAIRING",
            ),
            blend_path="",
            _runtime=None,
        )

        self.assertEqual("diagnose_only", _workspace_goal_mode(ctx, TurnClass.DRAFT_WORKSPACE))
        self.assertEqual("", session.execution_state.approved_strategy_label)

    def test_workspace_functional_expansion_is_migrated_write_goal(self):
        from blender_addon.runtime.handlers.workspace import GOAL_CONFIGS

        config = GOAL_CONFIGS["functional_expansion"]

        self.assertFalse(config.read_only)
        self.assertEqual("", config.legacy_handler)
        self.assertNotIn("write_script_draft", config.excluded_tools)
        self.assertEqual(5, config.max_rounds)

    def test_workspace_feedback_fix_is_migrated_economy_write_goal(self):
        from blender_addon.runtime.handlers.workspace import GOAL_CONFIGS

        config = GOAL_CONFIGS["feedback_fix"]

        self.assertFalse(config.read_only)
        self.assertEqual("", config.legacy_handler)
        self.assertNotIn("write_script_draft", config.excluded_tools)
        self.assertEqual(3, config.max_rounds)
        self.assertEqual(3, config.focal_budget_min)

    def test_knowledge_budget_only_tracks_live_intents(self):
        from blender_addon.runtime.handlers import _KNOWLEDGE_BUDGET_BY_CLASS

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
