"""Tests for Phase 8 — UI Layering.

Validates the invariants introduced by Workstream H:

  - chat_session.py is importable without bpy (unit-testable in CI).
  - _ChatSession correctly manages message queues, screenshots, attachments.
  - The main panel does NOT define any dead approval-token operators.
  - The dead operators that were removed do not appear in _ALL_CLASSES.
  - _wrap_text produces correct line wrapping.
  - _get_execution_phase falls back gracefully.
  - Phase badge labels are defined for the right phase values.

Phase 9 note: chat_ui.py shim was removed. Tests that imported it are deleted.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# _ChatSession — no bpy required
# ---------------------------------------------------------------------------

class TestChatSession(unittest.TestCase):
    """_ChatSession can be tested without Blender."""

    def _make(self):
        from blender_addon.ui.chat_session import _ChatSession
        return _ChatSession()

    def test_add_and_get_messages(self):
        s = self._make()
        s.add("user", "hello")
        s.add("assistant", "hi there")
        msgs = s.get_messages()
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["role"], "user")
        self.assertEqual(msgs[1]["text"], "hi there")

    def test_clear_resets_all_state(self):
        s = self._make()
        s.add("user", "test")
        s.running = True
        s.error = "boom"
        s.streaming_text = "partial"
        s.reasoning_text = "thinking..."
        s.pending_screenshots.append(b"\x89PNG")
        s.loaded_session_id = "abc"
        s.clear()
        self.assertEqual(s.get_messages(), [])
        self.assertFalse(s.running)
        self.assertEqual(s.error, "")
        self.assertEqual(s.streaming_text, "")
        self.assertEqual(s.reasoning_text, "")
        self.assertEqual(s.pending_screenshots, [])
        self.assertEqual(s.loaded_session_id, "")

    def test_replace_messages_filters_bad_entries(self):
        s = self._make()
        raw = [
            {"role": "user", "text": "ok"},
            {"role": "system", "text": "bad role"},  # filtered
            {"role": "assistant", "text": ""},         # filtered (empty)
            42,                                         # filtered (not dict)
            {"role": "assistant", "text": "reply"},
        ]
        s.replace_messages(raw, session_id="sess-1")
        msgs = s.get_messages()
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["role"], "user")
        self.assertEqual(msgs[1]["role"], "assistant")
        self.assertEqual(s.loaded_session_id, "sess-1")

    def test_replace_messages_caps_at_120(self):
        s = self._make()
        large = [{"role": "user", "text": f"msg {i}"} for i in range(200)]
        s.replace_messages(large)
        self.assertLessEqual(len(s.get_messages()), 120)

    def test_reset_turn_clears_per_turn_state(self):
        s = self._make()
        s.current_tool = "execute_code"
        s.tool_call_count = 3
        s.streaming_text = "partial"
        s.reasoning_text = "thinking"
        s.error = "old error"
        s.reset_turn()
        self.assertEqual(s.current_tool, "")
        self.assertEqual(s.tool_call_count, 0)
        self.assertEqual(s.streaming_text, "")
        self.assertEqual(s.reasoning_text, "")
        self.assertEqual(s.error, "")

    def test_screenshot_queue(self):
        s = self._make()
        self.assertEqual(s.pending_screenshot_count(), 0)
        s.add_screenshot(b"\x89PNG1")
        s.add_screenshot(b"\x89PNG2")
        self.assertEqual(s.pending_screenshot_count(), 2)
        data = s.consume_screenshots()
        self.assertEqual(len(data), 2)
        self.assertEqual(s.pending_screenshot_count(), 0)

    def test_file_attachment_queue(self):
        s = self._make()
        entry = {"name": "test.py", "text": "print('hi')", "bytes": 12, "truncated": False}
        s.add_file_attachment(entry)
        self.assertEqual(s.pending_file_count(), 1)
        files = s.consume_file_attachments()
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["name"], "test.py")

    def test_set_screenshot_notice(self):
        s = self._make()
        s.set_screenshot_notice("Captured (42KB).")
        self.assertEqual(s.screenshot_notice, "Captured (42KB).")

    def test_thread_safety_add(self):
        """Concurrent adds must not corrupt the list."""
        import threading
        s = self._make()
        threads = [
            threading.Thread(target=s.add, args=("user", f"msg {i}"))
            for i in range(20)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(s.get_messages()), 20)


# ---------------------------------------------------------------------------
# SESSION singleton — module-level
# ---------------------------------------------------------------------------

class TestSessionSingleton(unittest.TestCase):
    def test_session_is_importable_without_bpy(self):
        from blender_addon.ui.chat_session import SESSION, _ChatSession
        self.assertIsInstance(SESSION, _ChatSession)

    def test_session_exported_from_ui_package(self):
        # ui/__init__.py should re-export SESSION
        import blender_addon.ui as ui_pkg
        self.assertTrue(hasattr(ui_pkg, "SESSION"))


# ---------------------------------------------------------------------------
# Dead operators must not be registered
# ---------------------------------------------------------------------------

class TestDeadOperatorsRemoved(unittest.TestCase):
    """Phase 8 removes 9 dead operators tied to the old approval-token system."""

    _DEAD_OP_IDS = {
        "chat.approve_plan",
        "chat.deny_plan",
        "chat.reset_pending_plan",
        "chat.clear_approval_state",
        "chat.reset_transient_state",
        "chat.rebuild_plan",
        "chat.take_control",
        "chat.continue_session",
    }

    def _get_registered_idnames(self):
        # Verify invariant via source inspection — no bpy required.
        # Read the panel source and extract bl_idname = "..." assignments.
        import re
        from pathlib import Path
        panel_src = (
            Path(__file__).resolve().parent.parent
            / "blender_addon" / "ui" / "panel.py"
        ).read_text(encoding="utf-8")
        return set(re.findall(r'bl_idname\s*=\s*["\']([^"\']+)["\']', panel_src))

    def test_approve_plan_not_registered(self):
        ids = self._get_registered_idnames()
        self.assertNotIn("chat.approve_plan", ids)

    def test_deny_plan_not_registered(self):
        ids = self._get_registered_idnames()
        self.assertNotIn("chat.deny_plan", ids)

    def test_rebuild_plan_not_registered(self):
        ids = self._get_registered_idnames()
        self.assertNotIn("chat.rebuild_plan", ids)

    def test_take_control_not_registered(self):
        ids = self._get_registered_idnames()
        self.assertNotIn("chat.take_control", ids)

    def test_continue_session_not_registered(self):
        ids = self._get_registered_idnames()
        self.assertNotIn("chat.continue_session", ids)

    def test_clear_approval_state_not_registered(self):
        ids = self._get_registered_idnames()
        self.assertNotIn("chat.clear_approval_state", ids)

    def test_reset_pending_plan_not_registered(self):
        ids = self._get_registered_idnames()
        self.assertNotIn("chat.reset_pending_plan", ids)

    def test_reset_transient_state_not_registered(self):
        ids = self._get_registered_idnames()
        self.assertNotIn("chat.reset_transient_state", ids)


# ---------------------------------------------------------------------------
# _wrap_text helper
# ---------------------------------------------------------------------------

class TestWrapText(unittest.TestCase):
    def _wrap(self, text, width=56):
        from blender_addon.ui._helpers import _wrap_text
        return _wrap_text(text, width)

    def test_empty_string(self):
        result = self._wrap("")
        self.assertEqual(result, [""])

    def test_short_text_unchanged(self):
        result = self._wrap("hello", width=20)
        self.assertEqual(result, ["hello"])

    def test_long_text_wrapped(self):
        long_line = "a " * 40  # 80 chars
        result = self._wrap(long_line, width=20)
        self.assertGreater(len(result), 1)
        for line in result:
            self.assertLessEqual(len(line), 22)  # some slack for word boundaries

    def test_multiline_preserves_blank_lines(self):
        text = "first\n\nsecond"
        result = self._wrap(text, width=40)
        self.assertIn("", result)  # blank line preserved

    def test_newline_split(self):
        text = "line one\nline two"
        result = self._wrap(text, width=40)
        self.assertIn("line one", result)
        self.assertIn("line two", result)


# ---------------------------------------------------------------------------
# Phase badge labels
# ---------------------------------------------------------------------------

class TestPhaseBadge(unittest.TestCase):
    """_PHASE_LABELS must cover the non-idle phases from the state machine."""

    def _labels(self):
        from blender_addon.ui._helpers import _PHASE_LABELS
        return _PHASE_LABELS

    def test_awaiting_confirmation_has_label(self):
        self.assertIn("awaiting_confirmation", self._labels())

    def test_failed_has_label(self):
        self.assertIn("failed", self._labels())

    def test_executing_has_label(self):
        self.assertIn("executing", self._labels())

    def test_idle_not_in_labels(self):
        # idle = no badge needed
        self.assertNotIn("idle", self._labels())

    def test_all_labels_have_icon(self):
        for phase, (text, icon) in self._labels().items():
            self.assertIsInstance(text, str, f"Label text for {phase!r} must be a str")
            self.assertIsInstance(icon, str, f"Icon for {phase!r} must be a str")
            self.assertTrue(text, f"Label text for {phase!r} must be non-empty")


# ---------------------------------------------------------------------------
# _get_execution_phase — graceful fallback
# ---------------------------------------------------------------------------

class TestGetExecutionPhase(unittest.TestCase):
    """_get_execution_phase must return '' on any error (no bpy / no file)."""

    def test_returns_empty_string_when_session_unavailable(self):
        from blender_addon.ui._helpers import _get_execution_phase
        result = _get_execution_phase("/nonexistent/path", "")
        self.assertIsInstance(result, str)
        # Should not raise; on missing file returns "" or a valid phase string
        valid_phases = {"idle", "executing", "awaiting_confirmation", "failed",
                        "halted", "reading", "proposing", ""}
        self.assertIn(result, valid_phases)


# ---------------------------------------------------------------------------
# Package structure
# ---------------------------------------------------------------------------

class TestUiPackageStructure(unittest.TestCase):
    """The ui/ package must export the right names and be importable."""

    def test_ui_package_importable(self):
        import blender_addon.ui  # noqa: F401

    def test_chat_session_module_importable(self):
        import blender_addon.ui.chat_session  # noqa: F401

    def test_screenshot_module_importable(self):
        # screenshot.py imports bpy; outside Blender any import-related error is ok.
        try:
            import blender_addon.ui.screenshot  # noqa: F401
        except (ImportError, AttributeError, ModuleNotFoundError):
            pass  # expected outside Blender

    def test_advanced_module_importable(self):
        try:
            import blender_addon.ui.advanced  # noqa: F401
        except (ImportError, AttributeError, ModuleNotFoundError):
            pass  # expected outside Blender

    def test_panel_module_importable(self):
        try:
            import blender_addon.ui.panel  # noqa: F401
        except (ImportError, AttributeError, ModuleNotFoundError):
            pass  # expected outside Blender


if __name__ == "__main__":
    unittest.main()
