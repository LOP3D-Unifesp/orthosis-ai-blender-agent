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
    bpy.app = types.SimpleNamespace(  # type: ignore[attr-defined]
        handlers=types.SimpleNamespace(
            persistent=lambda fn: fn,
            load_post=[],
            save_post=[],
        ),
        timers=types.SimpleNamespace(
            register=lambda *args, **kwargs: None,
            is_registered=lambda *args, **kwargs: False,
            unregister=lambda *args, **kwargs: None,
        ),
    )
    bpy.data = types.SimpleNamespace(filepath="")  # type: ignore[attr-defined]
    sys.modules["bpy"] = bpy


_install_fake_bpy()

from blender_addon.session.chat_store import ChatHistoryStore
from blender_addon.session.schema import HistoryMessage, Session, utc_now_iso
from blender_addon.session.store import SessionV1Store


class TestChatHistoryStoreDurability(unittest.TestCase):
    def test_append_flushes_history_to_disk(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = ChatHistoryStore(root)

            with patch("blender_addon.session.chat_store.os.fsync") as mock_fsync:
                store.append("sess-1", role="assistant", content="resposta ok", turn_class="test")

            self.assertTrue(mock_fsync.called)
            history_path = root / "runtime" / "chat_history" / "sess-1.jsonl"
            rows = history_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(rows), 1)
            payload = json.loads(rows[0])
            self.assertEqual(payload["role"], "assistant")
            self.assertEqual(payload["content"], "resposta ok")
            self.assertEqual(payload["turn_class"], "test")


class TestSessionV1StoreAtomicSave(unittest.TestCase):
    def test_save_uses_atomic_replace_and_keeps_history_out_of_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            store = SessionV1Store(root)
            blend_path = str(root / "case.blend")
            session = Session.new(blend_path=blend_path)
            session.history.messages = [
                HistoryMessage(
                    role="assistant",
                    content="mensagem visivel",
                    ts=utc_now_iso(),
                    turn_class="test",
                )
            ]

            with patch("blender_addon.session.store.os.fsync") as mock_fsync:
                saved_path = store.save(session, blend_path=blend_path)

            self.assertTrue(mock_fsync.called)
            payload = json.loads(saved_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["history"]["messages"], [])
            self.assertEqual(list(saved_path.parent.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
