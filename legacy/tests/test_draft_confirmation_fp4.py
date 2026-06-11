"""Smoke tests for FP4: draft confirmation short-circuit in fast_path.py.

Product contract:
  A bare short confirmation ("sim", "ok", ...) when a confirmed-write action
  is pending MUST return the draft location for manual execution without
  calling prepare_draft_context or the LLM.

  The short-circuit must NOT fire when:
  - The message contains new instructions, error reports, or scene-read scope
  - There is no pending draft action
  - The session phase is failed/halted
  - No draft evidence exists in the session
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

# Stub bpy before any blender_addon import
_bpy = types.ModuleType("bpy")
_bpy.data = types.SimpleNamespace(filepath="", texts={}, node_groups={})
_bpy.app = types.SimpleNamespace(
    handlers=types.SimpleNamespace(persistent=lambda f: f, load_post=[], save_post=[]),
    timers=types.SimpleNamespace(register=lambda f: f()),
)
sys.modules.setdefault("bpy", _bpy)

from blender_addon.fast_path import _try_draft_confirmation  # noqa: E402


# ---------------------------------------------------------------------------
# Minimal session stub
# ---------------------------------------------------------------------------

@dataclass
class _DraftStub:
    block_name: str = "GN_Agent_Draft"
    version: int = 3
    last_written_chars: int = 1200


@dataclass
class _ExecStateStub:
    phase: str = "drafting"
    pending_draft_action: str = "write_confirmed_draft_revision"
    pending_draft_prompt: str = "previous proposal text"
    current_draft: Any = field(default_factory=_DraftStub)
    draft_block_name: str = "GN_Agent_Draft"
    draft_revision: int = 3
    last_saved_char_count: int = 1200


@dataclass
class _SessionStub:
    execution_state: _ExecStateStub = field(default_factory=_ExecStateStub)


def _make_session(**overrides) -> _SessionStub:
    es = _ExecStateStub(**overrides)
    return _SessionStub(execution_state=es)


# ---------------------------------------------------------------------------
# Tests: short-circuit FIRES
# ---------------------------------------------------------------------------

class TestFP4Fires(unittest.TestCase):
    """FP4 must fire for all canonical short confirmations."""

    def _assert_fires(self, msg: str, **session_overrides):
        session = _make_session(**session_overrides)
        result = _try_draft_confirmation(msg, session)
        self.assertIsNotNone(result, f"Expected FP4 to fire for {msg!r}")
        text, meta = result
        self.assertEqual(meta["fp_type"], "draft_confirmation")
        self.assertIn("GN_Agent_Draft", text)
        self.assertIn("manualmente", text)
        self.assertIn("relat", text)
        return text, meta, session

    def test_sim(self):
        self._assert_fires("sim")

    def test_ok(self):
        self._assert_fires("ok")

    def test_pode(self):
        self._assert_fires("pode")

    def test_vai(self):
        self._assert_fires("vai")

    def test_bora(self):
        self._assert_fires("bora")

    def test_claro(self):
        self._assert_fires("claro")

    def test_manda(self):
        self._assert_fires("manda")

    def test_yes(self):
        self._assert_fires("yes")

    def test_sure(self):
        self._assert_fires("sure")

    def test_go_ahead(self):
        self._assert_fires("go ahead")

    def test_with_trailing_exclamation(self):
        self._assert_fires("sim!")

    def test_clears_pending_action(self):
        _, _, session = self._assert_fires("sim")
        self.assertEqual(session.execution_state.pending_draft_action, "")
        self.assertEqual(session.execution_state.pending_draft_prompt, "")

    def test_response_includes_version(self):
        text, meta, _ = self._assert_fires("sim")
        self.assertEqual(meta["version"], 3)
        self.assertIn("revisão 3", text)

    def test_response_includes_char_count(self):
        text, _, _ = self._assert_fires("sim")
        self.assertIn("1200 chars", text)

    def test_draft_revision_without_current_draft_object(self):
        """draft_revision > 0 is sufficient evidence even without current_draft."""
        session = _make_session(current_draft=None, draft_revision=2)
        result = _try_draft_confirmation("sim", session)
        self.assertIsNotNone(result)
        _, meta = result
        self.assertEqual(meta["version"], 2)


# ---------------------------------------------------------------------------
# Tests: short-circuit DOES NOT fire (falls through)
# ---------------------------------------------------------------------------

class TestFP4FallThrough(unittest.TestCase):
    """FP4 must NOT fire in any of these cases."""

    def _assert_fallthrough(self, msg: str, **session_overrides):
        session = _make_session(**session_overrides)
        result = _try_draft_confirmation(msg, session)
        self.assertIsNone(result, f"Expected FP4 to fall through for {msg!r}")

    # --- Condition: pending_draft_action must be set ---

    def test_no_pending_action(self):
        self._assert_fallthrough("sim", pending_draft_action="")

    def test_different_pending_action(self):
        self._assert_fallthrough("sim", pending_draft_action="some_other_action")

    # --- Condition: phase must be "drafting" ---

    def test_phase_failed(self):
        self._assert_fallthrough("sim", phase="failed")

    def test_phase_halted(self):
        self._assert_fallthrough("sim", phase="halted")

    def test_phase_idle(self):
        self._assert_fallthrough("sim", phase="idle")

    def test_phase_executing(self):
        self._assert_fallthrough("sim", phase="executing")

    # --- Condition: message must be bare confirmation ---

    def test_confirmation_with_new_constraint(self):
        self._assert_fallthrough("sim, mas muda o valor para 0.5")

    def test_confirmation_with_correction_verb(self):
        self._assert_fallthrough("sim, só que ajusta a escala primeiro")

    def test_confirmation_with_expansion_verb(self):
        self._assert_fallthrough("sim, e também adiciona um nó de rotação")

    def test_error_report(self):
        self._assert_fallthrough("sim mas deu erro")

    def test_error_report_explicit(self):
        self._assert_fallthrough("sim, mas falhou")

    def test_diagnosis_question(self):
        self._assert_fallthrough("sim, por que não apareceu nada?")

    def test_scene_scope(self):
        self._assert_fallthrough("sim, mostra a árvore depois")

    def test_long_message_with_instructions(self):
        self._assert_fallthrough(
            "sim, mas faz isso na curva da direita e corrige o offset"
        )

    def test_retry_request_not_confirmation(self):
        # "tenta de novo" is a retry, not a bare confirmation
        self._assert_fallthrough("tenta de novo")

    def test_success_report_with_next_step(self):
        # "funcionou, agora organiza a árvore" → not a bare confirmation
        self._assert_fallthrough("funcionou, agora organiza a árvore")

    # --- Condition: draft evidence must exist ---

    def test_no_draft_no_revision(self):
        session = _make_session(current_draft=None, draft_revision=0)
        result = _try_draft_confirmation("sim", session)
        self.assertIsNone(result)

    # --- Condition: no execution_state at all ---

    def test_session_without_execution_state(self):
        session = types.SimpleNamespace()  # no execution_state
        result = _try_draft_confirmation("sim", session)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
