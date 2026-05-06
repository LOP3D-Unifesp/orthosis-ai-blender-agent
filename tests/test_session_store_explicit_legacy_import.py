from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


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


def _write_v1_session(project_root: Path, blend_path: str, user_text: str, *, last_active_at: str = "") -> Path:
    from blender_addon.session.schema import HistoryMessage, Session, utc_now_iso
    from blender_addon.session.store import SessionV1Store

    store = SessionV1Store(project_root=project_root)
    session = Session.new(blend_path=blend_path)
    session.history.messages.append(HistoryMessage(role="user", content=user_text))
    session.history.messages.append(HistoryMessage(role="assistant", content="assistant"))
    if last_active_at:
        session.identity.last_active_at = last_active_at
    else:
        session.identity.last_active_at = utc_now_iso()
    path = store.v1_path(blend_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(session.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _write_legacy_flat_session(project_root: Path, blend_path: str, user_text: str, *, updated_at: str = "") -> Path:
    legacy_dir = project_root / "runtime" / "sessions"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "0.2",
        "blend_path": blend_path,
        "session_id": "legacy-session",
        "updated_at": updated_at or "2026-04-26T00:00:00+00:00",
        "chat_history": [
            {"role": "user", "text": user_text},
            {"role": "assistant", "text": "assistant"},
        ],
    }
    path = legacy_dir / "session_legacy.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


class SessionStoreExplicitLegacyImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace_root = Path(self._tmp.name)
        self.project_root = self.workspace_root / "blend_IA_ort_v2"
        self.legacy_root = self.workspace_root / "blend_IA_ort"
        self.project_root.mkdir(parents=True, exist_ok=True)
        self.legacy_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _store(self):
        from blender_addon.session.store import SessionV1Store

        return SessionV1Store(project_root=self.project_root)

    def test_load_does_not_call_import_session_files(self):
        blend_path = str((self.project_root / "demo.blend").resolve())
        _write_v1_session(self.legacy_root, blend_path, "legacy only")

        store = self._store()
        with patch("blender_addon.session.store.import_session_files") as import_mock:
            session = store.load(blend_path)

        import_mock.assert_not_called()
        self.assertEqual(len(session.history.messages), 0)

    def test_existing_v1_is_not_overwritten_by_legacy_during_load(self):
        blend_path = str((self.project_root / "current.blend").resolve())
        current_path = _write_v1_session(
            self.project_root,
            blend_path,
            "CURRENT SESSION",
            last_active_at="2026-04-20T00:00:00+00:00",
        )
        before = current_path.read_text(encoding="utf-8")

        _write_v1_session(
            self.legacy_root,
            blend_path,
            "LEGACY SESSION SHOULD NOT WIN",
            last_active_at="2026-04-26T00:00:00+00:00",
        )

        store = self._store()
        session = store.load(blend_path)

        user_messages = [msg.content for msg in session.history.messages if msg.role == "user"]
        self.assertIn("CURRENT SESSION", user_messages)
        self.assertNotIn("LEGACY SESSION SHOULD NOT WIN", user_messages)
        self.assertEqual(current_path.read_text(encoding="utf-8"), before)

    def test_missing_v1_returns_empty_session_without_implicit_legacy_import(self):
        blend_path = str((self.project_root / "missing.blend").resolve())
        _write_v1_session(self.legacy_root, blend_path, "legacy candidate")
        _write_legacy_flat_session(self.legacy_root, blend_path, "legacy flat candidate")

        store = self._store()
        session = store.load(blend_path)

        self.assertEqual(len(session.history.messages), 0)
        self.assertEqual(session.focus.blend_path, blend_path)
        self.assertFalse(store.v1_path(blend_path).exists())

    def test_explicit_legacy_import_can_still_be_called_manually(self):
        blend_path = str((self.project_root / "manual-import.blend").resolve())
        _write_v1_session(self.legacy_root, blend_path, "legacy imported manually")

        store = self._store()
        imported = store.import_legacy_sessions_explicit(blend_path)

        self.assertEqual(imported, [store.v1_path(blend_path)])
        session = store.load(blend_path)
        user_messages = [msg.content for msg in session.history.messages if msg.role == "user"]
        self.assertIn("legacy imported manually", user_messages)


if __name__ == "__main__":
    unittest.main()
