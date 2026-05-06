"""Tests for Phase 3 of REFATOR_PLAN.md — Turn Router, State Machine, Prompt Builder.

Coverage:
    TurnRouter.classify:
        - phase-gated routing (awaiting_confirmation → confirmation / denial)
        - phase-gated routing (failed → post_failure_recovery)
        - greeting patterns
        - baseline refresh patterns
        - diagnosis patterns
        - mutation patterns
        - proposal patterns
        - default fallback → clarification
        - awaiting_confirmation override (non-yes/no input)

    StateMachine:
        - valid transitions (happy path)
        - invalid transition raises InvalidTransitionError
        - wildcard halt_requested from any phase
        - typed helpers (propose_mutation, confirm, deny, mark_succeeded, mark_failed, reset)

    PromptBuilder:
        - output stays within token budget
        - focus block appears when tree is focused
        - turn guidance appears for each turn class
        - knowledge items are rendered
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

# Mock bpy before importing blender_addon modules outside Blender.
if "bpy" not in sys.modules:
    _handlers = types.SimpleNamespace(load_post=[], persistent=lambda fn: fn)
    sys.modules["bpy"] = types.SimpleNamespace(
        app=types.SimpleNamespace(handlers=_handlers),
        data=types.SimpleNamespace(filepath=""),
    )

# ---------------------------------------------------------------------------
# Helpers — minimal session stubs (no Blender import required)
# ---------------------------------------------------------------------------

def _make_session(
    *,
    phase: str = "idle",
    pending_mutation: object | None = None,
    last_failure: object | None = None,
    tree_name: str = "",
    stale: bool = False,
    structural_summary: str = "",
) -> object:
    """Return a minimal duck-typed Session stub for testing."""
    execution_state = SimpleNamespace(
        phase=phase,
        pending_mutation=pending_mutation,
        last_failure=last_failure,
    )

    def _set_phase(p: str) -> None:
        execution_state.phase = p

    execution_state.set_phase = _set_phase

    focus = SimpleNamespace(tree_name=tree_name, blend_path="", signature="sig-1")
    baseline_workspace = SimpleNamespace(
        stale=stale,
        structural_summary=structural_summary,
    )
    history = SimpleNamespace(messages=[])
    identity = SimpleNamespace(blend_path="")
    lifecycle = SimpleNamespace()
    ui_state = SimpleNamespace()

    session = SimpleNamespace(
        execution_state=execution_state,
        focus=focus,
        baseline_workspace=baseline_workspace,
        history=history,
        identity=identity,
        lifecycle=lifecycle,
        ui_state=ui_state,
    )

    def _set_pending_mutation(m: object) -> None:
        execution_state.pending_mutation = m

    def _clear_pending_mutation() -> None:
        execution_state.pending_mutation = None

    session.set_pending_mutation = _set_pending_mutation
    session.clear_pending_mutation = _clear_pending_mutation

    return session


def _make_pending_mutation(description: str = "set scale to 1.0") -> object:
    return SimpleNamespace(
        description=description,
        tool_calls=[],
        focus_signature="sig-1",
    )


# ---------------------------------------------------------------------------
# TurnRouter tests
# ---------------------------------------------------------------------------

class TestTurnRouterPhaseGated(unittest.TestCase):
    def setUp(self) -> None:
        from blender_addon.runtime.router import TurnRouter, TurnClass
        self.router = TurnRouter()
        self.TurnClass = TurnClass

    def test_awaiting_confirmation_yes_routes_to_confirmation(self) -> None:
        session = _make_session(phase="awaiting_confirmation")
        for msg in ("yes", "Yes", "ok", "sure", "do it", "sim", "pode"):
            tc, meta = self.router.classify(session, msg)
            self.assertEqual(tc, self.TurnClass.MUTATION_CONFIRMATION, msg)

    def test_awaiting_confirmation_no_routes_to_denial(self) -> None:
        session = _make_session(phase="awaiting_confirmation")
        for msg in ("no", "No", "cancel", "abort", "não", "cancela"):
            tc, meta = self.router.classify(session, msg)
            self.assertEqual(tc, self.TurnClass.MUTATION_DENIAL, msg)

    def test_awaiting_confirmation_other_input_is_override(self) -> None:
        session = _make_session(phase="awaiting_confirmation")
        tc, meta = self.router.classify(session, "actually change it to 2.0 instead")
        self.assertIn("awaiting_confirmation_override", meta.signals)

    def test_failed_phase_routes_to_post_failure_recovery(self) -> None:
        session = _make_session(phase="failed")
        tc, meta = self.router.classify(session, "what happened?")
        self.assertEqual(tc, self.TurnClass.POST_FAILURE_RECOVERY)

    def test_failed_phase_any_input_goes_to_recovery(self) -> None:
        session = _make_session(phase="failed")
        for msg in ("try again", "never mind", "ok"):
            tc, _ = self.router.classify(session, msg)
            self.assertEqual(tc, self.TurnClass.POST_FAILURE_RECOVERY, msg)


class TestTurnRouterSignals(unittest.TestCase):
    def setUp(self) -> None:
        from blender_addon.runtime.router import TurnRouter, TurnClass
        self.router = TurnRouter()
        self.TurnClass = TurnClass

    def _classify(self, msg: str, phase: str = "idle"):
        session = _make_session(phase=phase)
        return self.router.classify(session, msg)

    def test_greeting_ola(self) -> None:
        tc, _ = self._classify("olá")
        self.assertEqual(tc, self.TurnClass.GREETING_OR_SMALLTALK)

    def test_greeting_hi(self) -> None:
        tc, _ = self._classify("hi")
        self.assertEqual(tc, self.TurnClass.GREETING_OR_SMALLTALK)

    def test_greeting_obrigado(self) -> None:
        tc, _ = self._classify("obrigado")
        self.assertEqual(tc, self.TurnClass.GREETING_OR_SMALLTALK)

    def test_baseline_refresh_english(self) -> None:
        tc, _ = self._classify("rebuild the baseline")
        self.assertEqual(tc, self.TurnClass.BASELINE_REFRESH)

    def test_baseline_refresh_portuguese(self) -> None:
        tc, _ = self._classify("atualiza o baseline")
        self.assertEqual(tc, self.TurnClass.BASELINE_REFRESH)

    def test_diagnosis_what_is_in_tree(self) -> None:
        tc, _ = self._classify("what is in the tree?")
        self.assertEqual(tc, self.TurnClass.DIAGNOSIS)

    def test_diagnosis_show_node(self) -> None:
        tc, _ = self._classify("show me node VM_G1_Scale")
        self.assertEqual(tc, self.TurnClass.DIAGNOSIS)

    def test_diagnosis_interrogative_start(self) -> None:
        tc, _ = self._classify("what does this modifier do?")
        self.assertEqual(tc, self.TurnClass.DIAGNOSIS)

    def test_mutation_set(self) -> None:
        tc, _ = self._classify("set VM_G1_Scale to 1.0")
        self.assertEqual(tc, self.TurnClass.MUTATION_REQUEST)

    def test_mutation_change(self) -> None:
        tc, _ = self._classify("change the scale parameter to 0.5")
        self.assertEqual(tc, self.TurnClass.MUTATION_REQUEST)

    def test_mutation_wire(self) -> None:
        tc, _ = self._classify("wire node A to node B")
        self.assertEqual(tc, self.TurnClass.MUTATION_REQUEST)

    def test_mutation_portuguese(self) -> None:
        tc, _ = self._classify("muda o valor de VM_G1_Scale para 1.0")
        self.assertEqual(tc, self.TurnClass.MUTATION_REQUEST)

    def test_mutation_portuguese_colloquial_revert(self) -> None:
        tc, _ = self._classify("pode voltar o valor de translação alterado pra 0?")
        self.assertEqual(tc, self.TurnClass.MUTATION_REQUEST)

    def test_mutation_portuguese_modificar(self) -> None:
        tc, _ = self._classify("pode modificar o valor pra 0?")
        self.assertEqual(tc, self.TurnClass.MUTATION_REQUEST)

    def test_diagnosis_question_about_previous_state_stays_non_mutation(self) -> None:
        tc, _ = self._classify("como posso voltar ao estado anterior?")
        self.assertEqual(tc, self.TurnClass.DIAGNOSIS)

    def test_diagnosis_with_alterado_stays_diagnosis(self) -> None:
        tc, _ = self._classify("analisa esse nó alterado")
        self.assertEqual(tc, self.TurnClass.DIAGNOSIS)

    def test_proposal_how_would_you(self) -> None:
        tc, _ = self._classify("how would you fix the discontinuity at the elbow?")
        self.assertEqual(tc, self.TurnClass.PROPOSAL)

    def test_proposal_suggest(self) -> None:
        tc, _ = self._classify("suggest the best way to smooth the profile")
        self.assertEqual(tc, self.TurnClass.PROPOSAL)

    def test_default_fallback_is_clarification(self) -> None:
        tc, meta = self._classify("just some random text")
        self.assertEqual(tc, self.TurnClass.CLARIFICATION)
        self.assertIn("default_clarification", meta.signals)

    def test_stale_baseline_sets_needs_refresh(self) -> None:
        session = _make_session(phase="idle", stale=True)
        _, meta = self.router.classify(session, "show me node X")
        self.assertTrue(meta.needs_baseline_refresh)

    def test_fresh_baseline_no_refresh_needed(self) -> None:
        session = _make_session(
            phase="idle",
            stale=False,
            structural_summary="summary here",
        )
        _, meta = self.router.classify(session, "show me node X")
        self.assertFalse(meta.needs_baseline_refresh)


# ---------------------------------------------------------------------------
# StateMachine tests
# ---------------------------------------------------------------------------

class TestStateMachineTransitions(unittest.TestCase):
    def setUp(self) -> None:
        from blender_addon.runtime.state_machine import StateMachine, InvalidTransitionError
        self.sm = StateMachine()
        self.InvalidTransitionError = InvalidTransitionError

    def _session(self, phase: str = "idle") -> object:
        return _make_session(phase=phase)

    # happy paths
    def test_idle_mutation_proposed(self) -> None:
        s = self._session("idle")
        new_phase = self.sm.transition(s, "mutation_proposed")
        self.assertEqual(new_phase, "awaiting_confirmation")
        self.assertEqual(s.execution_state.phase, "awaiting_confirmation")

    def test_awaiting_confirmed(self) -> None:
        s = self._session("awaiting_confirmation")
        self.sm.transition(s, "confirmed")
        self.assertEqual(s.execution_state.phase, "executing")

    def test_awaiting_denied(self) -> None:
        s = self._session("awaiting_confirmation")
        self.sm.transition(s, "denied")
        self.assertEqual(s.execution_state.phase, "idle")

    def test_executing_succeeded(self) -> None:
        s = self._session("executing")
        self.sm.transition(s, "execution_succeeded")
        self.assertEqual(s.execution_state.phase, "idle")

    def test_executing_failed(self) -> None:
        s = self._session("executing")
        self.sm.transition(s, "execution_failed")
        self.assertEqual(s.execution_state.phase, "failed")

    def test_failed_reset(self) -> None:
        s = self._session("failed")
        self.sm.transition(s, "reset")
        self.assertEqual(s.execution_state.phase, "idle")

    def test_reading_lifecycle(self) -> None:
        s = self._session("idle")
        self.sm.transition(s, "reading_started")
        self.assertEqual(s.execution_state.phase, "reading")
        self.sm.transition(s, "reading_done")
        self.assertEqual(s.execution_state.phase, "idle")

    def test_proposing_lifecycle(self) -> None:
        s = self._session("idle")
        self.sm.transition(s, "proposing_started")
        self.assertEqual(s.execution_state.phase, "proposing")
        self.sm.transition(s, "proposal_accepted")
        self.assertEqual(s.execution_state.phase, "awaiting_confirmation")

    def test_halt_from_any_phase(self) -> None:
        for phase in ("idle", "reading", "awaiting_confirmation", "executing", "failed"):
            s = self._session(phase)
            self.sm.transition(s, "halt_requested")
            self.assertEqual(s.execution_state.phase, "halted", phase)

    # error cases
    def test_invalid_transition_raises(self) -> None:
        s = self._session("idle")
        with self.assertRaises(self.InvalidTransitionError):
            self.sm.transition(s, "confirmed")  # confirmed only valid from awaiting

    def test_executing_cannot_be_proposed(self) -> None:
        s = self._session("executing")
        with self.assertRaises(self.InvalidTransitionError):
            self.sm.transition(s, "mutation_proposed")

    # typed helpers
    def test_propose_mutation_helper(self) -> None:
        s = self._session("idle")
        self.sm.propose_mutation(s)
        self.assertEqual(s.execution_state.phase, "awaiting_confirmation")

    def test_deny_helper(self) -> None:
        s = self._session("awaiting_confirmation")
        self.sm.deny(s)
        self.assertEqual(s.execution_state.phase, "idle")

    def test_mark_succeeded_helper(self) -> None:
        s = self._session("executing")
        self.sm.mark_succeeded(s)
        self.assertEqual(s.execution_state.phase, "idle")

    def test_mark_failed_helper(self) -> None:
        s = self._session("executing")
        self.sm.mark_failed(s)
        self.assertEqual(s.execution_state.phase, "failed")

    def test_reset_from_failed(self) -> None:
        s = self._session("failed")
        self.sm.reset(s)
        self.assertEqual(s.execution_state.phase, "idle")

    def test_reset_from_idle_is_noop(self) -> None:
        s = self._session("idle")
        self.sm.reset(s)  # must not raise
        self.assertEqual(s.execution_state.phase, "idle")

    def test_can_transition_true(self) -> None:
        s = self._session("idle")
        self.assertTrue(self.sm.can_transition(s, "mutation_proposed"))

    def test_can_transition_false(self) -> None:
        s = self._session("idle")
        self.assertFalse(self.sm.can_transition(s, "confirmed"))

    def test_is_awaiting(self) -> None:
        s = self._session("awaiting_confirmation")
        self.assertTrue(StateMachine.is_awaiting(s))

    def test_is_failed(self) -> None:
        s = self._session("failed")
        self.assertTrue(StateMachine.is_failed(s))

    def test_is_idle(self) -> None:
        s = self._session("idle")
        self.assertTrue(StateMachine.is_idle(s))


# We need to import StateMachine at class level for the static test above.
from blender_addon.runtime.state_machine import StateMachine


# ---------------------------------------------------------------------------
# PromptBuilder tests
# ---------------------------------------------------------------------------

class TestPromptBuilder(unittest.TestCase):
    def setUp(self) -> None:
        from blender_addon.runtime.prompt_builder import build_system_prompt
        self.build = build_system_prompt

    def _rough_token_count(self, text: str) -> int:
        """Approximate token count: 1 token ≈ 4 characters."""
        return len(text) // 4

    def test_prompt_within_budget(self) -> None:
        session = _make_session(
            tree_name="VM_G1_Forearm",
            structural_summary="Node count: 24",
        )
        prompt = self.build(session, "mutation_request")
        tokens = self._rough_token_count(prompt)
        # Hard budget from §9.4: ≤1550 tokens without knowledge.
        self.assertLessEqual(tokens, 1550, f"Prompt too large: {tokens} tokens")

    def test_prompt_with_knowledge_still_within_budget(self) -> None:
        session = _make_session(tree_name="VM_G1_Forearm")
        knowledge = [
            {"title": "GN orthosis scale", "content": "Use VM_G1_Scale for proportional scaling."},
            {"title": "Continuity rule", "content": "G1 continuity requires matching tangents at profile joints."},
        ]
        prompt = self.build(session, "mutation_request", knowledge=knowledge)
        tokens = self._rough_token_count(prompt)
        self.assertLessEqual(tokens, 2500, f"Prompt too large: {tokens} tokens")

    def test_focus_block_appears_when_tree_focused(self) -> None:
        session = _make_session(tree_name="VM_G1_Forearm")
        prompt = self.build(session, "diagnosis")
        self.assertIn("VM_G1_Forearm", prompt)

    def test_no_focus_block_when_no_tree(self) -> None:
        session = _make_session(tree_name="")
        prompt = self.build(session, "clarification")
        self.assertNotIn("Focused GN modifier:", prompt)

    def test_turn_guidance_present_for_each_class(self) -> None:
        session = _make_session()
        turn_classes = [
            "greeting_or_smalltalk",
            "clarification",
            "diagnosis",
            "baseline_refresh",
            "proposal",
            "mutation_request",
            "mutation_confirmation",
            "mutation_denial",
            "post_failure_recovery",
        ]
        for tc in turn_classes:
            prompt = self.build(session, tc)
            self.assertIn("This turn:", prompt, f"Missing guidance for {tc}")

    def test_diagnosis_guidance_prefers_broad_reads_before_narrow(self) -> None:
        session = _make_session()
        prompt = self.build(session, "diagnosis")
        self.assertIn("get_scene_summary", prompt)
        self.assertIn("get_gn_hosts", prompt)
        self.assertIn("Do not open ``get_local_subgraph_context`` just because a node is selected.", prompt)

    def test_proposal_guidance_prefers_broad_reads_before_narrow(self) -> None:
        session = _make_session()
        prompt = self.build(session, "proposal")
        self.assertIn("get_scene_summary", prompt)
        self.assertIn("get_gn_hosts", prompt)
        self.assertIn("Do not open ``get_local_subgraph_context`` just because a node is selected.", prompt)

    def test_stale_baseline_hint_appears(self) -> None:
        session = _make_session(stale=True)
        prompt = self.build(session, "diagnosis")
        self.assertIn("stale", prompt.lower())

    def test_awaiting_confirmation_hint_appears(self) -> None:
        pm = _make_pending_mutation("set VM_G1_Scale to 1.0")
        session = _make_session(phase="awaiting_confirmation", pending_mutation=pm)
        prompt = self.build(session, "mutation_confirmation")
        self.assertIn("awaiting confirmation", prompt.lower())

    def test_knowledge_items_rendered(self) -> None:
        session = _make_session()
        knowledge = [{"title": "Test Knowledge", "content": "This is test content."}]
        prompt = self.build(session, "diagnosis", knowledge=knowledge)
        self.assertIn("Test Knowledge", prompt)
        self.assertIn("This is test content.", prompt)

    def test_empty_knowledge_no_section(self) -> None:
        session = _make_session()
        prompt_with = self.build(session, "diagnosis", knowledge=[])
        prompt_without = self.build(session, "diagnosis", knowledge=None)
        self.assertEqual(prompt_with, prompt_without)


# ---------------------------------------------------------------------------
# HandlerResult / TurnContext unit tests (no API calls)
# ---------------------------------------------------------------------------

class TestHandlerResult(unittest.TestCase):
    def test_defaults(self) -> None:
        from blender_addon.runtime.handlers import HandlerResult
        r = HandlerResult(response_text="hello")
        self.assertEqual(r.response_text, "hello")
        self.assertEqual(r.tool_calls_made, [])
        self.assertIsNone(r.phase_transition)
        self.assertEqual(r.session_mutations, [])


class TestMutationDenialHandler(unittest.TestCase):
    """denial handler requires no API — safe to test without mocking client."""

    def test_denial_clears_pending_and_transitions_idle(self) -> None:
        from blender_addon.runtime.handlers.mutation_denial import handle
        from blender_addon.runtime.handlers import TurnContext
        from blender_addon.runtime.router import TurnClass
        from blender_addon.runtime.router import ClassifierMeta

        pm = _make_pending_mutation("set scale to 2.0")
        session = _make_session(phase="awaiting_confirmation", pending_mutation=pm)
        meta = ClassifierMeta(turn_class=TurnClass.MUTATION_DENIAL)
        ctx = TurnContext(
            session=session,
            message="no",
            meta=meta,
            blend_path="",
        )
        result = handle(ctx)
        self.assertIn("won't make", result.response_text.lower())
        self.assertEqual(result.phase_transition, "idle")
        self.assertIsNone(session.execution_state.pending_mutation)
        self.assertEqual(session.execution_state.phase, "idle")

    def test_denial_without_pending_mutation(self) -> None:
        from blender_addon.runtime.handlers.mutation_denial import handle
        from blender_addon.runtime.handlers import TurnContext
        from blender_addon.runtime.router import TurnClass, ClassifierMeta

        session = _make_session(phase="awaiting_confirmation")
        meta = ClassifierMeta(turn_class=TurnClass.MUTATION_DENIAL)
        ctx = TurnContext(session=session, message="no", meta=meta, blend_path="")
        result = handle(ctx)
        self.assertEqual(result.phase_transition, "idle")


class TestGreetingHandlerNoRuntime(unittest.TestCase):
    """Greeting handler works without a live runtime for fixed replies."""

    def test_fixed_greeting_ola(self) -> None:
        from blender_addon.runtime.handlers.greeting import handle
        from blender_addon.runtime.handlers import TurnContext
        from blender_addon.runtime.router import TurnClass, ClassifierMeta

        session = _make_session()
        meta = ClassifierMeta(turn_class=TurnClass.GREETING_OR_SMALLTALK)
        ctx = TurnContext(session=session, message="olá", meta=meta, blend_path="")
        result = handle(ctx)
        self.assertTrue(len(result.response_text) > 0)

    def test_fixed_greeting_obrigado(self) -> None:
        from blender_addon.runtime.handlers.greeting import handle
        from blender_addon.runtime.handlers import TurnContext
        from blender_addon.runtime.router import TurnClass, ClassifierMeta

        session = _make_session()
        meta = ClassifierMeta(turn_class=TurnClass.GREETING_OR_SMALLTALK)
        ctx = TurnContext(session=session, message="obrigado", meta=meta, blend_path="")
        result = handle(ctx)
        self.assertIn("nada", result.response_text.lower())


if __name__ == "__main__":
    unittest.main()
