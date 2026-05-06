"""Tests for Phase 9 — MCP Decision and Final Cleanup.

Validates the invariants introduced by Phase 9:

  - UIState.session_active field exists and serialises correctly.
  - migrate_legacy_state() maps agent_session_active → ui_state.session_active.
  - V1 session_active round-trips through to_dict/from_dict.
  - blender_addon.chat_ui shim is gone (ImportError expected).
  - blender_addon.__init__ imports from .ui directly.
  - Dead MCP tools are absent from server.py source.
  - server.py _compact_runtime_overview has no dead approval/plan fields.
"""

from __future__ import annotations

import unittest


# ---------------------------------------------------------------------------
# UIState.session_active schema
# ---------------------------------------------------------------------------

class TestUIStateSessionActive(unittest.TestCase):
    """UIState.session_active was added in Phase 9."""

    def _make(self, **kwargs):
        from blender_addon.session.schema import UIState
        return UIState(**kwargs)

    def test_field_exists_and_defaults_false(self):
        ui = self._make()
        self.assertFalse(ui.session_active)

    def test_can_set_true(self):
        ui = self._make(session_active=True)
        self.assertTrue(ui.session_active)

    def test_to_dict_includes_session_active(self):
        ui = self._make(session_active=True)
        d = ui.to_dict()
        self.assertIn("session_active", d)
        self.assertTrue(d["session_active"])

    def test_to_dict_false_case(self):
        ui = self._make(session_active=False)
        d = ui.to_dict()
        self.assertFalse(d["session_active"])

    def test_from_dict_reads_session_active(self):
        from blender_addon.session.schema import UIState
        d = {"session_active": True, "debug_mode": False}
        ui = UIState.from_dict(d)
        self.assertTrue(ui.session_active)

    def test_from_dict_defaults_to_false_when_absent(self):
        from blender_addon.session.schema import UIState
        ui = UIState.from_dict({})
        self.assertFalse(ui.session_active)

    def test_round_trip(self):
        from blender_addon.session.schema import UIState
        original = UIState(session_active=True, debug_mode=True)
        restored = UIState.from_dict(original.to_dict())
        self.assertTrue(restored.session_active)
        self.assertTrue(restored.debug_mode)


# ---------------------------------------------------------------------------
# migrate_legacy_state: agent_session_active → ui_state.session_active
# ---------------------------------------------------------------------------

class TestMigrateLegacySessionActive(unittest.TestCase):
    """migrate_legacy_state() must carry agent_session_active into ui_state."""

    def _migrate(self, legacy: dict):
        from blender_addon.session.store import migrate_legacy_state
        return migrate_legacy_state(legacy)

    def test_active_session_migrates(self):
        session = self._migrate({"agent_session_active": True, "session_id": "s-abc"})
        self.assertTrue(session.ui_state.session_active)

    def test_inactive_session_migrates(self):
        session = self._migrate({"agent_session_active": False, "session_id": "s-abc"})
        self.assertFalse(session.ui_state.session_active)

    def test_absent_field_defaults_false(self):
        session = self._migrate({"session_id": "s-abc"})
        self.assertFalse(session.ui_state.session_active)

    def test_other_ui_fields_still_migrate(self):
        session = self._migrate({
            "agent_session_active": True,
            "debug_mode": True,
            "mcp_write_enabled": True,
            "explicit_override_mode": True,
        })
        self.assertTrue(session.ui_state.session_active)
        self.assertTrue(session.ui_state.debug_mode)
        self.assertTrue(session.ui_state.mcp_write_enabled)
        self.assertTrue(session.ui_state.explicit_override_mode)


# ---------------------------------------------------------------------------
# Session V1 store round-trip
# ---------------------------------------------------------------------------

class TestSessionV1RoundTrip(unittest.TestCase):
    """Session.to_dict() / Session.from_dict() must preserve session_active."""

    def test_session_active_survives_round_trip(self):
        from blender_addon.session.schema import Session
        s = Session.new("test.blend")
        s.ui_state.session_active = True
        restored = Session.from_dict(s.to_dict())
        self.assertTrue(restored.ui_state.session_active)

    def test_session_active_false_survives_round_trip(self):
        from blender_addon.session.schema import Session
        s = Session.new("test.blend")
        s.ui_state.session_active = False
        restored = Session.from_dict(s.to_dict())
        self.assertFalse(restored.ui_state.session_active)

    def test_session_active_present_in_serialised_dict(self):
        from blender_addon.session.schema import Session
        s = Session.new("test.blend")
        s.ui_state.session_active = True
        d = s.to_dict()
        self.assertIn("session_active", d["ui_state"])
        self.assertTrue(d["ui_state"]["session_active"])


# ---------------------------------------------------------------------------
# chat_ui.py shim removed — must not be importable
# ---------------------------------------------------------------------------

class TestChatUiShimRemoved(unittest.TestCase):
    """Phase 9 removes the chat_ui.py backward-compat shim."""

    def test_chat_ui_not_importable(self):
        import importlib
        try:
            importlib.import_module("blender_addon.chat_ui")
            self.fail("blender_addon.chat_ui should not be importable after Phase 9")
        except (ImportError, ModuleNotFoundError):
            pass  # expected

    def test_ui_package_still_exports_session(self):
        import blender_addon.ui as ui_pkg
        self.assertTrue(hasattr(ui_pkg, "SESSION"))

    def test_session_importable_from_chat_session(self):
        from blender_addon.ui.chat_session import SESSION, _ChatSession
        self.assertIsInstance(SESSION, _ChatSession)


# ---------------------------------------------------------------------------
# MCP server.py dead-tool verification (source inspection)
# ---------------------------------------------------------------------------

class TestMcpDeadToolsRemoved(unittest.TestCase):
    """Phase 9 removes approval/plan tools that were dead since Phases 3-5."""

    _DEAD_TOOLS = {
        "approve_current_plan",
        "deny_current_plan",
        "get_pending_plan",
        "clear_pending_plan",
        "clear_approval_state",
        "reset_transient_runtime_state",
        "rebuild_pending_plan",
    }

    def _server_src(self) -> str:
        from pathlib import Path
        return (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")

    def test_approve_current_plan_absent(self):
        self.assertNotIn("def approve_current_plan", self._server_src())

    def test_deny_current_plan_absent(self):
        self.assertNotIn("def deny_current_plan", self._server_src())

    def test_get_pending_plan_absent(self):
        self.assertNotIn("def get_pending_plan", self._server_src())

    def test_clear_pending_plan_absent(self):
        self.assertNotIn("def clear_pending_plan", self._server_src())

    def test_clear_approval_state_absent(self):
        self.assertNotIn("def clear_approval_state", self._server_src())

    def test_reset_transient_absent(self):
        self.assertNotIn("def reset_transient_runtime_state", self._server_src())

    def test_rebuild_pending_plan_absent(self):
        self.assertNotIn("def rebuild_pending_plan", self._server_src())

    def test_compact_pending_plan_helper_absent(self):
        self.assertNotIn("def _compact_pending_plan", self._server_src())


# ---------------------------------------------------------------------------
# MCP _compact_runtime_overview has no dead fields
# ---------------------------------------------------------------------------

class TestMcpCompactOverviewClean(unittest.TestCase):
    """_compact_runtime_overview() must not reference deleted plan/approval fields."""

    def _overview_return_src(self) -> str:
        """Return only the return-dict body of _compact_runtime_overview()."""
        from pathlib import Path
        import re
        src = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")
        # Find the return { ... } block inside _compact_runtime_overview
        match = re.search(
            r"def _compact_runtime_overview\(.*?return \{(.*?)\}",
            src, re.DOTALL
        )
        return match.group(1) if match else ""

    def test_no_current_plan_id(self):
        self.assertNotIn("current_plan_id", self._overview_return_src())

    def test_no_presented_plan_fields(self):
        self.assertNotIn("presented_plan", self._overview_return_src())

    def test_no_approval_required(self):
        self.assertNotIn("approval_required", self._overview_return_src())

    def test_no_approval_status(self):
        self.assertNotIn('"approval_status"', self._overview_return_src())


# ---------------------------------------------------------------------------
# init imports from .ui directly (no chat_ui import)
# ---------------------------------------------------------------------------

class TestInitImportsFromUi(unittest.TestCase):
    """blender_addon/__init__.py must import from .ui, not .chat_ui."""

    def _init_src(self) -> str:
        from pathlib import Path
        return (
            Path(__file__).resolve().parent.parent / "blender_addon" / "__init__.py"
        ).read_text(encoding="utf-8")

    def test_no_chat_ui_import(self):
        self.assertNotIn("chat_ui", self._init_src())

    def test_imports_ui_package(self):
        self.assertIn("from . import ui", self._init_src())


if __name__ == "__main__":
    unittest.main()
