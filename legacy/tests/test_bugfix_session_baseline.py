"""Tests for the two Priority 1 bug fixes.

Bug 1 — End Session gate
========================
_sync_v1_session() had a "sticky" preservation that prevented
agent_session_active=False from propagating to V1 ui_state.session_active.
The result: prompt sending stayed unblocked even after End Session.

Bug 2 — Baseline overwrite after turn
======================================
_sync_v1_session() rebuilt the V1 session from migrate_legacy_state() on
every legacy save. Because migrate_legacy_state() never produces a *built*
baseline (tree_signature and built_at are always empty), any BaselineWorkspace
built during a turn was immediately discarded by the post-turn legacy sync.

Both fixes live exclusively in blender_addon/runtime/core.py inside the
_sync_v1_session() method and affect only the same-session-ID branch.
"""

from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Minimal bpy stub so blender_addon imports succeed outside Blender.
# ---------------------------------------------------------------------------
if "bpy" not in sys.modules:
    sys.modules["bpy"] = types.SimpleNamespace()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_runtime(tmp: str) -> "Runtime":  # noqa: F821
    from blender_addon.runtime import Runtime
    return Runtime(project_root=Path(tmp))


def _persist_state(runtime, blend_path: str, state: dict) -> None:
    runtime.persist_runtime_state(state, blend_path)


def _active_legacy_state(runtime, blend_path: str) -> dict:
    """Return a legacy state dict that looks like an active session."""
    state = runtime.load_runtime_state(blend_path)
    runtime.state_adapter.begin_new_session(state)
    state["agent_session_active"] = True
    return state


def _build_real_baseline(runtime, blend_path: str):
    """Build and persist a genuine BaselineWorkspace into the V1 store.

    Returns the Session so the caller can inspect baseline fields.
    """
    from blender_addon.session.baseline import BaselineBuilder

    session = runtime.v1_session_for(blend_path)
    builder = BaselineBuilder(session.baseline_workspace)
    builder.rebuild_from_summary(
        {"node_count": 42, "name": "VM_Ortese", "links": 10},
        built_from="auto",
        subgraph_index={"VM_Ortese": {"frames": ["Frame_A"]}},
        known_parameters={"VM_G1_Scale": {"value": 1.0}},
    )
    runtime.save_v1_session(session)
    return session


# ===========================================================================
# Bug 1 — End Session gate
# ===========================================================================

class TestEndSessionGateFix(unittest.TestCase):
    """session_active must reliably follow agent_session_active in the legacy state."""

    # ------------------------------------------------------------------
    # 1. End Session sets session_active=False in V1
    # ------------------------------------------------------------------

    def test_end_session_sets_session_inactive_in_v1(self):
        """Core of Bug 1: saving agent_session_active=False must propagate to V1."""
        with tempfile.TemporaryDirectory() as tmp:
            runtime = _make_runtime(tmp)
            blend = "proj.blend"

            # Step 1: start a session → V1 session_active must become True.
            state = _active_legacy_state(runtime, blend)
            _persist_state(runtime, blend, state)

            v1_after_start = runtime.v1_session_for(blend)
            self.assertTrue(
                v1_after_start.ui_state.session_active,
                "session_active should be True after Start Session",
            )

            # Step 2: end session → agent_session_active=False in legacy.
            runtime.state_adapter.set_agent_session_active(state, False)
            state["agent_session_active"] = False
            _persist_state(runtime, blend, state)   # triggers _sync_v1_session

            v1_after_end = runtime.v1_session_for(blend)
            self.assertFalse(
                v1_after_end.ui_state.session_active,
                "session_active must be False after End Session (Bug 1 regression check)",
            )

    # ------------------------------------------------------------------
    # 2. Start New Session re-enables prompt sending
    # ------------------------------------------------------------------

    def test_start_new_session_re_enables_after_end(self):
        """Begin New Session must flip session_active back to True in V1."""
        with tempfile.TemporaryDirectory() as tmp:
            runtime = _make_runtime(tmp)
            blend = "proj.blend"

            # Start → end → start again.
            state = _active_legacy_state(runtime, blend)
            _persist_state(runtime, blend, state)

            # End session.
            runtime.state_adapter.set_agent_session_active(state, False)
            state["agent_session_active"] = False
            _persist_state(runtime, blend, state)
            self.assertFalse(runtime.v1_session_for(blend).ui_state.session_active)

            # Start new session (begin_new_session rotates session_id + sets True).
            runtime.state_adapter.begin_new_session(state)
            state["agent_session_active"] = True
            _persist_state(runtime, blend, state)

            v1_reactivated = runtime.v1_session_for(blend)
            self.assertTrue(
                v1_reactivated.ui_state.session_active,
                "session_active must be True after Begin New Session",
            )

    # ------------------------------------------------------------------
    # 3. Sticky logic still works for the INTENDED case
    # ------------------------------------------------------------------

    def test_sticky_still_applies_when_legacy_field_absent(self):
        """Sticky logic must still preserve V1 True when legacy field is missing.

        This covers the original motivation: an old legacy state that doesn't
        carry agent_session_active at all should not accidentally clear an
        active V1 session.
        """
        with tempfile.TemporaryDirectory() as tmp:
            runtime = _make_runtime(tmp)
            blend = "proj.blend"

            # Build a V1 session with session_active=True directly.
            session = runtime.v1_session_for(blend)
            session.ui_state.session_active = True
            runtime.save_v1_session(session)

            # Now simulate a legacy sync where agent_session_active is ABSENT
            # (no key in the dict). The migrated session will default to False;
            # the sticky logic should restore True because we didn't explicitly
            # set it to False.
            from blender_addon.session_store import _new_session_id
            # Craft a minimal legacy state that shares the session_id but has
            # no agent_session_active key.
            raw_v1 = session.to_dict()
            legacy_minimal = {
                "session_id": raw_v1["identity"]["session_id"],
                "blend_path": blend,
                # agent_session_active intentionally absent
            }
            # Call _sync_v1_session directly with this minimal state.
            runtime._sync_v1_session(blend, legacy_minimal)

            v1_after = runtime.v1_session_for(blend)
            self.assertTrue(
                v1_after.ui_state.session_active,
                "Sticky logic must preserve True when legacy field is absent",
            )

    # ------------------------------------------------------------------
    # 4. Prompt gate stays blocked across a tool-call sync cycle
    # ------------------------------------------------------------------

    def test_end_session_survives_intermediate_tool_sync(self):
        """session_active=False must survive a subsequent _sync_v1_session call
        that carries tool results (simulates the common post-turn save path)."""
        with tempfile.TemporaryDirectory() as tmp:
            runtime = _make_runtime(tmp)
            blend = "test.blend"

            state = _active_legacy_state(runtime, blend)
            _persist_state(runtime, blend, state)

            # End session.
            runtime.state_adapter.set_agent_session_active(state, False)
            state["agent_session_active"] = False
            _persist_state(runtime, blend, state)

            # Simulate a random tool result sync (e.g., a get_scene_summary
            # result that arrives after the session was ended).
            runtime._sync_v1_session(
                blend,
                state,
                canonical_tool="get_scene_summary",
                raw={"status": "success", "result": {"objects": []}},
                tool_input={},
            )

            v1_final = runtime.v1_session_for(blend)
            self.assertFalse(
                v1_final.ui_state.session_active,
                "session_active must stay False through additional syncs after End Session",
            )

    # ------------------------------------------------------------------
    # 5. Session ID mismatch — no cross-session bleed
    # ------------------------------------------------------------------

    def test_no_session_active_bleed_across_session_ids(self):
        """A new session must not inherit session_active from a different session's V1."""
        with tempfile.TemporaryDirectory() as tmp:
            runtime = _make_runtime(tmp)
            blend = "bleed.blend"

            # Write a V1 with session_active=True.
            old_session = runtime.v1_session_for(blend)
            old_session.ui_state.session_active = True
            runtime.save_v1_session(old_session)

            # Now save a NEW legacy state with a different session_id and
            # agent_session_active=False (brand-new session not yet started).
            from blender_addon.session_store import _new_session_id
            new_state = {
                "session_id": _new_session_id(),   # different ID
                "blend_path": blend,
                "agent_session_active": False,
            }
            runtime._sync_v1_session(blend, new_state)

            v1_new = runtime.v1_session_for(blend)
            # The IDs don't match → sticky block does NOT run → value from
            # migration (False) must stand.
            self.assertFalse(
                v1_new.ui_state.session_active,
                "A new session must not inherit session_active=True from a different session",
            )


# ===========================================================================
# Bug 2 — Baseline overwrite after turn
# ===========================================================================

class TestBaselinePreservationFix(unittest.TestCase):
    """Built BaselineWorkspace must survive the post-turn legacy→V1 sync."""

    # ------------------------------------------------------------------
    # 1. Built baseline survives a plain legacy sync (the primary regression)
    # ------------------------------------------------------------------

    def test_built_baseline_survives_post_turn_sync(self):
        """Baseline built during a turn must not be discarded by _sync_v1_session."""
        with tempfile.TemporaryDirectory() as tmp:
            runtime = _make_runtime(tmp)
            blend = "ortese.blend"

            # Start a session so the IDs match later.
            state = _active_legacy_state(runtime, blend)
            _persist_state(runtime, blend, state)

            # Build a rich baseline in the V1 session (simulates what a
            # baseline_refresh or get_tree_structure handler does during a turn).
            session = _build_real_baseline(runtime, blend)
            saved_sig = session.baseline_workspace.tree_signature
            self.assertTrue(session.baseline_workspace.is_built(), "Pre-condition: baseline must be built")
            self.assertFalse(session.baseline_workspace.stale, "Pre-condition: baseline must not be stale")

            # Simulate the post-turn legacy sync: agent_runtime.run_turn() calls
            # save_v1_session() and then _sync_v1_to_legacy() → session_store.save()
            # → SyncedSessionStore.save() → _sync_v1_session().
            _persist_state(runtime, blend, state)   # this was the bug trigger

            v1_after_sync = runtime.v1_session_for(blend)
            self.assertTrue(
                v1_after_sync.baseline_workspace.is_built(),
                "Baseline must still be built after post-turn legacy sync (Bug 2 regression check)",
            )
            self.assertEqual(
                v1_after_sync.baseline_workspace.tree_signature,
                saved_sig,
                "tree_signature must be identical — baseline must not have been replaced",
            )
            self.assertFalse(
                v1_after_sync.baseline_workspace.stale,
                "Baseline must not be marked stale by the sync alone",
            )

    # ------------------------------------------------------------------
    # 2. Rich baseline preserved even when legacy has poorer data
    # ------------------------------------------------------------------

    def test_rich_v1_baseline_preferred_over_migrated_baseline(self):
        """V1 baseline with subgraph_index beats the thin migrated-from-legacy baseline."""
        with tempfile.TemporaryDirectory() as tmp:
            runtime = _make_runtime(tmp)
            blend = "rich.blend"

            state = _active_legacy_state(runtime, blend)
            _persist_state(runtime, blend, state)

            session = _build_real_baseline(runtime, blend)
            self.assertIn("VM_Ortese", session.baseline_workspace.subgraph_index)
            self.assertEqual(session.baseline_workspace.known_parameters["VM_G1_Scale"]["value"], 1.0)

            # The legacy state only carries a minimal gn_summary.
            state["last_gn_summary"] = {"name": "VM_Ortese", "node_count": 5}
            state["structural_index"] = {}
            _persist_state(runtime, blend, state)

            v1 = runtime.v1_session_for(blend)
            # The rich subgraph_index must survive, not the thin migration output.
            self.assertIn(
                "VM_Ortese",
                v1.baseline_workspace.subgraph_index,
                "Rich subgraph_index from V1 baseline must be preserved over thin migration",
            )
            self.assertIn(
                "VM_G1_Scale",
                v1.baseline_workspace.known_parameters,
                "known_parameters from V1 baseline must be preserved",
            )

    # ------------------------------------------------------------------
    # 3. Stale but built baseline is still preserved (data > nothing)
    # ------------------------------------------------------------------

    def test_stale_built_baseline_preserved_over_empty(self):
        """Even a stale baseline (is_built=True, stale=True) beats an empty one."""
        with tempfile.TemporaryDirectory() as tmp:
            runtime = _make_runtime(tmp)
            blend = "stale.blend"

            state = _active_legacy_state(runtime, blend)
            _persist_state(runtime, blend, state)

            # Build a baseline, then mark it stale (as a mutation tool would).
            session = _build_real_baseline(runtime, blend)
            session.baseline_workspace.mark_stale()
            runtime.save_v1_session(session)

            self.assertTrue(session.baseline_workspace.is_built())
            self.assertTrue(session.baseline_workspace.stale)

            # Post-turn sync.
            _persist_state(runtime, blend, state)

            v1 = runtime.v1_session_for(blend)
            self.assertTrue(
                v1.baseline_workspace.is_built(),
                "Stale-but-built baseline must be preserved (has structural data)",
            )
            self.assertTrue(v1.baseline_workspace.stale, "stale flag must survive")
            self.assertIn("VM_Ortese", v1.baseline_workspace.subgraph_index)

    # ------------------------------------------------------------------
    # 4. Empty baseline not injected when V1 has nothing built
    # ------------------------------------------------------------------

    def test_no_baseline_preserved_when_v1_never_built(self):
        """When V1 has never had a built baseline, sync must not invent one."""
        with tempfile.TemporaryDirectory() as tmp:
            runtime = _make_runtime(tmp)
            blend = "fresh.blend"

            state = _active_legacy_state(runtime, blend)
            _persist_state(runtime, blend, state)   # creates V1 file

            # Do NOT build any baseline. Just sync again.
            _persist_state(runtime, blend, state)

            v1 = runtime.v1_session_for(blend)
            self.assertFalse(
                v1.baseline_workspace.is_built(),
                "V1 must not have a built baseline if none was ever built",
            )

    # ------------------------------------------------------------------
    # 5. Tool result that builds baseline during sync still works
    # ------------------------------------------------------------------

    def test_tool_result_baseline_not_blocked_by_preservation(self):
        """A get_tree_structure tool result passed into _sync_v1_session must
        still update the baseline (the preserved baseline is a starting point,
        not a lock)."""
        with tempfile.TemporaryDirectory() as tmp:
            runtime = _make_runtime(tmp)
            blend = "toolresult.blend"

            state = _active_legacy_state(runtime, blend)
            _persist_state(runtime, blend, state)

            # Build an initial baseline.
            _build_real_baseline(runtime, blend)

            # Now simulate a sync that carries a get_tree_structure result
            # (as _apply_tool_result_to_v1_session would process it).
            new_summary = {
                "name": "VM_Ortese_v2",
                "node_count": 80,
                "links": [{"from": "A", "to": "B"}],
            }
            runtime._sync_v1_session(
                blend,
                state,
                canonical_tool="get_tree_structure",
                raw={"status": "success", "result": new_summary},
                tool_input={"tree_name": "VM_Ortese_v2"},
            )

            v1 = runtime.v1_session_for(blend)
            self.assertTrue(v1.baseline_workspace.is_built())
            # The new tree summary must have updated the baseline signature.
            self.assertNotEqual(
                v1.baseline_workspace.structural_summary,
                {},
                "Baseline structural_summary must be updated by tool result",
            )

    # ------------------------------------------------------------------
    # 6. Baseline not carried across session ID boundaries
    # ------------------------------------------------------------------

    def test_baseline_not_carried_to_new_session(self):
        """A new session (different session_id) must start with a fresh baseline."""
        with tempfile.TemporaryDirectory() as tmp:
            runtime = _make_runtime(tmp)
            blend = "newsession.blend"

            state = _active_legacy_state(runtime, blend)
            _persist_state(runtime, blend, state)
            _build_real_baseline(runtime, blend)

            # Simulate Begin New Session: new session_id in legacy.
            from blender_addon.session_store import _new_session_id as _nsi
            state["session_id"] = _nsi()       # rotate to a new ID
            state["agent_session_active"] = True
            _persist_state(runtime, blend, state)

            v1 = runtime.v1_session_for(blend)
            # The old session's baseline must NOT have been copied to the new one.
            self.assertFalse(
                v1.baseline_workspace.is_built(),
                "New session must not inherit a built baseline from the previous session",
            )


# ===========================================================================
# Integration: both fixes together
# ===========================================================================

class TestBothFixesIntegration(unittest.TestCase):
    """End-to-end scenario: full session lifecycle with baseline build."""

    def test_full_cycle_session_and_baseline(self):
        """Start → build baseline → end session → start new session.

        Verifies that:
          - session_active tracks correctly through the full cycle,
          - baseline built in session 1 does not bleed into session 2.
        """
        with tempfile.TemporaryDirectory() as tmp:
            runtime = _make_runtime(tmp)
            blend = "full.blend"

            # ---- Session 1 ----
            state = _active_legacy_state(runtime, blend)
            _persist_state(runtime, blend, state)

            _build_real_baseline(runtime, blend)
            sig_s1 = runtime.v1_session_for(blend).baseline_workspace.tree_signature

            # A few post-turn syncs (simulate turns happening).
            for _ in range(3):
                _persist_state(runtime, blend, state)

            v1_mid = runtime.v1_session_for(blend)
            self.assertTrue(v1_mid.ui_state.session_active, "active mid-session")
            self.assertTrue(v1_mid.baseline_workspace.is_built(), "baseline preserved mid-session")
            self.assertEqual(v1_mid.baseline_workspace.tree_signature, sig_s1)

            # End session.
            runtime.state_adapter.set_agent_session_active(state, False)
            state["agent_session_active"] = False
            _persist_state(runtime, blend, state)

            v1_ended = runtime.v1_session_for(blend)
            self.assertFalse(v1_ended.ui_state.session_active, "inactive after end")

            # ---- Session 2 ----
            runtime.state_adapter.begin_new_session(state)  # new session_id
            state["agent_session_active"] = True
            _persist_state(runtime, blend, state)

            v1_new = runtime.v1_session_for(blend)
            self.assertTrue(v1_new.ui_state.session_active, "active in new session")
            self.assertFalse(
                v1_new.baseline_workspace.is_built(),
                "new session must not inherit baseline from session 1",
            )


if __name__ == "__main__":
    unittest.main()
