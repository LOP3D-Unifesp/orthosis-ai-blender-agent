"""Tests for routing_obs session-state and shadow-handler helpers."""

from __future__ import annotations

import sys
import types
import unittest
from dataclasses import dataclass, field
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


@dataclass
class _FakeLastFailure:
    error: str = "AttributeError on line 42"


@dataclass
class _FakeDraft:
    block_name: str = "GN_Agent_Draft"
    description: str = "test draft"
    tree_name: str = "TestTree"
    version: int = 1


@dataclass
class _FakeExecutionState:
    phase: str = "idle"
    current_draft: Any = None
    draft_revision: int = 0
    last_executed_revision: int = 0
    last_execution_outcome: str = ""
    last_failure: Any = None
    retry_requires_draft_change: bool = False
    drafting_mode: bool = False
    draft_block_name: str = "GN_Agent_Draft"
    session_state: str = ""


@dataclass
class _FakeHistory:
    messages: list = field(default_factory=list)


@dataclass
class _FakeBaseline:
    stale: bool = True
    structural_summary: str = ""


@dataclass
class _FakeSession:
    execution_state: _FakeExecutionState = field(default_factory=_FakeExecutionState)
    history: _FakeHistory = field(default_factory=_FakeHistory)
    baseline_workspace: _FakeBaseline = field(default_factory=_FakeBaseline)


from blender_addon.runtime.routing_obs import (  # noqa: E402
    SESSION_STATES,
    compute_shadow_handler,
    infer_session_state,
)


class TestInferSessionState(unittest.TestCase):
    def test_idle_empty_session(self):
        s = _FakeSession()
        self.assertEqual(infer_session_state(s), "IDLE")

    def test_prefers_persisted_session_state(self):
        s = _FakeSession()
        s.execution_state.session_state = "REPAIRING"
        self.assertEqual(infer_session_state(s), "REPAIRING")

    def test_ignores_unknown_persisted_session_state(self):
        s = _FakeSession()
        s.execution_state.session_state = "UNKNOWN"
        self.assertEqual(infer_session_state(s), "IDLE")

    def test_exploring_reading_phase(self):
        s = _FakeSession()
        s.execution_state.phase = "reading"
        self.assertEqual(infer_session_state(s), "EXPLORING")

    def test_drafting_with_active_phase(self):
        s = _FakeSession()
        s.execution_state.phase = "drafting"
        self.assertEqual(infer_session_state(s), "DRAFTING")

    def test_pending_user_execution(self):
        s = _FakeSession()
        s.execution_state.current_draft = _FakeDraft()
        s.execution_state.draft_revision = 3
        s.execution_state.last_executed_revision = 2
        s.execution_state.last_execution_outcome = "success"
        self.assertEqual(infer_session_state(s), "PENDING_USER_EXECUTION")

    def test_repairing_retry_flag(self):
        s = _FakeSession()
        s.execution_state.retry_requires_draft_change = True
        self.assertEqual(infer_session_state(s), "REPAIRING")

    def test_repairing_failed_outcome(self):
        s = _FakeSession()
        s.execution_state.last_execution_outcome = "error"
        self.assertEqual(infer_session_state(s), "REPAIRING")

    def test_repairing_failed_phase(self):
        s = _FakeSession()
        s.execution_state.phase = "failed"
        self.assertEqual(infer_session_state(s), "REPAIRING")

    def test_repairing_last_failure_present(self):
        s = _FakeSession()
        s.execution_state.last_failure = _FakeLastFailure()
        self.assertEqual(infer_session_state(s), "REPAIRING")

    def test_resolved(self):
        s = _FakeSession()
        s.execution_state.current_draft = _FakeDraft()
        s.execution_state.draft_revision = 2
        s.execution_state.last_executed_revision = 2
        s.execution_state.last_execution_outcome = "success"
        self.assertEqual(infer_session_state(s), "RESOLVED")

    def test_all_states_are_known_labels(self):
        scenarios = [
            _FakeSession(),
            _FakeSession(execution_state=_FakeExecutionState(phase="reading")),
            _FakeSession(execution_state=_FakeExecutionState(phase="drafting")),
            _FakeSession(execution_state=_FakeExecutionState(retry_requires_draft_change=True)),
        ]
        for session in scenarios:
            result = infer_session_state(session)
            self.assertIn(result, SESSION_STATES)

    def test_no_mutation_on_session(self):
        s = _FakeSession()
        before_phase = s.execution_state.phase
        infer_session_state(s)
        self.assertEqual(s.execution_state.phase, before_phase)


class TestComputeShadowHandler(unittest.TestCase):
    def test_no_divergence_draft_workspace(self):
        result = compute_shadow_handler("draft_write", "DRAFTING", "draft_workspace")
        self.assertEqual(result, "draft_workspace")

    def test_no_divergence_pure_inquiry(self):
        result = compute_shadow_handler("pure_inquiry", "IDLE", "context_inquiry")
        self.assertEqual(result, "context_inquiry")

    def test_divergence_inquiry_then_write(self):
        result = compute_shadow_handler("inquiry_then_write", "DRAFTING", "context_inquiry")
        self.assertEqual(result, "draft_workspace")

    def test_divergence_draft_write_misrouted(self):
        result = compute_shadow_handler("draft_write", "IDLE", "context_inquiry")
        self.assertEqual(result, "draft_workspace")

    def test_divergence_feedback_fix(self):
        result = compute_shadow_handler("feedback_fix", "REPAIRING", "context_inquiry")
        self.assertEqual(result, "draft_workspace")

    def test_no_divergence_trivial_chat(self):
        result = compute_shadow_handler("trivial_chat", "IDLE", "trivial_chat")
        self.assertEqual(result, "trivial_chat")


if __name__ == "__main__":
    unittest.main()
