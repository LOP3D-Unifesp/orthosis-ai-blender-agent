"""Tests for the v1 structured session schema (Phase 1 of REFATOR_PLAN.md).

Covers:
* schema construction and defaults,
* invariants on focus changes / baseline staleness,
* bounded history helper,
* baseline builder scaffolding,
* persistence round-trip via SessionV1Store,
* one-shot migration from the legacy flat dict (schema 0.1).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from blender_addon.session import (
    SCHEMA_VERSION,
    BaselineBuilder,
    BaselineWorkspace,
    BoundedHistory,
    ExecutionState,
    Focus,
    History,
    HistoryMessage,
    Identity,
    Lifecycle,
    OperationalState,
    PendingMutation,
    Session,
    SessionV1Store,
    UIState,
    compute_focus_signature,
    compute_tree_signature,
)
from blender_addon.session.store import migrate_legacy_state


# ---------------------------------------------------------------------------
# Schema construction
# ---------------------------------------------------------------------------


class SchemaConstructionTests(unittest.TestCase):
    def test_session_new_has_operational_block_and_v1_schema_version(self):
        session = Session.new(blend_path="demo.blend")
        self.assertEqual(session.identity.schema_version, SCHEMA_VERSION)
        self.assertEqual(session.identity.canonical_language, "en")
        self.assertEqual(session.focus.blend_path, "demo.blend")
        self.assertTrue(session.focus.focus_signature)
        self.assertIsInstance(session.baseline_workspace, BaselineWorkspace)
        self.assertTrue(session.baseline_workspace.stale)
        self.assertIsInstance(session.history, History)
        self.assertEqual(session.execution_state.phase, "idle")
        self.assertIsNone(session.execution_state.pending_mutation)
        self.assertIsInstance(session.ui_state, UIState)
        self.assertIsInstance(session.operational_state, OperationalState)
        self.assertIsInstance(session.lifecycle, Lifecycle)
        self.assertTrue(session.lifecycle.continuity_token.startswith("cont-"))

    def test_focus_signature_is_deterministic(self):
        a = compute_focus_signature("demo.blend", None, "GeometryNodes", "GN_Tree")
        b = compute_focus_signature("demo.blend", None, "GeometryNodes", "GN_Tree")
        c = compute_focus_signature("demo.blend", None, "GeometryNodes", "Other")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_execution_state_rejects_unknown_phase(self):
        state = ExecutionState()
        with self.assertRaises(ValueError):
            state.set_phase("unknown_phase")

    def test_execution_state_normalises_unknown_initial_phase(self):
        state = ExecutionState(phase="bogus")
        self.assertEqual(state.phase, "idle")

    def test_lifecycle_remember_prior_session_is_bounded_and_unique(self):
        lifecycle = Lifecycle()
        for i in range(50):
            lifecycle.remember_prior_session(f"sess-{i}")
        # Same id added twice should not duplicate.
        lifecycle.remember_prior_session("sess-49")
        self.assertLessEqual(len(lifecycle.prior_session_ids), 16)
        self.assertEqual(lifecycle.prior_session_ids[-1], "sess-49")


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------


class SessionInvariantTests(unittest.TestCase):
    def test_focus_change_marks_baseline_stale_and_clears_pending_mutation(self):
        session = Session.new(blend_path="demo.blend")
        # Pretend a baseline was built.
        BaselineBuilder(session.baseline_workspace).rebuild_from_summary(
            {"counts": {"nodes": 10}},
            built_from="auto",
        )
        self.assertFalse(session.baseline_workspace.stale)
        # Pretend the agent proposed a mutation.
        session.set_pending_mutation(
            PendingMutation(description="set scale to 1.0", focus_signature=session.focus.focus_signature)
        )
        self.assertEqual(session.execution_state.phase, "awaiting_confirmation")
        self.assertIsNotNone(session.execution_state.pending_mutation)

        changed = session.update_focus(modifier_name="GeometryNodes", tree_name="GN_Tree")

        self.assertTrue(changed)
        self.assertTrue(session.baseline_workspace.stale)
        self.assertIsNone(session.execution_state.pending_mutation)
        self.assertEqual(session.execution_state.phase, "idle")

    def test_focus_update_with_same_coordinates_is_a_noop(self):
        session = Session.new(blend_path="demo.blend")
        original_signature = session.focus.focus_signature
        changed = session.update_focus(blend_path="demo.blend")
        self.assertFalse(changed)
        self.assertEqual(session.focus.focus_signature, original_signature)

    def test_mark_baseline_stale_clears_pending_mutation(self):
        session = Session.new(blend_path="demo.blend")
        session.set_pending_mutation(
            PendingMutation(description="wire A to B", focus_signature=session.focus.focus_signature)
        )
        self.assertEqual(session.execution_state.phase, "awaiting_confirmation")

        session.mark_baseline_stale()

        self.assertTrue(session.baseline_workspace.stale)
        self.assertIsNone(session.execution_state.pending_mutation)
        self.assertEqual(session.execution_state.phase, "idle")

    def test_clear_pending_mutation_returns_to_idle(self):
        session = Session.new(blend_path="demo.blend")
        session.set_pending_mutation(
            PendingMutation(description="set scale", focus_signature=session.focus.focus_signature)
        )
        session.clear_pending_mutation()
        self.assertIsNone(session.execution_state.pending_mutation)
        self.assertEqual(session.execution_state.phase, "idle")

    def test_set_pending_mutation_binds_to_current_focus(self):
        session = Session.new(blend_path="demo.blend")
        mutation = PendingMutation(description="set scale to 1.0")
        session.set_pending_mutation(mutation)
        self.assertEqual(
            session.execution_state.pending_mutation.focus_signature,
            session.focus.focus_signature,
        )


# ---------------------------------------------------------------------------
# History helper
# ---------------------------------------------------------------------------


class BoundedHistoryTests(unittest.TestCase):
    def test_append_rejects_invalid_role(self):
        history = History()
        bounded = BoundedHistory(history)
        self.assertIsNone(bounded.append(role="moderator", content="hi"))
        self.assertIsNone(bounded.append(role="user", content="   "))
        self.assertEqual(len(bounded), 0)

    def test_append_records_message_with_role_content_turn_class(self):
        bounded = BoundedHistory(History())
        msg = bounded.append(role="user", content="hello", turn_class="diagnosis")
        self.assertIsNotNone(msg)
        self.assertEqual(msg.role, "user")
        self.assertEqual(msg.content, "hello")
        self.assertEqual(msg.turn_class, "diagnosis")
        self.assertEqual(len(bounded), 1)

    def test_history_is_bounded_to_max_messages(self):
        history = History(max_messages=3)
        bounded = BoundedHistory(history)
        for i in range(10):
            bounded.append(role="user", content=f"msg{i}")
        self.assertEqual(len(bounded), 3)
        self.assertEqual([m.content for m in history.messages], ["msg7", "msg8", "msg9"])

    def test_summariser_callback_receives_evicted_messages(self):
        seen: list[list[HistoryMessage]] = []

        def summariser(evicted, prior):
            seen.append(list(evicted))
            return f"summary:{len(evicted)}"

        history = History(max_messages=2)
        bounded = BoundedHistory(history, summariser=summariser)
        bounded.append(role="user", content="a")
        bounded.append(role="assistant", content="b")
        bounded.append(role="user", content="c")
        self.assertEqual(history.older_summary, "summary:1")
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0].content, "a")

    def test_extend_skips_invalid_items(self):
        bounded = BoundedHistory(History())
        appended = bounded.extend(
            [
                {"role": "user", "content": "hello"},
                {"role": "system", "text": "boot"},
                "not a dict",
                {"role": "moderator", "content": "blocked"},
                {"role": "assistant", "content": ""},
            ]
        )
        self.assertEqual(appended, 2)


# ---------------------------------------------------------------------------
# Baseline builder
# ---------------------------------------------------------------------------


class BaselineBuilderTests(unittest.TestCase):
    def test_rebuild_marks_baseline_fresh_and_signs_summary(self):
        baseline = BaselineWorkspace()
        builder = BaselineBuilder(baseline)
        self.assertTrue(builder.is_stale())
        builder.rebuild_from_summary({"counts": {"nodes": 12}}, built_from="user_request")
        self.assertFalse(builder.is_stale())
        self.assertTrue(builder.is_built())
        self.assertEqual(baseline.built_from, "user_request")
        self.assertEqual(baseline.tree_signature, compute_tree_signature({"counts": {"nodes": 12}}))

    def test_signature_is_dict_order_independent(self):
        a = compute_tree_signature({"counts": {"nodes": 12}, "depth": 4})
        b = compute_tree_signature({"depth": 4, "counts": {"nodes": 12}})
        self.assertEqual(a, b)

    def test_rejects_unknown_built_from(self):
        builder = BaselineBuilder(BaselineWorkspace())
        with self.assertRaises(ValueError):
            builder.rebuild_from_summary({"counts": {}}, built_from="weird_source")

    def test_is_sufficient_for_requires_blocks(self):
        baseline = BaselineWorkspace()
        builder = BaselineBuilder(baseline)
        builder.rebuild_from_summary({"counts": {"nodes": 1}}, built_from="auto")
        self.assertTrue(builder.is_sufficient_for(requires={"structural_summary"}))
        self.assertFalse(builder.is_sufficient_for(requires={"subgraph_index"}))
        builder.rebuild_from_summary(
            {"counts": {"nodes": 1}},
            built_from="auto",
            subgraph_index={"GN_Tree": {"nodes": 5}},
        )
        self.assertTrue(builder.is_sufficient_for(requires={"subgraph_index"}))


# ---------------------------------------------------------------------------
# Persistence round-trip
# ---------------------------------------------------------------------------


class SessionPersistenceTests(unittest.TestCase):
    def test_round_trip_preserves_all_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionV1Store(project_root=Path(tmp))
            session = Session.new(blend_path="demo.blend")
            session.update_focus(modifier_name="GeometryNodes", tree_name="GN_Tree")
            BaselineBuilder(session.baseline_workspace).rebuild_from_summary(
                {"counts": {"nodes": 4, "links": 7}},
                built_from="auto",
                subgraph_index={"main": {"nodes": ["A", "B"]}},
                known_parameters={"VM_G1_Scale": {"field": "Value", "value": 0.5, "source": "test"}},
                open_questions=["where does the spline branch off?"],
            )
            BoundedHistory(session.history).append(role="user", content="show node X", turn_class="diagnosis")
            session.ui_state.debug_mode = True

            path = store.save(session, "demo.blend")
            self.assertTrue(path.exists())
            self.assertIn("sessions_v1", str(path))

            reloaded = store.load("demo.blend")
            self.assertEqual(reloaded.identity.schema_version, SCHEMA_VERSION)
            self.assertEqual(reloaded.identity.session_id, session.identity.session_id)
            self.assertEqual(reloaded.focus.tree_name, "GN_Tree")
            self.assertEqual(reloaded.focus.focus_signature, session.focus.focus_signature)
            self.assertFalse(reloaded.baseline_workspace.stale)
            self.assertEqual(reloaded.baseline_workspace.tree_signature, session.baseline_workspace.tree_signature)
            self.assertEqual(reloaded.baseline_workspace.subgraph_index, {"main": {"nodes": ["A", "B"]}})
            self.assertEqual(reloaded.baseline_workspace.known_parameters["VM_G1_Scale"]["value"], 0.5)
            self.assertEqual(reloaded.baseline_workspace.open_questions, ["where does the spline branch off?"])
            self.assertEqual(len(reloaded.history.messages), 1)
            self.assertEqual(reloaded.history.messages[0].turn_class, "diagnosis")
            self.assertTrue(reloaded.ui_state.debug_mode)
            self.assertIsInstance(reloaded.lifecycle, Lifecycle)

    def test_load_fresh_returns_empty_session_bound_to_blend_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionV1Store(project_root=Path(tmp))
            session = store.load("never_seen.blend")
            self.assertEqual(session.focus.blend_path, "never_seen.blend")
            self.assertEqual(session.identity.schema_version, SCHEMA_VERSION)
            self.assertEqual(session.execution_state.phase, "idle")
            self.assertFalse(store.has_v1_file("never_seen.blend"))

    def test_save_writes_to_v1_subdirectory_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionV1Store(project_root=Path(tmp))
            store.save(Session.new(blend_path="demo.blend"), "demo.blend")
            v1_dir = Path(tmp) / "runtime" / "sessions_v1"
            legacy_dir = Path(tmp) / "runtime" / "sessions"
            self.assertTrue(v1_dir.exists())
            self.assertFalse(legacy_dir.exists())

    def test_save_serialises_to_valid_json_with_schema_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionV1Store(project_root=Path(tmp))
            path = store.save(Session.new(blend_path="demo.blend"), "demo.blend")
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], SCHEMA_VERSION)
            for key in (
                "identity",
                "focus",
                "baseline_workspace",
                "history",
                "execution_state",
                "ui_state",
                "operational_state",
                "lifecycle",
            ):
                self.assertIn(key, payload)

    def test_pending_mutation_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionV1Store(project_root=Path(tmp))
            session = Session.new(blend_path="demo.blend")
            session.set_pending_mutation(
                PendingMutation(
                    description="set VM_G1_Scale to 1.0",
                    tool_calls=[{"name": "execute_code", "input": {"code": "..."}}],
                    plan_used=False,
                )
            )
            store.save(session, "demo.blend")
            reloaded = store.load("demo.blend")
            self.assertEqual(reloaded.execution_state.phase, "awaiting_confirmation")
            self.assertIsNotNone(reloaded.execution_state.pending_mutation)
            self.assertEqual(
                reloaded.execution_state.pending_mutation.description,
                "set VM_G1_Scale to 1.0",
            )
            self.assertEqual(
                reloaded.execution_state.pending_mutation.focus_signature,
                session.focus.focus_signature,
            )


# ---------------------------------------------------------------------------
# Legacy migration
# ---------------------------------------------------------------------------


def _legacy_state_fixture() -> dict[str, object]:
    """Mirror of the real legacy file shape, with all of the do-not-preserve fields."""
    return {
        "schema_version": "0.1",
        "session_id": "sess-20260402T013704Z-e8546330",
        "blend_path": "C:/path/to/file.blend",
        "last_scene_summary": {"objects": ["Cube"]},
        "last_gn_summary": {"trees": {"GN_Tree": {"nodes": 12}}},
        "recent_actions": [{"tool_name": "get_scene_summary", "status": "ok"}],
        "debug_mode": True,
        "explicit_override_mode": False,
        "mcp_write_enabled": True,
        "last_task_class": "scene_cleanup",
        "last_target_tree": "Geometry Nodes",
        "audit_trail": [],
        "agent_session_active": True,
        "session_started_at": "2026-04-02T01:37:04+00:00",
        "turn_counter": 28,
        "session_memory": {
            "last_goal": "Tighten the curvature near the wrist anchor.",
            "target_tree": "Geometry Nodes",
            "focus_subgraph": "G1 region",
            "active_frame": "",
            "relevant_nodes": ["VM_G1_Scale"],
            "last_parameter_changes": [
                {"node": "VM_G1_Scale", "field": "Value", "value": 0.7}
            ],
            "last_hypothesis": "G1 continuity is breaking at the inner anchor.",
            "decisions": ["explicit_user_read_request"],
            "aliases": {},
            "nodes_precreated_by_user": [],
            "last_manual_roundtrip_note": "",
        },
        "structural_index": {"Geometry Nodes": {"nodes": 12, "links": 18}},
        "local_scope": {},
        "tree_change_markers": {},
        "updated_at": "2026-04-03T16:54:16+00:00",
        # Do-not-preserve fields below: every one of these must vanish.
        "current_plan_id": "plan-c5ced3c4d9",
        "current_plan_status": "presented",
        "current_plan_type": "execution_plan",
        "current_plan_mode": "supervised",
        "approval_required": True,
        "approval_token": "appr-6dd956ba17f8",
        "approval_status": "pending",
        "approval_source": "",
        "execution_plan_id": "plan-execution-1",
        "execution_approval_token": "appr-execution",
        "fallback_plan_id": "plan-fallback-1",
        "fallback_approval_token": "appr-fallback",
        "presented_plan_summary": "Cleanup the scene before continuing.",
        "presented_plan_steps": ["Confirm target", "Execute cleanup", "Verify"],
        "presented_plan_stages": [{"stage_id": "stage-1", "stage_status": "pending"}],
        "presented_plan_tools": ["get_scene_summary", "execute_code"],
        "presented_context_reads": ["get_scene_summary"],
        "presented_fallback_possible": True,
        "presented_execute_code_risk": True,
        "current_stage_id": "stage-f3568e13",
        "current_stage_index": 0,
        "current_stage_status": "pending",
        "execution_policy": {
            "always_plan_first": True,
            "mutation_requires_user_approval": True,
        },
        "last_replan": {},
        "last_failure": "Tool execute_code raised an error: division by zero.",
        "chat_history": [
            {"role": "user", "text": "let's clean the scene", "timestamp": "2026-04-03T16:50:00+00:00"},
            {"role": "assistant", "text": "I'll plan the cleanup.", "timestamp": "2026-04-03T16:50:05+00:00"},
            {"role": "moderator", "text": "should be ignored", "timestamp": "x"},
            "not a dict, should be ignored",
            {"role": "user", "text": "", "timestamp": "x"},
        ],
        "legacy_chat_history_enabled": True,
    }


class LegacyMigrationTests(unittest.TestCase):
    def test_migrate_from_legacy_state_produces_v1_session(self):
        legacy = _legacy_state_fixture()
        session = migrate_legacy_state(legacy, blend_path=legacy["blend_path"])

        self.assertEqual(session.identity.schema_version, SCHEMA_VERSION)
        self.assertEqual(session.identity.session_id, legacy["session_id"])
        self.assertEqual(session.focus.blend_path, legacy["blend_path"])
        self.assertEqual(session.focus.tree_name, "Geometry Nodes")
        self.assertTrue(session.focus.focus_signature)

        # Baseline carries the GN summary as a structural hint and is stale.
        self.assertTrue(session.baseline_workspace.stale)
        self.assertIn("last_gn_summary", session.baseline_workspace.structural_summary)
        self.assertEqual(
            session.baseline_workspace.subgraph_index["Geometry Nodes"]["nodes"], 12
        )
        self.assertEqual(
            session.baseline_workspace.known_parameters["VM_G1_Scale"]["value"], 0.7
        )
        self.assertTrue(
            any("hypothesis_to_revisit" in q for q in session.baseline_workspace.open_questions)
        )

        # History migrates only the valid messages, in order, with bounds applied.
        self.assertEqual(len(session.history.messages), 2)
        self.assertEqual(session.history.messages[0].role, "user")
        self.assertEqual(session.history.messages[1].role, "assistant")

        # UI state preserves the user's mode toggles.
        self.assertTrue(session.ui_state.debug_mode)
        self.assertTrue(session.ui_state.mcp_write_enabled)
        self.assertFalse(session.ui_state.explicit_override_mode)

        # Operational state preserves the remaining flat runtime memory.
        self.assertEqual(session.operational_state.session_memory["target_tree"], "Geometry Nodes")
        self.assertEqual(session.operational_state.turn_counter, 28)
        self.assertEqual(session.operational_state.structural_index["Geometry Nodes"]["nodes"], 12)
        self.assertEqual(session.operational_state.last_scene_summary["objects"], ["Cube"])
        self.assertEqual(session.operational_state.recent_actions[0]["tool_name"], "get_scene_summary")

        # Lifecycle remembers the prior session id and notes the last goal.
        self.assertIn(legacy["session_id"], session.lifecycle.prior_session_ids)
        self.assertTrue(any("last_goal" in note for note in session.lifecycle.notes))

        # Execution state is reset to idle. The legacy failure becomes a hint
        # but every approval/plan token is gone.
        self.assertEqual(session.execution_state.phase, "idle")
        self.assertIsNone(session.execution_state.pending_mutation)
        self.assertIsNotNone(session.execution_state.last_failure)
        self.assertIn("division by zero", session.execution_state.last_failure.error)
        # Phase 7: consecutive_failures removed from ExecutionState.

        # The serialised dict must NOT carry any of the do-not-preserve keys.
        serialised = session.to_dict()
        self._assert_no_do_not_preserve_fields(serialised)

    def _assert_no_do_not_preserve_fields(self, payload):
        forbidden_substrings = (
            "approval_token",
            "approval_required",
            "approval_status",
            "current_plan_id",
            "current_plan_type",
            "current_plan_mode",
            "current_plan_status",
            "execution_plan_id",
            "execution_approval_token",
            "fallback_plan_id",
            "fallback_approval_token",
            "presented_plan_summary",
            "presented_plan_steps",
            "presented_plan_stages",
            "presented_plan_tools",
            "presented_context_reads",
            "current_stage_id",
            "execution_policy",
        )
        flat = json.dumps(payload)
        for needle in forbidden_substrings:
            self.assertNotIn(needle, flat, f"forbidden field {needle!r} survived migration")

    def test_store_load_auto_migrates_from_legacy_file_without_touching_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            legacy_dir = project_root / "runtime" / "sessions"
            legacy_dir.mkdir(parents=True)
            blend_path = "demo.blend"
            store = SessionV1Store(project_root=project_root)
            legacy_payload = _legacy_state_fixture()
            legacy_payload["blend_path"] = blend_path
            legacy_file = store.legacy_path(blend_path)
            legacy_file.write_text(json.dumps(legacy_payload), encoding="utf-8")
            legacy_mtime_before = legacy_file.stat().st_mtime

            session = store.load(blend_path)
            self.assertEqual(session.identity.schema_version, SCHEMA_VERSION)
            self.assertEqual(session.focus.blend_path, blend_path)
            self.assertEqual(session.focus.tree_name, "Geometry Nodes")

            # The legacy file must remain untouched.
            self.assertTrue(legacy_file.exists())
            self.assertEqual(legacy_file.stat().st_mtime, legacy_mtime_before)
            # And no v1 file should have been written by load() alone.
            self.assertFalse(store.has_v1_file(blend_path))

    def test_v1_file_takes_precedence_over_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            store = SessionV1Store(project_root=project_root)
            blend_path = "demo.blend"

            # Write a legacy file with one tree name.
            legacy_dir = project_root / "runtime" / "sessions"
            legacy_dir.mkdir(parents=True)
            legacy_payload = _legacy_state_fixture()
            legacy_payload["blend_path"] = blend_path
            legacy_payload["last_target_tree"] = "Legacy Tree"
            legacy_payload["session_memory"]["target_tree"] = "Legacy Tree"
            store.legacy_path(blend_path).write_text(json.dumps(legacy_payload), encoding="utf-8")

            # Write a v1 file with a different tree name.
            v1_session = Session.new(blend_path=blend_path)
            v1_session.update_focus(tree_name="V1 Tree")
            store.save(v1_session, blend_path)

            session = store.load(blend_path)
            self.assertEqual(session.focus.tree_name, "V1 Tree")

    def test_save_after_legacy_migration_writes_v1_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            store = SessionV1Store(project_root=project_root)
            blend_path = "demo.blend"
            (project_root / "runtime" / "sessions").mkdir(parents=True)
            legacy_payload = _legacy_state_fixture()
            legacy_payload["blend_path"] = blend_path
            store.legacy_path(blend_path).write_text(json.dumps(legacy_payload), encoding="utf-8")

            session = store.load(blend_path)
            store.save(session, blend_path)

            self.assertTrue(store.has_v1_file(blend_path))
            self.assertTrue(store.has_legacy_file(blend_path))


# ---------------------------------------------------------------------------
# Feature flag plumbing
# ---------------------------------------------------------------------------


class FeatureFlagPlumbingTests(unittest.TestCase):
    def test_load_structured_session_v1_returns_session_object(self):
        # The agent_runtime module imports a lot of Blender-aware modules at
        # import time, so we exercise the helper purely through the
        # SessionV1Store path used by the helper. This guards the contract
        # without requiring Blender to be importable.
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionV1Store(project_root=Path(tmp))
            session = store.load("demo.blend")
            self.assertIsInstance(session, Session)
            self.assertEqual(session.identity.schema_version, SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
