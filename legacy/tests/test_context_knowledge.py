"""Phase 8 cleanup: this test file is obsolete.

context_knowledge was tombstoned in Phase 6 of REFATOR_PLAN.md.
Accessing any symbol from it raises ImportError by design.

The module-level import in the original test caused the entire file to fail
at collection time, producing a spurious ERROR in every test run.  The tests
themselves were testing behaviour that no longer exists (keyword-regex
knowledge selection replaced by structural retrieval in Phase 6).

Tests for the new knowledge retrieval live in test_knowledge_phase6.py.
"""
import unittest


class ContextKnowledgeTombstoneTest(unittest.TestCase):
    """Verify the Phase 6 tombstone raises ImportError as designed."""

    def test_context_knowledge_raises_import_error(self):
        import blender_addon.context_knowledge as ck
        with self.assertRaises(ImportError):
            _ = ck.select_knowledge
