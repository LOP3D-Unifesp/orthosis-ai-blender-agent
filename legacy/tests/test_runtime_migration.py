from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path

if "bpy" not in sys.modules:
    sys.modules["bpy"] = types.SimpleNamespace()

from blender_addon.runtime_migration import _merge_jsonl


class RuntimeMigrationTests(unittest.TestCase):
    def test_merge_jsonl_dedups_equal_json_with_different_key_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.jsonl"
            dest = root / "dest.jsonl"
            dest.write_text('{"type":"goal_start","goal_id":"g1","timestamp":"2026-04-01T00:00:00+00:00","session_id":"s1"}\n', encoding="utf-8")
            source.write_text('{"session_id":"s1","timestamp":"2026-04-01T00:00:00+00:00","goal_id":"g1","type":"goal_start"}\n', encoding="utf-8")

            _merge_jsonl(source, dest)

            lines = [line for line in dest.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(lines), 1)

    def test_merge_jsonl_dedups_outcomes_that_only_differ_by_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.jsonl"
            dest = root / "dest.jsonl"
            dest.write_text('{"goal_id":"g1","session_id":"s1","outcome":"accepted","notes":"","timestamp":"2026-04-01T00:00:00+00:00"}\n', encoding="utf-8")
            source.write_text('{"goal_id":"g1","session_id":"s1","outcome":"accepted","notes":"","timestamp":"2026-04-02T00:00:00+00:00"}\n', encoding="utf-8")

            _merge_jsonl(source, dest)

            lines = [line for line in dest.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(lines), 1)

    def test_merge_jsonl_keeps_distinct_runtime_events_with_only_timestamp_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.jsonl"
            dest = root / "dest.jsonl"
            dest.write_text('{"type":"runtime_event","goal_id":"g1","event_type":"session_memory_updated","timestamp":"2026-04-01T00:00:00+00:00","payload":{"used":true},"session_id":"s1"}\n', encoding="utf-8")
            source.write_text('{"type":"runtime_event","goal_id":"g1","event_type":"session_memory_updated","timestamp":"2026-04-02T00:00:00+00:00","payload":{"used":true},"session_id":"s1"}\n', encoding="utf-8")

            _merge_jsonl(source, dest)

            lines = [line for line in dest.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(lines), 2)


if __name__ == "__main__":
    unittest.main()
