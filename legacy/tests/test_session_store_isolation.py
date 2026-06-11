"""Tests for SessionV1Store session isolation across blend files.

Verifies the fix for the ghost-history bug: opening a new .blend file must
NOT show the history of a previously active session stored in session.json.
"""

from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Minimal fake bpy
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_legacy_session_payload(blend_path: str, history_text: str) -> dict:
    """Create a minimal legacy flat-dict session payload with one history entry.

    Uses "chat_history" key — the field name expected by migrate_legacy_state
    → _build_history_from_legacy.
    """
    return {
        "schema_version": "0.2",
        "blend_path": blend_path,
        "agent_session_active": True,
        "chat_history": [
            {"role": "user", "text": history_text},
            {"role": "assistant", "text": "Resposta de teste."},
        ],
    }


def _make_v1_session_payload(blend_path: str, history_text: str) -> dict:
    """Create a minimal V1 structured session payload."""
    from blender_addon.session.schema import (
        Session, History, HistoryMessage, Identity, Focus,
        Lifecycle, ExecutionState, BaselineWorkspace, UIState,
        OperationalState, utc_now_iso, new_session_id, new_continuity_token,
        compute_focus_signature,
    )
    sess = Session.new(blend_path=blend_path)
    sess.history.messages.append(
        HistoryMessage(role="user", content=history_text)
    )
    sess.history.messages.append(
        HistoryMessage(role="assistant", content="Resposta V1.")
    )
    return sess.to_dict()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSessionIsolation(unittest.TestCase):
    """session.json from file A must not contaminate the panel for file B."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _store(self):
        from blender_addon.session.store import SessionV1Store
        return SessionV1Store(project_root=self.project_root)

    def _write_legacy_session_json(self, payload: dict) -> Path:
        legacy_dir = self.project_root / "runtime" / "sessions"
        legacy_dir.mkdir(parents=True, exist_ok=True)
        path = legacy_dir / "session.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_new_blend_does_not_load_legacy_session_json(self):
        """Opening a new blend file must return empty history, not session.json content."""
        self._write_legacy_session_json(
            _make_legacy_session_payload("/old/project.blend", "Histórico do arquivo antigo")
        )

        store = self._store()
        session = store.load("/new/project.blend")

        messages = session.history.messages
        self.assertEqual(len(messages), 0,
            "New blend file must start with empty history, not inherit session.json")

    def test_new_blend_without_any_prior_session(self):
        """load() with a never-seen blend path returns a fresh session."""
        store = self._store()
        session = store.load("/totally/new/file.blend")
        self.assertEqual(len(session.history.messages), 0)
        # blend_path should be set on the new session
        self.assertIn("new", session.focus.blend_path.replace("\\", "/"))

    def test_legacy_session_json_still_used_when_blend_path_empty(self):
        """When blend_path is empty (Blender unsaved), session.json is still the fallback."""
        self._write_legacy_session_json(
            _make_legacy_session_payload("", "Histórico sem arquivo")
        )

        store = self._store()
        session = store.load("")

        messages = session.history.messages
        self.assertGreater(len(messages), 0,
            "With no blend_path, session.json should still be loaded as fallback")

    def test_correct_v1_session_loaded_when_exists(self):
        """When a per-file V1 session exists, it is loaded (not session.json)."""
        import hashlib
        blend_path = str(Path("/my/ortese.blend").resolve())
        normalized = Path(blend_path).resolve().as_posix().lower()
        h = hashlib.md5(normalized.encode("utf-8")).hexdigest()[:8]

        # Write the correct V1 session
        v1_dir = self.project_root / "runtime" / "sessions_v1"
        v1_dir.mkdir(parents=True, exist_ok=True)
        v1_file = v1_dir / f"session_{h}.json"
        v1_file.write_text(
            json.dumps(_make_v1_session_payload(blend_path, "Histórico correto do arquivo")),
            encoding="utf-8",
        )

        # Write a conflicting session.json with different content
        self._write_legacy_session_json(
            _make_legacy_session_payload("/other/file.blend", "Histórico de outro arquivo")
        )

        store = self._store()
        session = store.load(blend_path)

        messages = session.history.messages
        self.assertGreater(len(messages), 0)
        # Should have loaded from V1, not from session.json
        user_msgs = [m.content for m in messages if m.role == "user"]
        self.assertTrue(
            any("correto" in t for t in user_msgs),
            f"Expected V1 history, got: {user_msgs}"
        )

    def test_no_cross_contamination_between_two_blend_files(self):
        """Sessions for two different blend files are independent."""
        import hashlib

        blend_a = str(Path("/projects/ortese_a.blend").resolve())
        blend_b = str(Path("/projects/ortese_b.blend").resolve())

        # Write V1 session for file A only
        v1_dir = self.project_root / "runtime" / "sessions_v1"
        v1_dir.mkdir(parents=True, exist_ok=True)

        norm_a = Path(blend_a).resolve().as_posix().lower()
        h_a = hashlib.md5(norm_a.encode("utf-8")).hexdigest()[:8]
        (v1_dir / f"session_{h_a}.json").write_text(
            json.dumps(_make_v1_session_payload(blend_a, "Mensagem do arquivo A")),
            encoding="utf-8",
        )

        store = self._store()

        # File A should have history
        session_a = store.load(blend_a)
        msgs_a = [m.content for m in session_a.history.messages if m.role == "user"]
        self.assertTrue(any("arquivo A" in t for t in msgs_a))

        # File B (never opened before) should have NO history
        session_b = store.load(blend_b)
        self.assertEqual(len(session_b.history.messages), 0,
            "File B must not inherit file A's history")


if __name__ == "__main__":
    unittest.main()
