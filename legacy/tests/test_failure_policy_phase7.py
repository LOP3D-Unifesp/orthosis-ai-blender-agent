"""Tests for Phase 7 — one-shot explain-and-stop failure policy.

Validates that the live handler architecture enforces the failure policy
described in §2.5 and §8.6 of REFATOR_PLAN.md:

  - mutation_confirmation halts with an explanation on failure (phase → failed).
  - No replan is generated, no new approval token issued, no retry.
  - The router routes phase == "failed" to POST_FAILURE_RECOVERY exclusively.
  - post_failure_recovery resets phase to idle (the user can issue a new request).
  - The StateMachine has no "replan" or "retry" transition from "failed".
  - consecutive_failures was removed from ExecutionState (Phase 7).
  - BASE_SYSTEM_PROMPT does not instruct the model to replan after failure.
  - Tombstoned replan modules raise ImportError on access.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Minimal session stub (no Blender / no API key required)
# ---------------------------------------------------------------------------

def _make_session(
    *,
    phase: str = "idle",
    pending_mutation: object | None = None,
    last_failure: object | None = None,
    tree_name: str = "",
) -> object:
    """Duck-typed Session stub that the handlers can operate on."""
    execution_state = SimpleNamespace(
        phase=phase,
        pending_mutation=pending_mutation,
        last_failure=last_failure,
    )

    def _set_phase(p: str) -> None:
        execution_state.phase = p

    execution_state.set_phase = _set_phase

    focus = SimpleNamespace(tree_name=tree_name, blend_path="", focus_signature="sig-test")
    baseline_workspace = SimpleNamespace(stale=False, structural_summary="")
    history = SimpleNamespace(messages=[])

    session = SimpleNamespace(
        execution_state=execution_state,
        focus=focus,
        baseline_workspace=baseline_workspace,
        history=history,
    )

    def _clear_pending_mutation() -> None:
        session.execution_state.pending_mutation = None

    def _set_pending_mutation(m: object) -> None:
        session.execution_state.pending_mutation = m

    session.clear_pending_mutation = _clear_pending_mutation
    session.set_pending_mutation = _set_pending_mutation
    return session


def _make_pending_mutation(description: str = "Set VM_G1_Scale to 1.0") -> object:
    return SimpleNamespace(
        description=description,
        tool_calls=[],  # no pre-captured calls → agent-loop path
        proposed_at="2026-01-01T00:00:00Z",
        focus_signature="sig-test",
        plan_used=False,
    )


def _make_turn_context(session: object, message: str = "yes") -> object:
    """Minimal TurnContext stub."""
    from blender_addon.runtime.router import ClassifierMeta, TurnClass

    journal = MagicMock()
    journal.log_runtime_event = MagicMock()

    runtime = MagicMock()
    runtime.journal = journal
    runtime._messages = []
    runtime.tools = []
    runtime.model = "claude-sonnet-4-6"

    from pathlib import Path

    meta = ClassifierMeta(turn_class=TurnClass.MUTATION_CONFIRMATION)
    from blender_addon.runtime.handlers import TurnContext

    ctx = TurnContext(
        session=session,
        message=message,
        meta=meta,
        blend_path="test.blend",
        _runtime=runtime,
        knowledge_dir=Path("/nonexistent/knowledge/domain"),
    )
    return ctx


# ---------------------------------------------------------------------------
# State machine — failure policy invariants
# ---------------------------------------------------------------------------

class TestStateMachineFailurePolicy(unittest.TestCase):
    """The state machine must have no replan or retry transitions from failed."""

    def setUp(self):
        from blender_addon.runtime.state_machine import StateMachine, InvalidTransitionError
        self.sm = StateMachine()
        self.InvalidTransition = InvalidTransitionError

    def _session(self, phase: str) -> object:
        return _make_session(phase=phase)

    def test_failed_resets_to_idle_via_reset(self):
        s = self._session("failed")
        self.sm.reset(s)
        self.assertEqual(s.execution_state.phase, "idle")

    def test_failed_cannot_transition_to_executing(self):
        s = self._session("failed")
        with self.assertRaises(self.InvalidTransition):
            self.sm.transition(s, "confirmed")

    def test_failed_cannot_transition_to_awaiting_confirmation(self):
        s = self._session("failed")
        with self.assertRaises(self.InvalidTransition):
            self.sm.transition(s, "mutation_proposed")

    def test_failed_cannot_loop_back_via_execution_failed(self):
        """There must be no transition that keeps or re-enters 'executing' from 'failed'."""
        s = self._session("failed")
        with self.assertRaises(self.InvalidTransition):
            self.sm.transition(s, "execution_failed")

    def test_no_replan_event_exists(self):
        """The string 'replan' must not name any transition event."""
        from blender_addon.runtime.state_machine import _TRANSITIONS
        event_names = {event for (_phase, event) in _TRANSITIONS}
        for event in event_names:
            self.assertNotIn("replan", event.lower(), f"Event {event!r} contains 'replan'")

    def test_mark_failed_transitions_to_failed(self):
        s = self._session("executing")
        self.sm.mark_failed(s)
        self.assertEqual(s.execution_state.phase, "failed")


# ---------------------------------------------------------------------------
# Router — phase-gated routing after failure
# ---------------------------------------------------------------------------

class TestRouterFailureGating(unittest.TestCase):
    """When phase == 'failed', every user message must route to POST_FAILURE_RECOVERY."""

    def setUp(self):
        from blender_addon.runtime.router import TurnRouter, TurnClass
        self.router = TurnRouter()
        self.TurnClass = TurnClass

    def _classify(self, message: str, phase: str = "failed") -> object:
        s = _make_session(phase=phase)
        tc, _meta = self.router.classify(s, message)
        return tc

    def test_any_message_routes_to_recovery_when_failed(self):
        for msg in ["ok", "what happened?", "set scale to 1.0", "yes", "no", "hello"]:
            with self.subTest(msg=msg):
                tc = self._classify(msg, phase="failed")
                self.assertEqual(tc, self.TurnClass.POST_FAILURE_RECOVERY)

    def test_idle_mutation_does_not_route_to_recovery(self):
        tc = self._classify("set VM_G1_Scale to 1.0", phase="idle")
        self.assertNotEqual(tc, self.TurnClass.POST_FAILURE_RECOVERY)


# ---------------------------------------------------------------------------
# mutation_confirmation handler — explain-and-stop on failure
# ---------------------------------------------------------------------------

class TestMutationConfirmationFailurePolicy(unittest.TestCase):
    """Failing mutations must produce an explanation and set phase = 'failed'.
    No replan is generated, no approval token issued.
    """

    def _run_failure(self, error_text: str = "AttributeError: 'NoneType'") -> tuple:
        """Execute the mutation_confirmation handler with a forced failure.

        The agent loop raises an exception to simulate a failed execution.
        Returns (session, handler_result).
        """
        from blender_addon.runtime.handlers.mutation_confirmation import handle

        pending = _make_pending_mutation("Set VM_G1_Scale to 1.0")
        session = _make_session(phase="awaiting_confirmation", pending_mutation=pending)
        ctx = _make_turn_context(session, message="yes")

        # Force the agent loop to raise so the handler sees an error.
        ctx._runtime._agent_loop = MagicMock(side_effect=RuntimeError(error_text))

        result = handle(ctx)
        return session, result

    def test_failure_sets_phase_to_failed(self):
        session, _result = self._run_failure()
        self.assertEqual(session.execution_state.phase, "failed")

    def test_failure_records_last_failure(self):
        session, _result = self._run_failure("KeyError: 'VM_G1_Scale'")
        self.assertIsNotNone(session.execution_state.last_failure)
        self.assertIn("KeyError", session.execution_state.last_failure.error)

    def test_failure_response_mentions_error(self):
        _session, result = self._run_failure("SyntaxError: invalid syntax")
        self.assertIn("SyntaxError", result.response_text)

    def test_failure_clears_pending_mutation(self):
        session, _result = self._run_failure()
        self.assertIsNone(session.execution_state.pending_mutation)

    def test_failure_phase_transition_is_failed(self):
        _s, result = self._run_failure()
        self.assertEqual(result.phase_transition, "failed")

    def test_failure_does_not_contain_replan_text(self):
        _s, result = self._run_failure("random error")
        lowered = result.response_text.lower()
        # Must not propose automatic replanning.
        self.assertNotIn("replan", lowered)
        self.assertNotIn("novo plano", lowered)
        self.assertNotIn("approval token", lowered)

    def test_success_sets_phase_to_idle(self):
        """Positive control: a successful execution must not set failed phase."""
        from blender_addon.runtime.handlers.mutation_confirmation import handle

        pending = _make_pending_mutation("Set VM_G1_Scale to 1.0")
        session = _make_session(phase="awaiting_confirmation", pending_mutation=pending)
        ctx = _make_turn_context(session, message="yes")

        # Mock agent loop to return success text.
        ctx._runtime._agent_loop = MagicMock(return_value="VM_G1_Scale set to 1.0 successfully.")

        result = handle(ctx)
        self.assertNotEqual(session.execution_state.phase, "failed")
        self.assertEqual(result.phase_transition, "idle")


# ---------------------------------------------------------------------------
# post_failure_recovery handler — resets to idle, no retry
# ---------------------------------------------------------------------------

class TestPostFailureRecoveryHandler(unittest.TestCase):
    """post_failure_recovery must explain the failure and reset to idle."""

    def _run_recovery(self, last_failure_text: str = "AttributeError") -> tuple:
        from blender_addon.runtime.handlers.post_failure_recovery import handle
        from blender_addon.session.schema import LastFailure

        lf = LastFailure(
            tool="execute_code",
            error=last_failure_text,
            cause="execution_failed",
            suggested_alternative="",
        )
        session = _make_session(phase="failed", last_failure=lf)
        ctx = _make_turn_context(session, message="what went wrong?")
        # Mock the API call so we don't need a real key.
        ctx._runtime._agent_loop = MagicMock(return_value="The execution failed because of X. Try Y instead.")
        # retrieve_knowledge returns empty list (no corpus dir).
        result = handle(ctx)
        return session, result

    def test_recovery_resets_phase_to_idle(self):
        session, _result = self._run_recovery()
        self.assertEqual(session.execution_state.phase, "idle")

    def test_recovery_phase_transition_is_idle(self):
        _s, result = self._run_recovery()
        self.assertEqual(result.phase_transition, "idle")

    def test_recovery_returns_text_response(self):
        _s, result = self._run_recovery()
        self.assertIsInstance(result.response_text, str)
        self.assertTrue(len(result.response_text) > 0)

    def test_recovery_does_not_propose_new_approval(self):
        _s, result = self._run_recovery("some error")
        lowered = result.response_text.lower()
        self.assertNotIn("approval token", lowered)
        self.assertNotIn("replan", lowered)


# ---------------------------------------------------------------------------
# ExecutionState — consecutive_failures removed
# ---------------------------------------------------------------------------

class TestConsecutiveFailuresRemoved(unittest.TestCase):
    """Phase 7: consecutive_failures must not exist on ExecutionState."""

    def test_execution_state_has_no_consecutive_failures(self):
        from blender_addon.session.schema import ExecutionState
        es = ExecutionState()
        self.assertFalse(
            hasattr(es, "consecutive_failures"),
            "consecutive_failures must not exist on ExecutionState after Phase 7",
        )

    def test_execution_state_serialisation_has_no_consecutive_failures(self):
        from blender_addon.session.schema import ExecutionState
        d = ExecutionState().to_dict()
        self.assertNotIn("consecutive_failures", d)

    def test_execution_state_from_dict_ignores_stale_consecutive_failures(self):
        """Sessions serialised by older versions must load cleanly."""
        from blender_addon.session.schema import ExecutionState
        es = ExecutionState.from_dict({"phase": "idle", "consecutive_failures": 99})
        self.assertFalse(hasattr(es, "consecutive_failures"))
        self.assertEqual(es.phase, "idle")


# ---------------------------------------------------------------------------
# System prompt — must not instruct model to replan
# ---------------------------------------------------------------------------

class TestSystemPromptFailurePolicy(unittest.TestCase):
    """BASE_SYSTEM_PROMPT must not tell the model to replan after failure."""

    def test_base_prompt_does_not_say_replan(self):
        from blender_addon import agent_runtime as ar
        prompt = ar.BASE_SYSTEM_PROMPT.lower()
        # Must not instruct the model to replan after a mutation fails.
        self.assertNotIn(
            "stop, replan",
            prompt,
            "BASE_SYSTEM_PROMPT still instructs the model to replan after failure",
        )

    def test_base_prompt_does_not_require_dedicated_fallback_approval(self):
        from blender_addon import agent_runtime as ar
        prompt = ar.BASE_SYSTEM_PROMPT.lower()
        self.assertNotIn(
            "dedicated approval",
            prompt,
            "BASE_SYSTEM_PROMPT still references fallback/dedicated approval gate",
        )

    def test_base_prompt_says_no_automatic_replan(self):
        from blender_addon import agent_runtime as ar
        prompt = ar.BASE_SYSTEM_PROMPT
        self.assertIn(
            "No automatic replan",
            prompt,
            "BASE_SYSTEM_PROMPT should state 'No automatic replan'",
        )


# ---------------------------------------------------------------------------
# Tombstone guards — legacy replan modules must raise ImportError
# ---------------------------------------------------------------------------

class TestTombstoneGuardsPhase7(unittest.TestCase):
    """Accessing any symbol from the tombstoned replan modules must raise ImportError."""

    def test_execution_postprocess_raises(self):
        import blender_addon.execution_postprocess as ep
        with self.assertRaises(ImportError):
            _ = ep.build_replan_payload

    def test_execution_postprocess_render_replan_raises(self):
        import blender_addon.execution_postprocess as ep
        with self.assertRaises(ImportError):
            _ = ep.render_replan_message

    def test_runtime_execution_raises(self):
        import blender_addon.runtime_execution as re_mod
        with self.assertRaises(ImportError):
            _ = re_mod.execute_tool

    def test_runtime_governance_raises(self):
        import blender_addon.runtime_governance as rg
        with self.assertRaises(ImportError):
            _ = rg.has_valid_fallback_approval

    def test_execution_prechecks_raises(self):
        import blender_addon.execution_prechecks as ep
        with self.assertRaises(ImportError):
            _ = ep.ensure_execute_code_fallback_precheck


if __name__ == "__main__":
    unittest.main()
