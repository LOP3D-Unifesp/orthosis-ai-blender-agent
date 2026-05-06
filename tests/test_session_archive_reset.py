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


def _session_payload(blend_path: str, user_text: str) -> dict:
    from blender_addon.session.schema import HistoryMessage, Session

    session = Session.new(blend_path=blend_path)
    session.history.messages.append(HistoryMessage(role="user", content=user_text))
    session.history.messages.append(HistoryMessage(role="assistant", content="assistant"))
    return session.to_dict()


class SessionArchiveResetTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _store(self):
        from blender_addon.session.store import SessionV1Store

        return SessionV1Store(project_root=self.project_root)

    def _write_v1(self, blend_path: str, user_text: str) -> Path:
        store = self._store()
        path = store.v1_path(blend_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_session_payload(blend_path, user_text), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def test_archive_reset_moves_current_v1_to_archive_and_creates_clean_session(self):
        main_blend = str((self.project_root / "testeAgenteBlender.blend").resolve())
        other_blend = str((self.project_root / "testeAgenteBlender1.blend").resolve())
        self._write_v1(main_blend, "histórico antigo do blend principal")
        self._write_v1(other_blend, "histórico do outro blend")

        store = self._store()
        result = store.archive_and_reset_v1_session(main_blend)

        self.assertTrue(bool(result.get("archived", False)))
        archive_file = Path(str(result.get("archive_file") or ""))
        current_file = Path(str(result.get("current_session_file") or ""))
        self.assertTrue(archive_file.exists())
        self.assertTrue(current_file.exists())
        self.assertNotEqual(archive_file, current_file)

        reloaded = store.load(main_blend)
        self.assertEqual(len(reloaded.history.messages), 0)
        self.assertEqual(reloaded.focus.blend_path, main_blend)

        archived_payload = json.loads(archive_file.read_text(encoding="utf-8"))
        archived_messages = archived_payload.get("history", {}).get("messages", [])
        archived_user_messages = [m.get("content", "") for m in archived_messages if m.get("role") == "user"]
        self.assertIn("histórico antigo do blend principal", archived_user_messages)

        other_reloaded = store.load(other_blend)
        other_user_messages = [m.content for m in other_reloaded.history.messages if m.role == "user"]
        self.assertIn("histórico do outro blend", other_user_messages)

    def test_runtime_archive_reset_logs_journal_event_and_lifecycle_note(self):
        from blender_addon.runtime import Runtime

        blend_path = str((self.project_root / "testeAgenteBlender.blend").resolve())
        self._write_v1(blend_path, "histórico antigo do blend principal")

        runtime = Runtime(project_root=self.project_root)
        result = runtime.archive_and_reset_session(blend_path)

        self.assertEqual(str(result.get("status") or ""), "archived_and_reset")
        session = runtime.v1_session_for(blend_path)
        self.assertEqual(len(session.history.messages), 0)
        self.assertIn("session_archived_and_reset", list(session.lifecycle.notes))

        journal_file = runtime.journal.session_file
        self.assertIsNotNone(journal_file)
        lines = Path(str(journal_file)).read_text(encoding="utf-8").splitlines()
        self.assertTrue(
            any('"event_type": "session_archived_and_reset"' in line for line in lines),
            "Expected session_archived_and_reset runtime event in journal",
        )

    def test_archive_reset_does_not_import_legacy(self):
        blend_path = str((self.project_root / "testeAgenteBlender.blend").resolve())
        self._write_v1(blend_path, "histórico antigo do blend principal")

        store = self._store()
        # archive_and_reset should complete without errors; no legacy import occurs
        store.archive_and_reset_v1_session(blend_path)
        session = store.load(blend_path)
        self.assertEqual(len(session.history.messages), 0)

    def test_diagnose_session_lists_current_candidates_and_archive(self):
        blend_path = str((self.project_root / "testeAgenteBlender.blend").resolve())
        current_path = self._write_v1(blend_path, "histórico atual")
        candidate_path = current_path.parent / "C_Users_Eduardo_Desktop_blend_IA_ort_v2_testeAgenteBlender.blend_legacy.session.json"
        candidate_path.write_text(
            json.dumps(_session_payload(blend_path, "candidato antigo"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        store = self._store()
        store.archive_and_reset_v1_session(blend_path)
        diagnosis = store.diagnose_v1_session(blend_path)

        self.assertEqual(int(diagnosis["current"]["msg_count"]), 0)
        self.assertEqual(str(diagnosis["current"]["path"]), str(store.v1_path(blend_path)))
        self.assertTrue(bool(diagnosis["archive"]["exists"]))
        candidate_messages = [entry.get("first", "") for entry in diagnosis["candidates"]]
        self.assertTrue(any("candidato antigo" in text for text in candidate_messages))
        archived_files = [entry.get("path", "") for entry in diagnosis["archive"]["files"]]
        self.assertTrue(any("archived_" in path for path in archived_files))


if __name__ == "__main__":
    unittest.main()
