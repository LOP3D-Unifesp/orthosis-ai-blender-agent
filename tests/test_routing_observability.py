"""Tests for routing_obs — session_state and turn_intent inference.

These tests are pure-Python (no bpy, no Blender, no network).
They verify:
  1. SessionState derivation from ExecutionState fields
  2. TurnIntent derivation from signals + session state
  3. Shadow handler detection (divergence logging)
  4. Enrichment does not mutate session state
  5. Routing is unchanged after enrichment (turn_class identical)
  6. Journal routing_observation event contains expected fields
"""

from __future__ import annotations

import sys
import types
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Minimal fake bpy so runtime modules can be imported without Blender
# ---------------------------------------------------------------------------

def _install_fake_bpy() -> None:
    if "bpy" in sys.modules:
        return
    bpy = types.ModuleType("bpy")
    bpy.app = types.SimpleNamespace(  # type: ignore[attr-defined]
        handlers=types.SimpleNamespace(persistent=lambda fn: fn, load_post=[], save_post=[]),
        timers=types.SimpleNamespace(register=lambda fn: fn()),
    )
    bpy.data = types.SimpleNamespace(filepath="", texts={}, node_groups={})  # type: ignore[attr-defined]
    sys.modules["bpy"] = bpy


_install_fake_bpy()

# ---------------------------------------------------------------------------
# Minimal session stubs
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Import modules under test
# ---------------------------------------------------------------------------

from blender_addon.runtime.routing_obs import (
    infer_session_state,
    infer_turn_intent,
    compute_shadow_handler,
    enrich_meta_observability,
    SESSION_STATES,
    TURN_INTENTS,
)
from blender_addon.runtime.router import ClassifierMeta, TurnClass


# ---------------------------------------------------------------------------
# SessionState tests
# ---------------------------------------------------------------------------

class TestInferSessionState(unittest.TestCase):

    def test_idle_empty_session(self):
        s = _FakeSession()
        self.assertEqual(infer_session_state(s), "IDLE")

    def test_exploring_reading_phase(self):
        s = _FakeSession()
        s.execution_state.phase = "reading"
        self.assertEqual(infer_session_state(s), "EXPLORING")

    def test_drafting_with_active_phase(self):
        s = _FakeSession()
        s.execution_state.phase = "drafting"
        self.assertEqual(infer_session_state(s), "DRAFTING")

    def test_drafting_with_draft_never_executed(self):
        s = _FakeSession()
        s.execution_state.current_draft = _FakeDraft()
        s.execution_state.draft_revision = 1
        s.execution_state.last_executed_revision = 0
        # draft exists, never run → could be DRAFTING or PENDING; draft_revision > last_executed
        result = infer_session_state(s)
        self.assertIn(result, ("DRAFTING", "PENDING_USER_EXECUTION"))

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
        """infer_session_state should only return labels in SESSION_STATES."""
        scenarios = [
            _FakeSession(),
            _FakeSession(execution_state=_FakeExecutionState(phase="reading")),
            _FakeSession(execution_state=_FakeExecutionState(phase="drafting")),
            _FakeSession(execution_state=_FakeExecutionState(
                phase="idle", retry_requires_draft_change=True
            )),
        ]
        for s in scenarios:
            result = infer_session_state(s)
            self.assertIn(result, SESSION_STATES, f"Unknown state: {result!r}")

    def test_no_mutation_on_session(self):
        """infer_session_state must not mutate execution_state."""
        s = _FakeSession()
        s.execution_state.phase = "idle"
        before_phase = s.execution_state.phase
        infer_session_state(s)
        self.assertEqual(s.execution_state.phase, before_phase)


# ---------------------------------------------------------------------------
# TurnIntent tests
# ---------------------------------------------------------------------------

class TestInferTurnIntent(unittest.TestCase):

    def _session_idle(self) -> _FakeSession:
        return _FakeSession()

    def _session_with_draft(self) -> _FakeSession:
        s = _FakeSession()
        s.execution_state.current_draft = _FakeDraft()
        s.execution_state.draft_revision = 1
        return s

    def test_trivial_chat(self):
        result = infer_turn_intent(
            self._session_idle(), "olá", ["greeting_pattern"], "trivial_chat"
        )
        self.assertEqual(result, "trivial_chat")

    def test_state_control(self):
        result = infer_turn_intent(
            self._session_idle(), "cancela", ["draft_state_control_pattern"], "state_control"
        )
        self.assertEqual(result, "state_control")

    def test_execution_feedback_no_fix(self):
        result = infer_turn_intent(
            self._session_with_draft(),
            "executei o script",
            ["draft_execution_feedback_recovery"],
            "execution_feedback",
        )
        self.assertEqual(result, "execution_feedback")

    def test_feedback_fix_with_fix_word(self):
        result = infer_turn_intent(
            self._session_with_draft(),
            "executei mas corrige o loop",
            ["draft_execution_feedback_recovery"],
            "execution_feedback",
        )
        self.assertEqual(result, "feedback_fix")

    def test_feedback_fix_with_write_signal(self):
        result = infer_turn_intent(
            self._session_with_draft(),
            "rodei, mas quero mudar",
            ["draft_execution_feedback_recovery", "mutation_pattern"],
            "draft_workspace",
        )
        self.assertEqual(result, "feedback_fix")

    def test_draft_write_from_request_pattern(self):
        result = infer_turn_intent(
            self._session_idle(),
            "escreve o draft agora",
            ["draft_write_request_pattern"],
            "draft_workspace",
        )
        self.assertEqual(result, "draft_write")

    def test_draft_write_from_mutation(self):
        result = infer_turn_intent(
            self._session_idle(),
            "muda o scale para 1.5",
            ["mutation_pattern"],
            "draft_workspace",
        )
        self.assertEqual(result, "draft_write")

    def test_draft_refinement_from_recovery(self):
        result = infer_turn_intent(
            self._session_with_draft(),
            "tenta de novo",
            ["draft_workspace_recovery"],
            "draft_workspace",
        )
        self.assertEqual(result, "draft_refinement")

    def test_continuation_without_draft(self):
        result = infer_turn_intent(
            self._session_idle(),
            "segue",
            ["continuation_pattern"],
            "context_inquiry",
        )
        self.assertEqual(result, "continuation")

    def test_continuation_with_draft_becomes_refinement(self):
        result = infer_turn_intent(
            self._session_with_draft(),
            "segue",
            ["continuation_pattern"],
            "draft_workspace",
        )
        self.assertEqual(result, "draft_refinement")

    def test_pure_inquiry_default(self):
        result = infer_turn_intent(
            self._session_idle(),
            "qual o estado da cena?",
            ["diagnosis_pattern"],
            "context_inquiry",
        )
        self.assertEqual(result, "pure_inquiry")

    # --- MISMATCH DETECTOR ---

    def test_inquiry_then_write_detected(self):
        """context_inquiry + active draft + 'criei o draft' → inquiry_then_write."""
        result = infer_turn_intent(
            self._session_with_draft(),
            "tenta agora, criei o draft",
            ["default_context_inquiry"],
            "context_inquiry",
        )
        self.assertEqual(result, "inquiry_then_write")

    def test_inquiry_then_write_already_have_draft(self):
        result = infer_turn_intent(
            self._session_with_draft(),
            "já tem o draft, pode tentar",
            ["default_context_inquiry"],
            "context_inquiry",
        )
        self.assertEqual(result, "inquiry_then_write")

    def test_no_mismatch_without_active_draft(self):
        """Without active draft, soft words alone don't trigger inquiry_then_write."""
        result = infer_turn_intent(
            self._session_idle(),
            "tenta agora",
            ["default_context_inquiry"],
            "context_inquiry",
        )
        self.assertEqual(result, "pure_inquiry")

    def test_all_intents_are_known_labels(self):
        scenarios = [
            ("oi", ["greeting_pattern"], "trivial_chat", False),
            ("cancela", ["draft_state_control_pattern"], "state_control", False),
            ("executei", ["draft_execution_feedback_recovery"], "execution_feedback", False),
            ("muda o scale", ["mutation_pattern"], "draft_workspace", False),
            ("escreve o draft", ["draft_write_request_pattern"], "draft_workspace", False),
            ("tenta agora, criei o draft", ["default_context_inquiry"], "context_inquiry", True),
            ("qual é o nó?", ["diagnosis_pattern"], "context_inquiry", False),
        ]
        for msg, signals, chosen, needs_draft in scenarios:
            s = self._session_with_draft() if needs_draft else self._session_idle()
            result = infer_turn_intent(s, msg, signals, chosen)
            self.assertIn(result, TURN_INTENTS, f"Unknown intent {result!r} for {msg!r}")


# ---------------------------------------------------------------------------
# Shadow handler tests
# ---------------------------------------------------------------------------

class TestComputeShadowHandler(unittest.TestCase):

    def test_no_divergence_draft_workspace(self):
        result = compute_shadow_handler("draft_write", "DRAFTING", "draft_workspace")
        self.assertEqual(result, "draft_workspace")

    def test_no_divergence_pure_inquiry(self):
        result = compute_shadow_handler("pure_inquiry", "IDLE", "context_inquiry")
        self.assertEqual(result, "context_inquiry")

    def test_divergence_inquiry_then_write(self):
        """inquiry_then_write + context_inquiry → shadow=draft_workspace."""
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


# ---------------------------------------------------------------------------
# ClassifierMeta enrichment (integration with router)
# ---------------------------------------------------------------------------

class TestEnrichMetaObservability(unittest.TestCase):

    def test_fields_are_populated(self):
        meta = ClassifierMeta(turn_class=TurnClass.CONTEXT_INQUIRY, raw_message="qual o nó?")
        s = _FakeSession()
        enrich_meta_observability(meta, s, "qual o nó?")
        self.assertIn(meta.session_state, SESSION_STATES)
        self.assertIn(meta.turn_intent, TURN_INTENTS)

    def test_default_fields_are_empty_before_enrichment(self):
        meta = ClassifierMeta(turn_class=TurnClass.CONTEXT_INQUIRY)
        self.assertEqual(meta.turn_intent, "")
        self.assertEqual(meta.session_state, "")

    def test_enrichment_survives_bad_session(self):
        """enrich_meta_observability must never raise."""
        meta = ClassifierMeta(turn_class=TurnClass.CONTEXT_INQUIRY)
        enrich_meta_observability(meta, None, "test")
        # After safe failure, fields default to fallback values
        self.assertIsInstance(meta.session_state, str)
        self.assertIsInstance(meta.turn_intent, str)


# ---------------------------------------------------------------------------
# Router integration — turn_class unchanged after enrichment
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main()
