from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path

if "bpy" not in sys.modules:
    _handlers = types.SimpleNamespace(load_post=[], save_post=[], persistent=lambda fn: fn)
    sys.modules["bpy"] = types.SimpleNamespace(
        app=types.SimpleNamespace(handlers=_handlers),
        data=types.SimpleNamespace(filepath=""),
    )

from blender_addon.session import HistoryMessage, Session, SessionV1Store


class SessionReattachTests(unittest.TestCase):
    def test_unsaved_session_moves_to_saved_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionV1Store(project_root=Path(tmp))
            session = Session.new(blend_path="")
            session.history.messages.append(HistoryMessage(role="user", content="hello", ts="2026-01-01T00:00:00Z"))
            temp_path = store.save(session, "")

            saved_path = store.reattach_session("", "C:/proj/demo.blend")

            self.assertEqual(saved_path, store.v1_path("C:/proj/demo.blend"))
            self.assertFalse(temp_path.exists())
            migrated = store.load("C:/proj/demo.blend")
            self.assertEqual(migrated.focus.blend_path, "C:/proj/demo.blend")
            self.assertEqual(len(migrated.history.messages), 1)

    def test_save_as_moves_session_to_new_file_when_target_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionV1Store(project_root=Path(tmp))
            old_path = "C:/proj/old.blend"
            new_path = "C:/proj/new.blend"
            session = Session.new(blend_path=old_path)
            session.update_focus(tree_name="Geometry Nodes")
            old_session_path = store.save(session, old_path)

            moved_path = store.reattach_session(old_path, new_path)

            self.assertEqual(moved_path, store.v1_path(new_path))
            self.assertFalse(old_session_path.exists())
            migrated = store.load(new_path)
            self.assertEqual(migrated.focus.blend_path, new_path)
            self.assertEqual(migrated.focus.tree_name, "Geometry Nodes")

    def test_reattach_does_not_overwrite_existing_target_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionV1Store(project_root=Path(tmp))
            old_path = "C:/proj/old.blend"
            new_path = "C:/proj/new.blend"
            source = Session.new(blend_path=old_path)
            source.history.messages.append(HistoryMessage(role="user", content="source", ts="2026-01-01T00:00:00Z"))
            target = Session.new(blend_path=new_path)
            target.history.messages.append(HistoryMessage(role="user", content="target", ts="2026-01-01T00:00:00Z"))
            source_path = store.save(source, old_path)
            target_path = store.save(target, new_path)

            moved = store.reattach_session(old_path, new_path)

            self.assertIsNone(moved)
            self.assertTrue(source_path.exists())
            self.assertTrue(target_path.exists())
            loaded = store.load(new_path)
            self.assertEqual(loaded.history.messages[0].content, "target")

    def test_reattach_conflict_result_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionV1Store(project_root=Path(tmp))
            old_path = "C:/proj/old.blend"
            new_path = "C:/proj/new.blend"
            store.save(Session.new(blend_path=old_path), old_path)
            store.save(Session.new(blend_path=new_path), new_path)

            result = store.reattach_session_result(old_path, new_path)

            self.assertEqual(result.get("status"), "target_exists")
            self.assertEqual(result.get("old_blend_path"), old_path)
            self.assertEqual(result.get("new_blend_path"), new_path)
            self.assertIn("session_", str(result.get("target_session_file", "")))


if __name__ == "__main__":
    unittest.main()
