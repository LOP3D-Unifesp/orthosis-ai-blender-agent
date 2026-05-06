"""Tests for Phase 4 of REFATOR_PLAN.md — Phase-based authorization.

Coverage:
    AgentRuntime._execute_tool:
        - read tools are allowed from any phase
        - mutation tools blocked when phase != 'executing'
        - mutation tools allowed when phase == 'executing'
        - make_plan allowed from any phase (not a mutation gate)
        - execute_code blocked when idle (not executing)

    Tombstone guards:
        - execution_prechecks functions raise ImportError
        - runtime_governance functions raise ImportError

    StateMachine confirmation flow (end-to-end):
        - idle → propose_mutation → awaiting_confirmation
        - awaiting_confirmation → confirm → executing
        - executing → mark_succeeded → idle
        - awaiting_confirmation → deny → idle
        - failed → reset → idle

    mutation_confirmation handler:
        - calls _sm.confirm before tool dispatch
        - phase is 'executing' during tool replay

    TurnRouter phase gates still intact (no regression):
        - awaiting_confirmation + yes → mutation_confirmation
        - awaiting_confirmation + no  → mutation_denial
        - failed → post_failure_recovery
"""

from __future__ import annotations

import sys
import types
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

# Mock bpy before any blender_addon import that chains through runtime/__init__.py
if "bpy" not in sys.modules:
    sys.modules["bpy"] = types.SimpleNamespace()

# ---------------------------------------------------------------------------
# Minimal session stubs (no Blender / bpy required)
# ---------------------------------------------------------------------------

def _make_session(phase: str = "idle", pending_mutation=None):
    """Return a minimal session stub with execution_state."""
    es = SimpleNamespace(
        phase=phase,
        pending_mutation=pending_mutation,
        last_failure=None,
    )
    es.set_phase = lambda p: setattr(es, "phase", p)
    session = SimpleNamespace(
        execution_state=es,
        baseline_workspace=None,
        history=SimpleNamespace(messages=[]),
        focus=None,
    )
    session.clear_pending_mutation = lambda: setattr(es, "pending_mutation", None)
    return session


# ---------------------------------------------------------------------------
# StateMachine confirmation flow
# ---------------------------------------------------------------------------

from blender_addon.runtime.state_machine import StateMachine, InvalidTransitionError
from blender_addon.session.schema import Session


class TestStateMachineConfirmationFlow(unittest.TestCase):
    def setUp(self):
        self.sm = StateMachine()

    def _session(self):
        return Session()

    def test_idle_to_awaiting_via_propose(self):
        s = self._session()
        self.assertEqual(s.execution_state.phase, "idle")
        self.sm.propose_mutation(s)
        self.assertEqual(s.execution_state.phase, "awaiting_confirmation")

    def test_awaiting_to_executing_via_confirm(self):
        s = self._session()
        self.sm.propose_mutation(s)
        self.sm.confirm(s)
        self.assertEqual(s.execution_state.phase, "executing")

    def test_executing_to_idle_via_succeeded(self):
        s = self._session()
        self.sm.propose_mutation(s)
        self.sm.confirm(s)
        self.sm.mark_succeeded(s)
        self.assertEqual(s.execution_state.phase, "idle")

    def test_awaiting_to_idle_via_deny(self):
        s = self._session()
        self.sm.propose_mutation(s)
        self.sm.deny(s)
        self.assertEqual(s.execution_state.phase, "idle")

    def test_executing_to_failed_via_mark_failed(self):
        s = self._session()
        self.sm.propose_mutation(s)
        self.sm.confirm(s)
        self.sm.mark_failed(s)
        self.assertEqual(s.execution_state.phase, "failed")

    def test_failed_to_idle_via_reset(self):
        s = self._session()
        self.sm.propose_mutation(s)
        self.sm.confirm(s)
        self.sm.mark_failed(s)
        self.sm.reset(s)
        self.assertEqual(s.execution_state.phase, "idle")

    def test_invalid_transition_raises(self):
        s = self._session()
        # Cannot confirm without proposing first.
        with self.assertRaises(InvalidTransitionError):
            self.sm.confirm(s)

    def test_full_happy_path(self):
        """idle → propose → awaiting → confirm → executing → succeeded → idle."""
        s = self._session()
        phases = [s.execution_state.phase]
        self.sm.propose_mutation(s); phases.append(s.execution_state.phase)
        self.sm.confirm(s);         phases.append(s.execution_state.phase)
        self.sm.mark_succeeded(s);  phases.append(s.execution_state.phase)
        self.assertEqual(phases, ["idle", "awaiting_confirmation", "executing", "idle"])


# ---------------------------------------------------------------------------
# AgentRuntime._execute_tool — phase-based gate
# ---------------------------------------------------------------------------

def _make_runtime_stub(phase: str = "idle"):
    """Return a minimal AgentRuntime-like object that can run _execute_tool."""
    # Build a minimal runtime object using SimpleNamespace.
    runtime_stub = SimpleNamespace(
        v1_session_for=lambda *a, **kw: _make_session(phase=phase),
    )
    journal_stub = SimpleNamespace(
        log_runtime_event=MagicMock(),
        accumulate_tokens=MagicMock(),
    )
    session_store_stub = SimpleNamespace(
        save=MagicMock(),
        load=MagicMock(return_value={}),
        get_session_memory=MagicMock(return_value={}),
    )
    rt = SimpleNamespace(
        runtime=runtime_stub,
        journal=journal_stub,
        _session_state={},
        _tool_step=0,
        _current_turn_tools=[],
        _session_memory={},
        _structural_index={},
        _halt_execution=False,
        # In-memory session cache — previously read from disk via v1_session_for().
        # _execute_tool now reads phase from this instead, so stubs must supply it.
        _active_v1_session=_make_session(phase=phase),
        # Capture mode — set by mutation_request.handle() around its agent loop.
        # Default False so tests that simulate idle/awaiting still get BLOCKED.
        _capture_mode=False,
    )
    rt.runtime.state_adapter = session_store_stub
    # Attach the real method by binding it.
    from blender_addon.agent_runtime import AgentRuntime
    rt._execute_tool = AgentRuntime._execute_tool.__get__(rt, type(rt))
    rt._postprocess_tool = AgentRuntime._postprocess_tool.__get__(rt, type(rt))
    rt._update_operational_state_from_tool = AgentRuntime._update_operational_state_from_tool.__get__(rt, type(rt))
    rt._format_runtime_tool_result = AgentRuntime._format_runtime_tool_result
    return rt


class TestExecuteToolPhaseGate(unittest.TestCase):
    """Unit tests for AgentRuntime._execute_tool phase authorization."""

    def _patch_dispatch(self, result: str = '{"status": "ok"}'):
        """Patch dispatch_tool where it is used (agent_runtime).

        Phase 5: renamed dispatch_runtime_tool → dispatch_tool in agent_runtime.
        """
        runtime_raw = {"status": "success", "result": {"status": "ok"}}
        return patch(
            "blender_addon.agent_runtime.dispatch_tool",
            return_value=(runtime_raw, result, 10),
        )

    def _patch_screenshot(self, return_val=None):
        return patch(
            "blender_addon.agent_runtime.process_screenshot_result",
            return_value=return_val,
        )

    def test_read_tool_allowed_when_idle(self):
        """get_tree_structure is a read tool — allowed from any phase."""
        rt = _make_runtime_stub(phase="idle")
        with self._patch_dispatch("tree data") as mock_dispatch, \
             self._patch_screenshot():
            result = rt._execute_tool("get_tree_structure", {}, 0)
        self.assertEqual(result, "tree data")
        mock_dispatch.assert_called_once()

    def test_read_tool_allowed_when_awaiting(self):
        rt = _make_runtime_stub(phase="awaiting_confirmation")
        with self._patch_dispatch("tree data"), self._patch_screenshot():
            result = rt._execute_tool("get_tree_structure", {}, 0)
        self.assertNotIn("BLOCKED", result)

    def test_execute_code_allowed_when_idle(self):
        """execute_code has no phase gate — always dispatched regardless of phase."""
        rt = _make_runtime_stub(phase="idle")
        with self._patch_dispatch('{"output": "done"}') as mock_dispatch, \
             self._patch_screenshot():
            result = rt._execute_tool("execute_code", {"code": "pass"}, 0)
        mock_dispatch.assert_called_once()
        self.assertNotIn("BLOCKED", result)

    def test_execute_code_allowed_when_awaiting(self):
        """execute_code dispatches even when phase is awaiting_confirmation."""
        rt = _make_runtime_stub(phase="awaiting_confirmation")
        with self._patch_dispatch('{"output": "done"}') as mock_dispatch, \
             self._patch_screenshot():
            result = rt._execute_tool("execute_code", {"code": "pass"}, 0)
        mock_dispatch.assert_called_once()
        self.assertNotIn("BLOCKED", result)

    def test_execute_code_allowed_when_executing(self):
        rt = _make_runtime_stub(phase="executing")
        with self._patch_dispatch('{"output": "done"}') as mock_dispatch, \
             self._patch_screenshot():
            result = rt._execute_tool("execute_code", {"code": "pass"}, 0)
        mock_dispatch.assert_called_once()
        self.assertNotIn("BLOCKED", result)

    def test_other_mutation_tool_blocked_when_idle(self):
        """Non-execute_code mutation tools are still gated by phase / authorization."""
        rt = _make_runtime_stub(phase="idle")
        with self._patch_dispatch() as mock_dispatch, self._patch_screenshot():
            result = rt._execute_tool("create_node",
                                      {"tree_name": "T", "node_type": "X", "node_name": "N"}, 0)
        self.assertIn("BLOCKED", result)
        mock_dispatch.assert_not_called()

    def test_other_mutation_tool_allowed_when_executing(self):
        """Non-execute_code mutation tools are allowed in the executing phase."""
        rt = _make_runtime_stub(phase="executing")
        with self._patch_dispatch('{"ok": true}') as mock_dispatch, self._patch_screenshot():
            result = rt._execute_tool("create_node",
                                      {"tree_name": "T", "node_type": "X", "node_name": "N"}, 0)
        mock_dispatch.assert_called_once()
        self.assertNotIn("BLOCKED", result)

    def test_gate_logs_blocked_event_for_non_execute_code(self):
        """Blocked non-execute_code call must log 'execution_gate_blocked_phase'."""
        rt = _make_runtime_stub(phase="idle")
        with self._patch_dispatch(), self._patch_screenshot():
            rt._execute_tool("create_node",
                             {"tree_name": "T", "node_type": "X", "node_name": "N"}, 0)
        calls = [c.kwargs for c in rt.journal.log_runtime_event.call_args_list]
        blocked = [c for c in calls if c.get("event_type") == "execution_gate_blocked_phase"]
        self.assertTrue(blocked, "Expected execution_gate_blocked_phase event")

    def test_make_plan_allowed_when_idle(self):
        """make_plan is not in MUTATION_TOOLS so it is never gated."""
        rt = _make_runtime_stub(phase="idle")
        with self._patch_dispatch('{"plan": "ok"}') as mock_dispatch, \
             self._patch_screenshot():
            result = rt._execute_tool("make_plan", {"steps": []}, 0)
        mock_dispatch.assert_called_once()
        self.assertNotIn("BLOCKED", result)

    def test_executing_phase_allows_non_execute_code_tools(self):
        """The executing phase alone allows mutation tools."""
        rt = _make_runtime_stub(phase="executing")
        with self._patch_dispatch('{"output": "done"}') as mock_dispatch, \
             self._patch_screenshot():
            result = rt._execute_tool("connect_nodes",
                {"tree_name":"T","from_node":"A","from_socket":"s",
                 "to_node":"B","to_socket":"s"}, 0)
        mock_dispatch.assert_called_once()
        self.assertNotIn("BLOCKED", result)

    def test_capture_mode_stages_execute_code_instead_of_dispatching(self):
        """_capture_mode=True stages execute_code without dispatching to Blender."""
        rt = _make_runtime_stub(phase="idle")
        rt._capture_mode = True
        with self._patch_dispatch() as mock_dispatch, self._patch_screenshot():
            result = rt._execute_tool("execute_code", {"code": "import bpy"}, 0)
        self.assertNotIn("BLOCKED", result)
        self.assertIn("staged", result.lower())
        mock_dispatch.assert_not_called()
        staged = [t for t in rt._current_turn_tools if t.get("name") == "execute_code"]
        self.assertTrue(staged)
        self.assertEqual(staged[0]["input"]["code"], "import bpy")

    def test_capture_mode_stages_other_mutation_tools_too(self):
        """_capture_mode=True stages non-execute_code mutation tools (not BLOCKED)."""
        rt = _make_runtime_stub(phase="idle")
        rt._capture_mode = True
        with self._patch_dispatch() as mock_dispatch, self._patch_screenshot():
            result = rt._execute_tool("create_node",
                                      {"tree_name": "T", "node_type": "X", "node_name": "N"}, 0)
        self.assertNotIn("BLOCKED", result)
        self.assertIn("staged", result.lower())
        mock_dispatch.assert_not_called()


# ---------------------------------------------------------------------------
# Tombstone guards
# ---------------------------------------------------------------------------

class TestTombstoneGuards(unittest.TestCase):
    """Verify that deleted modules raise ImportError on any attribute access."""

    def test_execution_prechecks_raises(self):
        import blender_addon.execution_prechecks as ep
        with self.assertRaises(ImportError):
            _ = ep.ensure_mutation_approval_pre_dispatch

    def test_execution_prechecks_any_attr_raises(self):
        import blender_addon.execution_prechecks as ep
        with self.assertRaises(ImportError):
            _ = ep.ensure_always_plan_first

    def test_runtime_governance_raises(self):
        import blender_addon.runtime_governance as rg
        with self.assertRaises(ImportError):
            _ = rg.new_approval_token

    def test_runtime_governance_has_valid_raises(self):
        import blender_addon.runtime_governance as rg
        with self.assertRaises(ImportError):
            _ = rg.has_valid_current_approval


# ---------------------------------------------------------------------------
# TurnRouter phase gates — no regression
# ---------------------------------------------------------------------------

from blender_addon.runtime.router import TurnRouter, TurnClass


class TestTurnRouterPhaseGatesPhase4(unittest.TestCase):
    """Verify router still correctly gate-routes after Phase 4 changes."""

    def test_awaiting_yes_routes_mutation_confirmation(self):
        s = _make_session(phase="awaiting_confirmation")
        tc, meta = TurnRouter().classify(s, "yes")
        self.assertEqual(tc, TurnClass.MUTATION_CONFIRMATION)

    def test_awaiting_no_routes_mutation_denial(self):
        s = _make_session(phase="awaiting_confirmation")
        tc, meta = TurnRouter().classify(s, "no")
        self.assertEqual(tc, TurnClass.MUTATION_DENIAL)

    def test_failed_routes_post_failure_recovery(self):
        s = _make_session(phase="failed")
        tc, meta = TurnRouter().classify(s, "what happened?")
        self.assertEqual(tc, TurnClass.POST_FAILURE_RECOVERY)

    def test_awaiting_override_falls_through_to_mutation(self):
        """Non-yes/no input while awaiting_confirmation triggers override signal,
        then falls through to normal classification of the message."""
        s = _make_session(phase="awaiting_confirmation")
        tc, meta = TurnRouter().classify(s, "set scale to 2.0")
        # Signal should include override
        self.assertIn("awaiting_confirmation_override", meta.signals)
        # And the message itself classifies as mutation
        self.assertEqual(tc, TurnClass.MUTATION_REQUEST)

    def test_idle_mutation_request_routes_mutation(self):
        s = _make_session(phase="idle")
        tc, _ = TurnRouter().classify(s, "set value to 3.0")
        self.assertEqual(tc, TurnClass.MUTATION_REQUEST)

    def test_idle_question_routes_diagnosis(self):
        s = _make_session(phase="idle")
        tc, _ = TurnRouter().classify(s, "what nodes are in this tree?")
        self.assertEqual(tc, TurnClass.DIAGNOSIS)


if __name__ == "__main__":
    unittest.main()
