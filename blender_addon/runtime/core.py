"""Central Runtime — Phase 2 of REFATOR_PLAN.md.

This module hosts the single shared :class:`Runtime` that the in-Blender
socket bridge (``blender_addon/server.py``) calls into. Phase 2 lifts the
socket-path responsibilities out of the now-deleted ``RuntimeBridgeCore``
into this class while applying two long-standing bug fixes documented in
REFATOR_PLAN.md §11 Phase 2:

1. The literal ``"chatgpt"`` leftover that ``RuntimeBridgeCore`` used to
   stamp on every ``get_session_state`` view is gone — the runtime is
   Blender-centric and there is no second conversation surface.
2. ``set_modes`` no longer bumps the turn counter on every UI command.
   Turn counting is now exclusively the responsibility of the chat path
   (``runtime_turn.run_turn``), which already calls ``bump_turn_counter``
   once per real user turn.

:class:`blender_addon.session.SessionV1Store` is the canonical persisted
session. Flat-state operations are pure functions in :mod:`runtime.state_ops`.

The chat path (``AgentRuntime`` / ``runtime_turn``) is **not** rewritten in
Phase 2. ``AgentRuntime`` accepts an optional ``runtime: Runtime`` argument
so ``chat_ui`` can hand it the shared :class:`Runtime`, but the chat path
still drives the flat-state adapter directly. Phase 3 will move chat turns
onto :meth:`Runtime.run_turn` and retire ``AgentRuntime`` as a wrapper.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..operation_journal import OperationJournal
from ..tools.server_dispatch import RuntimeDispatcher
from ..safety_policy import SafetyContext, evaluate_tool_call
from ..session import BaselineBuilder, LastFailure
from . import state_ops
from .state_ops import default_state as _default_state


def _extract_tree_name(tool_input: dict[str, Any]) -> str:
    for key in ("tree_name", "target_tree"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_node_name(tool_input: dict[str, Any]) -> str:
    for key in ("node_name", "name", "node", "from_node", "old_name", "object_name"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _build_structural_index(tree_payload: dict[str, Any], *, dispatcher: RuntimeDispatcher) -> dict[str, Any]:
    nodes = tree_payload.get("nodes", []) if isinstance(tree_payload.get("nodes"), list) else []
    links = tree_payload.get("links", []) if isinstance(tree_payload.get("links"), list) else []
    interface = tree_payload.get("interface", {}) if isinstance(tree_payload.get("interface"), dict) else {}

    frames = [str(node.get("name", "")) for node in nodes if isinstance(node, dict) and node.get("type") == "NodeFrame"]
    group_nodes = [
        str(node.get("name", ""))
        for node in nodes
        if isinstance(node, dict) and str(node.get("type", "")).lower() in {"geometrynodegroup", "nodegroup"}
    ]
    key_nodes = [str(node.get("name", "")) for node in nodes if isinstance(node, dict)][:40]
    params: list[str] = []
    if isinstance(interface.get("inputs"), list):
        params = [str(inp.get("name", "")) for inp in interface.get("inputs", []) if isinstance(inp, dict)]
    return {
        "tree_name": str(tree_payload.get("name", "")),
        "node_count": int(tree_payload.get("node_count", len(nodes)) or 0),
        "link_count": len(links),
        "frames": [name for name in frames if name],
        "group_nodes": [name for name in group_nodes if name],
        "key_nodes": [name for name in key_nodes if name],
        "known_parameters": [name for name in params if name],
        "tree_hash": dispatcher._tree_hash(tree_payload),
        "updated_at": int(time.time()),
    }


def _state_focus_tree_name(state: dict[str, Any]) -> str:
    session_memory = state.get("session_memory") if isinstance(state.get("session_memory"), dict) else {}
    local_scope = state.get("local_scope") if isinstance(state.get("local_scope"), dict) else {}
    tree_name = (
        state.get("last_target_tree")
        or session_memory.get("target_tree")
        or local_scope.get("tree_name")
        or ""
    )
    return str(tree_name or "").strip()


def _known_parameters_from_state(state: dict[str, Any]) -> dict[str, Any]:
    known_parameters: dict[str, Any] = {}
    session_memory = state.get("session_memory") if isinstance(state.get("session_memory"), dict) else {}
    raw_changes = session_memory.get("last_parameter_changes")
    if not isinstance(raw_changes, list):
        return known_parameters
    for change in raw_changes:
        if not isinstance(change, dict):
            continue
        node_name = str(change.get("node") or change.get("name") or "").strip()
        if not node_name:
            continue
        known_parameters[node_name] = {
            "field": str(change.get("field") or ""),
            "value": change.get("value"),
            "source": "runtime_sync",
        }
    return known_parameters


def _open_questions_from_state(state: dict[str, Any]) -> list[str]:
    session_memory = state.get("session_memory") if isinstance(state.get("session_memory"), dict) else {}
    last_hypothesis = str(session_memory.get("last_hypothesis") or "").strip()
    if not last_hypothesis:
        return []
    return [f"hypothesis_to_revisit: {last_hypothesis[:200]}"]


def _phase_from_state(state: dict[str, Any]) -> str:
    if str(state.get("last_failure", "") or "").strip():
        return "failed"
    return "idle"


# Phase 2 final state:
# Runtime is the live bridge runtime, AgentRuntime can share its foundation,
# and the flat dict now moves through explicit legacy-state helpers while the
# V1 session continues to converge toward the canonical store.
class Runtime:
    """Single shared runtime for socket-path callers (Phase 2).

    Replaces ``RuntimeBridgeCore``. Public surface mirrors what the
    in-Blender socket bridge needs:

    * :meth:`get_session_state` — load the legacy session for a blend file
      and return a state view enriched with derived flags.
    * :meth:`set_modes` — apply UI/MCP mode toggles, approval decisions,
      session lifecycle commands, and control-owner enforcement.
    * :meth:`execute_tool_call` — run a single tool call through safety
      policy + the runtime dispatcher and persist the resulting state.

    A v1 :class:`blender_addon.session.SessionV1Store` is constructed
    alongside the legacy helper store; ``v1_session_for(blend_path)`` is the
    persisted source of truth while runtime callers still exchange flat dicts.
    """

    def __init__(
        self,
        project_root: Path,
        *,
        journal: OperationJournal | None = None,
        dispatcher: RuntimeDispatcher | None = None,
    ) -> None:
        self.project_root = Path(project_root)
        self.dispatcher = dispatcher or RuntimeDispatcher()
        self.journal = journal or OperationJournal(project_root=self.project_root)
        self._observed_sessions: set[str] = set()

        # v1 structured-session store, loaded lazily so this module pays no
        # import cost when the schema package is unavailable (e.g. during the
        # legacy unit-test runs that don't import blender_addon.session).
        self._v1_store: Any = None
        # Onda 3: persisted high-level session_state store. Loaded lazily.
        self._session_state_store: Any = None
        # Journal session start is deferred until a real blend_path is known.
        # _ensure_session() on the journal will auto-create a fallback session
        # if any event is written before _start_journal_session() is called.
        self._journal_session_started: bool = False

    # ------------------------------------------------------------------
    # v1 structured-session bridge
    # ------------------------------------------------------------------

    def _start_journal_session(self, session_id: str, blend_file: str) -> None:
        """Start the journal session once a real blend_path is available."""
        if not self._journal_session_started:
            self._journal_session_started = True
            self.journal.start_session(session_id, blend_file=blend_file)

    def _get_v1_store(self) -> Any:
        if self._v1_store is None:
            from ..session import SessionV1Store

            self._v1_store = SessionV1Store(project_root=self.project_root)
        return self._v1_store

    def v1_session_for(self, blend_path: str | None = None) -> Any:
        """Return the structured v1 :class:`Session` for ``blend_path``.

        Phase 2 helper. The legacy store is still authoritative for live
        runtime decisions; this is exposed so tests and Phase 3 callers can
        observe the v1 schema converging in parallel.
        """
        resolved = self._resolve_blend_path(blend_path)
        # DIAG: (only log when resolved path changes to avoid draw spam)
        import sys
        _prev = getattr(self, "_diag_last_resolved", None)
        if resolved != _prev:
            self._diag_last_resolved = resolved  # type: ignore[attr-defined]
            print(f"[DIAG/core.v1_session_for] called blend_path={blend_path!r}  resolved={resolved!r}", file=sys.stderr, flush=True)
        result = self._get_v1_store().load(resolved)
        _msgs = getattr(getattr(result, "history", None), "messages", [])
        if resolved != _prev:
            print(f"[DIAG/core.v1_session_for] returned session msg_count={len(_msgs)}", file=sys.stderr, flush=True)
        # Anchor the journal session to the real blend_path on first resolution.
        if resolved:
            _sid = getattr(getattr(result, "identity", None), "session_id", None) or "runtime"
            self._start_journal_session(_sid, blend_file=resolved)
        return result

    def load_runtime_state(self, blend_path: str | None = None) -> dict[str, Any]:
        """Return the flat runtime-state adapter projected from the V1 session."""
        resolved = self._resolve_blend_path(blend_path)
        return self._runtime_state_from_v1(resolved)

    def save_v1_session(self, session: Any) -> Path:
        """Persist a structured v1 :class:`Session`. Phase 2 helper."""
        return self._get_v1_store().save(session)

    def set_work_cycle_phase(self, blend_path: str | None, phase: str) -> None:
        """Persist a work_cycle_phase transition. Called from UI operators on the main thread."""
        from ..session.schema import WORK_CYCLE_PHASES
        if phase not in WORK_CYCLE_PHASES:
            return
        resolved = self._resolve_blend_path(blend_path)
        session = self._get_v1_store().load(resolved)
        try:
            session.execution_state.set_work_cycle_phase(phase)
        except Exception:
            session.execution_state.work_cycle_phase = phase
        self._get_v1_store().save(session)

    def append_chat_message(
        self,
        session_id: str,
        *,
        role: str,
        content: str,
        ts: str = "",
        turn_class: str = "",
    ) -> None:
        """Write one chat message to the JSONL immediately (before V1 save)."""
        self._get_v1_store().append_chat_message(
            session_id, role=role, content=content, ts=ts, turn_class=turn_class
        )

    def clear_chat_history(self, session_id: str) -> None:
        """Delete the chat JSONL for a session (Clear button path)."""
        self._get_v1_store().clear_chat_history(session_id)

    # ------------------------------------------------------------------
    # Onda 3: persisted session_state
    # ------------------------------------------------------------------

    def _get_session_state_store(self) -> Any:
        if self._session_state_store is None:
            from ..session import SessionStateStore

            self._session_state_store = SessionStateStore(project_root=self.project_root)
        return self._session_state_store

    def read_persisted_session_state(self, session_id: str) -> str:
        """Return the persisted session_state for ``session_id`` (or "")."""
        if not session_id:
            return ""
        return self._get_session_state_store().read_state(session_id)

    def persist_session_state(
        self,
        session_id: str,
        *,
        next_state: str,
        previous_state: str = "",
        blend_path: str = "",
    ) -> None:
        """Write the next session_state file. Logs ``state_transition`` on change."""
        if not session_id:
            return
        try:
            self._get_session_state_store().write(
                session_id,
                session_state=next_state,
                blend_path=blend_path,
                previous_state=previous_state,
            )
        except Exception as exc:
            try:
                self.journal.log_runtime_event(
                    event_type="session_state_persist_error",
                    payload={"session_id": session_id, "error": str(exc)},
                    status="warning",
                )
            except Exception:
                pass
            return

        if previous_state != next_state:
            try:
                self.journal.log_runtime_event(
                    event_type="state_transition",
                    payload={
                        "session_id": session_id,
                        "previous_state": previous_state or "",
                        "next_state": next_state,
                        "blend_path": blend_path,
                    },
                )
            except Exception:
                pass

    def reattach_session(self, old_blend_path: str | None, new_blend_path: str | None) -> Path | None:
        """Rebind a persisted session from one blend path to another."""
        return self._get_v1_store().reattach_session(
            self._resolve_blend_path(old_blend_path),
            self._resolve_blend_path(new_blend_path),
        )

    def reattach_session_result(self, old_blend_path: str | None, new_blend_path: str | None) -> dict[str, Any]:
        """Return an explicit reattach outcome for save/save-as handling."""
        return self._get_v1_store().reattach_session_result(
            self._resolve_blend_path(old_blend_path),
            self._resolve_blend_path(new_blend_path),
        )

    def diagnose_v1_session(self, blend_path: str | None = None) -> dict[str, Any]:
        """Return a diagnostic view of the active V1 session and sibling candidates."""
        resolved = self._resolve_blend_path(blend_path)
        return self._get_v1_store().diagnose_v1_session(resolved)

    def archive_and_reset_session(self, blend_path: str | None = None) -> dict[str, Any]:
        """Explicitly archive the current V1 session file and replace it with a clean one."""
        resolved = self._resolve_blend_path(blend_path)
        result = self._get_v1_store().archive_and_reset_v1_session(resolved)
        new_session_id = str(result.get("new_session_id") or "")
        if new_session_id:
            self._start_journal_session(new_session_id, blend_file=resolved)
        try:
            self.journal.log_runtime_event(
                event_type="session_archived_and_reset",
                payload={
                    "blend_path": resolved,
                    "current_session_file": str(result.get("current_session_file") or ""),
                    "archive_file": str(result.get("archive_file") or ""),
                    "archived": bool(result.get("archived", False)),
                    "new_session_id": new_session_id,
                    "prior_session_id": str(
                        (result.get("archived_session") or {}).get("session_id", "")
                        if isinstance(result.get("archived_session"), dict)
                        else ""
                    ),
                },
                status="success",
            )
        except Exception:
            pass
        return result

    def _apply_runtime_state_to_v1_session(self, session: Any, legacy_state: dict[str, Any], *, blend_path: str) -> None:
        object_name = session.focus.object_name
        modifier_name = session.focus.modifier_name
        tree_name = _state_focus_tree_name(legacy_state) or session.focus.tree_name
        session.update_focus(
            blend_path=blend_path,
            object_name=object_name,
            modifier_name=modifier_name,
            tree_name=tree_name or None,
        )
        session.ui_state.debug_mode = bool(legacy_state.get("debug_mode", False))
        session.ui_state.explicit_override_mode = bool(legacy_state.get("explicit_override_mode", False))
        session.ui_state.mcp_write_enabled = bool(legacy_state.get("mcp_write_enabled", False))
        if hasattr(session.ui_state, "simulate_bridge_failure"):
            session.ui_state.simulate_bridge_failure = bool(legacy_state.get("simulate_bridge_failure", False))
        session.ui_state.session_active = bool(legacy_state.get("agent_session_active", False))
        try:
            session.operational_state.turn_counter = int(legacy_state.get("turn_counter") or 0)
        except Exception:
            session.operational_state.turn_counter = 0
        session.operational_state.session_memory = (
            dict(legacy_state.get("session_memory")) if isinstance(legacy_state.get("session_memory"), dict) else {}
        )
        session.operational_state.local_scope = (
            dict(legacy_state.get("local_scope")) if isinstance(legacy_state.get("local_scope"), dict) else {}
        )
        session.operational_state.structural_index = (
            dict(legacy_state.get("structural_index")) if isinstance(legacy_state.get("structural_index"), dict) else {}
        )
        session.operational_state.tree_structural_memory = (
            dict(legacy_state.get("tree_structural_memory"))
            if isinstance(legacy_state.get("tree_structural_memory"), dict)
            else {}
        )
        session.operational_state.tree_change_markers = (
            dict(legacy_state.get("tree_change_markers"))
            if isinstance(legacy_state.get("tree_change_markers"), dict)
            else {}
        )
        session.operational_state.recent_actions = [
            dict(item)
            for item in (legacy_state.get("recent_actions") or [])
            if isinstance(item, dict)
        ]
        session.operational_state.risky_events = [
            dict(item)
            for item in (legacy_state.get("risky_events") or [])
            if isinstance(item, dict)
        ]
        session.operational_state.last_scene_summary = (
            dict(legacy_state.get("last_scene_summary"))
            if isinstance(legacy_state.get("last_scene_summary"), dict)
            else {}
        )
        session.operational_state.last_gn_summary = (
            dict(legacy_state.get("last_gn_summary")) if isinstance(legacy_state.get("last_gn_summary"), dict) else {}
        )

        last_failure_text = str(legacy_state.get("last_failure", "") or "").strip()
        if last_failure_text:
            session.execution_state.last_failure = LastFailure(
                tool="",
                error=last_failure_text,
                cause="mirrored_from_legacy_runtime",
                suggested_alternative="",
            )
        else:
            session.execution_state.last_failure = None

        session.execution_state.set_phase(_phase_from_state(legacy_state))

    def _apply_tool_result_to_v1_session(
        self,
        session: Any,
        legacy_state: dict[str, Any],
        *,
        canonical_tool: str | None = None,
        raw: dict[str, Any] | None = None,
        tool_input: dict[str, Any] | None = None,
    ) -> None:
        if not canonical_tool or not isinstance(raw, dict):
            return

        status = str(raw.get("status", "success") or "success")
        if status != "success":
            error = str(raw.get("error", "") or "").strip()
            if error:
                session.execution_state.last_failure = LastFailure(
                    tool=canonical_tool,
                    error=error,
                    cause="runtime_tool_error",
                    suggested_alternative="",
                )
                session.execution_state.set_phase("failed")
            return

        result = raw.get("result", {}) if isinstance(raw.get("result"), dict) else {}
        if canonical_tool in {"analyze_gn_state"} and result:
            focus_tree = str(result.get("name", "") or _extract_tree_name(tool_input or {})).strip()
            if focus_tree:
                session.update_focus(
                    blend_path=session.focus.blend_path,
                    object_name=session.focus.object_name,
                    modifier_name=session.focus.modifier_name,
                    tree_name=focus_tree,
                )
            subgraph_index = session.operational_state.structural_index
            builder = BaselineBuilder(session.baseline_workspace)
            builder.rebuild_from_summary(
                result,
                built_from="auto",
                subgraph_index=subgraph_index if isinstance(subgraph_index, dict) else None,
                known_parameters=_known_parameters_from_state(legacy_state),
                open_questions=_open_questions_from_state(legacy_state),
            )
            return

        if canonical_tool == "get_changes_since_last_turn":
            if int(result.get("changes_count", 0) or 0) > 0:
                session.mark_baseline_stale()
            return

        if self.journal.is_mutation(canonical_tool):
            session.mark_baseline_stale()

    def _sync_v1_session(
        self,
        blend_path: str | None,
        legacy_state: dict[str, Any],
        *,
        canonical_tool: str | None = None,
        raw: dict[str, Any] | None = None,
        tool_input: dict[str, Any] | None = None,
    ) -> Path | None:
        if not isinstance(legacy_state, dict):
            return None
        resolved = self._resolve_blend_path(blend_path or str(legacy_state.get("blend_path", "") or ""))
        v1_store = self._get_v1_store()
        # Capture whether the V1 file is being created for the first time so we
        # can emit a one-shot journal event if legacy approval state was discarded
        # during migration (set by migrate_legacy_state via lifecycle.add_note).
        _v1_was_new = not v1_store.v1_path(resolved).exists()
        session = v1_store.load(resolved)
        if _v1_was_new:
            try:
                _notes = list(getattr(getattr(session, "lifecycle", None), "notes", None) or [])
                if any("legacy_approval_state_discarded" in (_n or "") for _n in _notes):
                    self.journal.log_runtime_event(
                        event_type="legacy_approval_state_discarded",
                        payload={"blend_path": resolved, "source": "session_migration"},
                        status="warning",
                    )
            except Exception:
                pass
        self._apply_runtime_state_to_v1_session(session, legacy_state, blend_path=resolved)
        self._apply_tool_result_to_v1_session(
            session,
            legacy_state,
            canonical_tool=canonical_tool,
            raw=raw,
            tool_input=tool_input,
        )
        return v1_store.save(session, resolved)

    # ------------------------------------------------------------------
    # Helpers (lifted from RuntimeBridgeCore)
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_blend_path(blend_path: str | None) -> str:
        if blend_path:
            return blend_path
        try:
            import bpy  # type: ignore

            return bpy.data.filepath or ""
        except Exception:
            return ""

    @staticmethod
    def _overlay_v1_session_view(
        state: dict[str, Any],
        session: Any,
        *,
        resolved: str,
    ) -> dict[str, Any]:
        view = dict(state)
        identity = getattr(session, "identity", None)
        focus = getattr(session, "focus", None)
        ui_state = getattr(session, "ui_state", None)
        execution_state = getattr(session, "execution_state", None)
        operational_state = getattr(session, "operational_state", None)
        history = getattr(session, "history", None)

        if identity is not None:
            view["session_id"] = str(getattr(identity, "session_id", "") or view.get("session_id", ""))
            view["updated_at"] = str(getattr(identity, "last_active_at", "") or view.get("updated_at", ""))

        if focus is not None:
            view["blend_path"] = str(getattr(focus, "blend_path", "") or resolved)
            view["last_target_tree"] = str(getattr(focus, "tree_name", "") or view.get("last_target_tree", ""))

        if ui_state is not None:
            view["debug_mode"] = bool(getattr(ui_state, "debug_mode", False))
            view["explicit_override_mode"] = bool(getattr(ui_state, "explicit_override_mode", False))
            view["mcp_write_enabled"] = bool(getattr(ui_state, "mcp_write_enabled", False))
            view["simulate_bridge_failure"] = bool(getattr(ui_state, "simulate_bridge_failure", False))
            view["agent_session_active"] = bool(getattr(ui_state, "session_active", False))

        if execution_state is not None:
            last_failure = getattr(execution_state, "last_failure", None)
            view["last_failure"] = str(getattr(last_failure, "error", "") or "")

        if operational_state is not None:
            view["turn_counter"] = int(getattr(operational_state, "turn_counter", 0) or 0)
            view["session_memory"] = (
                dict(getattr(operational_state, "session_memory", {}))
                if isinstance(getattr(operational_state, "session_memory", {}), dict)
                else {}
            )
            view["local_scope"] = (
                dict(getattr(operational_state, "local_scope", {}))
                if isinstance(getattr(operational_state, "local_scope", {}), dict)
                else {}
            )
            view["structural_index"] = (
                dict(getattr(operational_state, "structural_index", {}))
                if isinstance(getattr(operational_state, "structural_index", {}), dict)
                else {}
            )
            view["tree_structural_memory"] = (
                dict(getattr(operational_state, "tree_structural_memory", {}))
                if isinstance(getattr(operational_state, "tree_structural_memory", {}), dict)
                else {}
            )
            view["tree_change_markers"] = (
                dict(getattr(operational_state, "tree_change_markers", {}))
                if isinstance(getattr(operational_state, "tree_change_markers", {}), dict)
                else {}
            )
            view["recent_actions"] = [
                dict(item)
                for item in getattr(operational_state, "recent_actions", [])
                if isinstance(item, dict)
            ]
            view["risky_events"] = [
                dict(item)
                for item in getattr(operational_state, "risky_events", [])
                if isinstance(item, dict)
            ]
            view["last_scene_summary"] = (
                dict(getattr(operational_state, "last_scene_summary", {}))
                if isinstance(getattr(operational_state, "last_scene_summary", {}), dict)
                else {}
            )
            view["last_gn_summary"] = (
                dict(getattr(operational_state, "last_gn_summary", {}))
                if isinstance(getattr(operational_state, "last_gn_summary", {}), dict)
                else {}
            )

        raw_messages = getattr(history, "messages", []) if history is not None else []
        if isinstance(raw_messages, list):
            view["chat_history"] = [
                {
                    "role": str(getattr(message, "role", "") or ""),
                    "text": str(getattr(message, "content", "") or ""),
                    "timestamp": str(getattr(message, "ts", "") or ""),
                }
                for message in raw_messages
                if str(getattr(message, "role", "") or "").strip()
                and str(getattr(message, "content", "") or "").strip()
            ]
        if isinstance(raw_messages, list) and raw_messages and not int(view.get("turn_counter", 0) or 0):
            view["turn_counter"] = len(raw_messages)

        return view

    def _runtime_state_from_v1(self, resolved: str) -> dict[str, Any]:
        state = _default_state(resolved)
        session = self.v1_session_for(resolved)
        return self._overlay_v1_session_view(state, session, resolved=resolved)

    def _load_runtime_state(self, resolved: str) -> dict[str, Any]:
        return self._runtime_state_from_v1(resolved)

    def _persist_runtime_state(
        self,
        resolved: str,
        state: dict[str, Any],
        *,
        canonical_tool: str | None = None,
        raw: dict[str, Any] | None = None,
        tool_input: dict[str, Any] | None = None,
    ) -> Path:
        path = self._sync_v1_session(
            resolved,
            state,
            canonical_tool=canonical_tool,
            raw=raw,
            tool_input=tool_input,
        )
        if path is None:
            return self.save_v1_session(self.v1_session_for(resolved))
        return path

    def persist_runtime_state(
        self,
        state: dict[str, Any],
        blend_path: str | None = None,
        *,
        canonical_tool: str | None = None,
        raw: dict[str, Any] | None = None,
        tool_input: dict[str, Any] | None = None,
    ) -> Path:
        resolved = self._resolve_blend_path(blend_path or str(state.get("blend_path", "") or ""))
        return self._persist_runtime_state(
            resolved,
            state,
            canonical_tool=canonical_tool,
            raw=raw,
            tool_input=tool_input,
        )

    @staticmethod
    def _normalize_control_source(control_source: str | None) -> str:
        source = str(control_source or "").strip()
        return source or "mcp"

    @staticmethod
    def _new_plan_id() -> str:
        return f"plan-{uuid4().hex[:10]}"

    @staticmethod
    def _new_approval_token() -> str:
        return f"appr-{uuid4().hex[:12]}"

    @staticmethod
    def _detect_state_inconsistencies(state: dict[str, Any]) -> list[str]:
        issues: list[str] = []
        plan_id = str(state.get("current_plan_id", "") or "").strip()
        plan_status = str(state.get("current_plan_status", "none") or "none")
        approval_required = bool(state.get("approval_required", False))
        approval_status = str(state.get("approval_status", "none") or "none")
        approval_token = str(state.get("approval_token", "") or "").strip()
        stages = state.get("presented_plan_stages", []) if isinstance(state.get("presented_plan_stages"), list) else []
        raw_stage_idx = state.get("current_stage_index", -1)
        try:
            stage_idx = int(raw_stage_idx)
        except Exception:
            stage_idx = -1

        if approval_required and (not plan_id or not approval_token):
            issues.append("approval_required_missing_plan_or_token")
        if approval_status == "granted" and plan_status not in {"approved", "executing", "completed"}:
            issues.append("approval_granted_with_invalid_plan_status")
        if plan_status in {"presented", "approved", "executing"} and not plan_id:
            issues.append("active_plan_status_without_plan_id")
        if stages and (stage_idx < 0 or stage_idx >= len(stages)):
            issues.append("current_stage_index_out_of_bounds")
        if not stages and str(state.get("current_stage_id", "") or "").strip():
            issues.append("current_stage_id_without_stage_list")
        return issues

    @staticmethod
    def _infer_resumed_session_state(state: dict[str, Any], inconsistencies: list[str]) -> str:
        turn_counter = int(state.get("turn_counter", 0) or 0)
        plan_id = str(state.get("current_plan_id", "") or "").strip()
        approval_required = bool(state.get("approval_required", False))
        approval_status = str(state.get("approval_status", "none") or "none")
        recent_actions = state.get("recent_actions", []) if isinstance(state.get("recent_actions"), list) else []
        session_memory = state.get("session_memory", {}) if isinstance(state.get("session_memory"), dict) else {}
        has_operational_memory = bool(
            str(session_memory.get("last_goal", "") or "").strip()
            or str(session_memory.get("target_tree", "") or "").strip()
            or bool(session_memory.get("relevant_nodes", []))
            or bool(session_memory.get("decisions", []))
        )
        has_history = bool(
            turn_counter > 0
            or state.get("last_task_class")
            or state.get("last_plan_summary")
            or recent_actions
            or has_operational_memory
        )
        if not has_history:
            return "new_session"
        if inconsistencies:
            return "resumed_with_inconsistent_state"
        if plan_id and approval_required and approval_status == "pending":
            return "resumed_with_approval_pending"
        if plan_id:
            return "resumed_with_plan_pending"
        return "resumed_without_pending_plan"

    @staticmethod
    def _infer_next_action_expected(state: dict[str, Any], resumed_state: str) -> str:
        if not bool(state.get("agent_session_active", False)):
            return "start_or_continue_session"
        if resumed_state == "resumed_with_inconsistent_state":
            return "reset_transient_state_or_rebuild_plan"
        if bool(state.get("approval_required", False)) and str(state.get("approval_status", "none") or "none") == "pending":
            return "approve_or_deny_current_plan"
        if str(state.get("current_plan_status", "none") or "none") == "approved":
            return "execute_approved_stage"
        if str(state.get("current_plan_status", "none") or "none") == "executing":
            return "wait_execution_or_check_journal"
        return "send_new_goal"

    @staticmethod
    def _set_current_stage_status(state: dict[str, Any], stage_status: str) -> None:
        stages = state.get("presented_plan_stages")
        if not isinstance(stages, list):
            return
        raw_idx = state.get("current_stage_index", -1)
        try:
            idx = int(raw_idx)
        except Exception:
            idx = -1
        if idx < 0 or idx >= len(stages):
            return
        stage = stages[idx]
        if isinstance(stage, dict):
            stage["stage_status"] = str(stage_status or "pending")
            state["current_stage_status"] = str(stage_status or "pending")

    def _rebuild_plan_from_state(self, state: dict[str, Any], *, source: str) -> tuple[bool, str]:
        summary = str(state.get("presented_plan_summary", "") or state.get("last_plan_summary", "") or "").strip()
        tools = state.get("presented_plan_tools", [])
        if not isinstance(tools, list):
            tools = []
        reads = state.get("presented_context_reads", [])
        if not isinstance(reads, list):
            reads = []
        stages = state.get("presented_plan_stages", [])
        if not isinstance(stages, list):
            stages = []

        if not summary and not tools and not stages:
            return False, "No plan context available to rebuild."

        if not stages:
            stages = [
                {
                    "stage_id": f"stage-{uuid4().hex[:8]}",
                    "stage_index": 1,
                    "stage_title": "Recovered Stage",
                    "stage_goal": summary or "Recovered execution stage",
                    "stage_tools": [str(t) for t in tools[:6]],
                    "fallback_possible": bool(state.get("presented_fallback_possible", False)),
                    "execute_code_risk": bool(state.get("presented_execute_code_risk", False)),
                    "impact": "restored_from_previous_plan",
                    "approval_required": True,
                    "stage_status": "pending",
                }
            ]

        stage_idx = 0
        stage = stages[stage_idx] if stages and isinstance(stages[stage_idx], dict) else {}
        plan_id = self._new_plan_id()
        approval_token = self._new_approval_token()

        state["current_plan_id"] = plan_id
        state["current_plan_status"] = "presented"
        state["approval_required"] = True
        state["approval_token"] = approval_token
        state["approval_status"] = "pending"
        state["approval_source"] = ""
        state["presented_plan_summary"] = summary or "Recovered plan from previous pending state."
        state["presented_plan_tools"] = [str(t) for t in tools[:10]]
        state["presented_context_reads"] = [str(t) for t in reads[:8]]
        state["presented_plan_steps"] = [str(s.get("stage_goal", "")) for s in stages if isinstance(s, dict)][:8]
        state["presented_plan_impacts"] = [str(s.get("impact", "")) for s in stages if isinstance(s, dict)][:8]
        state["presented_plan_stages"] = stages
        state["current_stage_index"] = stage_idx
        state["current_stage_id"] = str(stage.get("stage_id", "") or "")
        state["current_stage_status"] = "pending"
        state["runtime_phase"] = "awaiting_user_approval"
        state["execution_plan_id"] = ""
        state["execution_approval_token"] = ""

        self.journal.log_runtime_event(
            event_type="plan_rebuilt_after_invalid_state",
            payload={
                "plan_id": plan_id,
                "approval_token": approval_token,
                "source": source,
                "current_stage_id": state.get("current_stage_id", ""),
            },
            status="warning",
        )
        self.journal.log_runtime_event(
            event_type="stage_presented_to_user",
            payload={
                "plan_id": plan_id,
                "stage_id": state.get("current_stage_id", ""),
                "stage_index": stage_idx + 1,
                "stage_title": stage.get("stage_title", ""),
                "stage_tools": stage.get("stage_tools", []),
                "impact": stage.get("impact", ""),
                "fallback_possible": stage.get("fallback_possible", False),
                "execute_code_risk": stage.get("execute_code_risk", False),
            },
            status="info",
        )
        self.journal.log_runtime_event(
            event_type="approval_requested",
            payload={"plan_id": plan_id, "approval_token": approval_token, "reason": "rebuild_plan"},
            status="blocked",
        )
        return True, ""

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    def get_session_state(self, *, blend_path: str | None = None) -> dict[str, Any]:
        resolved = self._resolve_blend_path(blend_path)
        state = self._load_runtime_state(resolved)
        inconsistencies = self._detect_state_inconsistencies(state)
        resumed_state = self._infer_resumed_session_state(state, inconsistencies)
        next_action_expected = self._infer_next_action_expected(state, resumed_state)
        active_session = bool(state.get("agent_session_active", False))
        persisted_simple_state = str(state.get("session_state", "no_session") or "no_session")
        if not active_session:
            simple_state = "no_session"
        elif persisted_simple_state in {"active", "paused"}:
            simple_state = persisted_simple_state
        else:
            simple_state = "active"
        state["session_state"] = simple_state
        if not active_session:
            state["session_resumed_notice"] = ""
        observed_key = f"{resolved}::{state.get('session_id', '')}"
        if observed_key not in self._observed_sessions and resumed_state != "new_session":
            self._observed_sessions.add(observed_key)
            if active_session:
                state["session_state"] = "paused"
                state["session_resumed_notice"] = "Sessao retomada automaticamente."
                simple_state = "paused"
            self.journal.log_runtime_event(
                event_type="session_resumed",
                payload={
                    "session_id": state.get("session_id", ""),
                    "resumed_session_state": resumed_state,
                    "current_plan_id": state.get("current_plan_id", ""),
                },
                status="info",
            )
            self.journal.log_runtime_event(
                event_type="resumed_session_state",
                payload={
                    "resumed_session_state": resumed_state,
                    "approval_pending": bool(state.get("approval_required", False))
                    and str(state.get("approval_status", "none") or "none") == "pending",
                    "plan_pending": bool(str(state.get("current_plan_id", "") or "").strip())
                    and str(state.get("current_plan_status", "none") or "none") in {"presented", "approved", "executing"},
                    "state_inconsistencies": inconsistencies,
                    "next_action_expected": next_action_expected,
                },
                status="info" if not inconsistencies else "warning",
            )

        state_view = dict(state)
        state_view["resumed_session_state"] = resumed_state
        state_view["session_resumed"] = resumed_state != "new_session"
        state_view["session_state"] = simple_state
        state_view["session_resumed_notice"] = str(state.get("session_resumed_notice", "") or "")
        # REFATOR_PLAN.md §11 Phase 2 bug fix: the literal "chatgpt" leftover
        # has been removed. The runtime is Blender-centric (decision §1) — there
        # is no second conversation surface to advertise.
        state_view["backend_session_kind"] = "technical_runtime"
        state_view["legacy_chat_history_enabled"] = bool(state.get("legacy_chat_history_enabled", False))
        state_view["control_owner_mode"] = (
            "enforced" if bool(state.get("control_owner_enforced", False)) else "advisory"
        )
        state_view["state_inconsistencies"] = inconsistencies
        state_view["next_action_expected"] = next_action_expected
        state_view["approval_pending"] = bool(state.get("approval_required", False)) and str(
            state.get("approval_status", "none") or "none"
        ) == "pending"
        state_view["plan_pending"] = bool(str(state.get("current_plan_id", "") or "").strip()) and str(
            state.get("current_plan_status", "none") or "none"
        ) in {"presented", "approved", "executing"}
        journal_paths = self.journal.get_paths()
        state_view["_runtime_project_root"] = str(self.project_root)
        state_view["_runtime_journal_base_dir"] = journal_paths.get("base_dir", "")
        state_view["_runtime_journal_run_file"] = journal_paths.get("run_file", "")
        state_view["_runtime_journal_session_file"] = journal_paths.get("session_file", "")
        state_view["_runtime_journal_index_file"] = journal_paths.get("index_file", "")
        state_view["simulate_bridge_failure"] = bool(state.get("simulate_bridge_failure", False))
        return state_view

    def set_modes(
        self,
        *,
        blend_path: str | None = None,
        debug_mode: bool | None = None,
        explicit_override_mode: bool | None = None,
        mcp_write_enabled: bool | None = None,
        agent_session_active: bool | None = None,
        reset_session_memory: bool = False,
        start_new_session: bool = False,
        approval_plan_id: str | None = None,
        approval_token: str | None = None,
        approval_decision: str | None = None,
        approval_source: str | None = None,
        clear_pending_plan: bool = False,
        clear_approval_state: bool = False,
        reset_transient_state: bool = False,
        rebuild_plan: bool = False,
        control_source: str | None = None,
        claim_control_owner: bool = False,
        force_control_owner: bool = False,
        control_owner_enforced: bool | None = None,
        clear_control_owner: bool = False,
        drafting_mode: bool | None = None,
        simulate_bridge_failure: bool | None = None,
    ) -> dict[str, Any]:
        resolved = self._resolve_blend_path(blend_path)
        state = self._load_runtime_state(resolved)
        # REFATOR_PLAN.md §11 Phase 2 bug fix: turn counting belongs to the
        # chat path (``runtime_turn.run_turn``), which fires once per real
        # user turn. Bumping here on every UI command (mode toggle, claim
        # control, start session, …) inflated the counter and corrupted
        # downstream "is this a fresh session?" heuristics.
        source = self._normalize_control_source(control_source)
        session_id_before = str(state.get("session_id", "") or "")
        was_session_active = bool(state.get("agent_session_active", False))
        changed_fields = [
            name
            for name, value in {
                "debug_mode": debug_mode,
                "explicit_override_mode": explicit_override_mode,
                "mcp_write_enabled": mcp_write_enabled,
                "agent_session_active": agent_session_active,
                "approval_plan_id": approval_plan_id,
                "approval_token": approval_token,
                "approval_decision": approval_decision,
                "start_new_session": start_new_session,
                "clear_pending_plan": clear_pending_plan,
                "clear_approval_state": clear_approval_state,
                "reset_transient_state": reset_transient_state,
                "rebuild_plan": rebuild_plan,
                "control_owner_enforced": control_owner_enforced,
                "clear_control_owner": clear_control_owner,
                "simulate_bridge_failure": simulate_bridge_failure,
            }.items()
            if value is not None and value is not False
        ]
        if reset_session_memory:
            changed_fields.append("reset_session_memory")

        if debug_mode is not None:
            state_ops.set_debug_mode(state, debug_mode)
        if explicit_override_mode is not None:
            state_ops.set_override_mode(state, explicit_override_mode)
        if mcp_write_enabled is not None:
            state_ops.set_mcp_write_enabled(state, mcp_write_enabled)
        if simulate_bridge_failure is not None:
            state["simulate_bridge_failure"] = bool(simulate_bridge_failure)
            self.journal.log_runtime_event(
                event_type="simulate_bridge_failure_set",
                payload={"enabled": bool(simulate_bridge_failure), "source": source},
                status="warning" if bool(simulate_bridge_failure) else "info",
            )
        if start_new_session:
            state_ops.begin_new_session(state)
            self.journal.start_session(state.get("session_id", "runtime"), blend_file=resolved)
            self.journal.log_runtime_event(
                event_type="session_created",
                payload={
                    "source": source,
                    "previous_session_id": session_id_before,
                    "session_id": state.get("session_id", ""),
                    "journal_run_file": self.journal.get_paths().get("run_file", ""),
                    "journal_session_file": self.journal.get_paths().get("session_file", ""),
                },
                status="success",
            )
            self.journal.log_runtime_event(
                event_type="session_started",
                payload={
                    "source": source,
                    "previous_session_id": session_id_before,
                    "session_id": state.get("session_id", ""),
                    "journal_run_file": self.journal.get_paths().get("run_file", ""),
                    "journal_session_file": self.journal.get_paths().get("session_file", ""),
                },
                status="success",
            )
            self.journal.log_runtime_event(
                event_type="session_state_reset",
                payload={"source": source, "reason": "start_new_session"},
                status="info",
            )
        if agent_session_active is not None:
            state["agent_session_active"] = bool(agent_session_active)
            if was_session_active and not bool(state.get("agent_session_active", False)):
                state_ops.reset_session_memory(state)
                state["last_task_class"] = ""
                state["last_routing_reason"] = ""
                state["last_target_tree"] = ""
                state["last_plan_summary"] = ""
                state["last_plan_gate"] = {}
                state["last_turn_tools"] = []
                self.journal.log_runtime_event(
                    event_type="session_ended",
                    payload={
                        "source": source,
                        "session_id": session_id_before,
                        "next_session_state": "no_session",
                        "state_cleared": True,
                    },
                    status="success",
                )
        if bool(state.get("agent_session_active", False)) and not start_new_session:
            if str(state.get("runtime_phase", "idle") or "idle") == "executing":
                state["session_state"] = "active"
            else:
                state["session_state"] = "paused"
        if not bool(state.get("agent_session_active", False)):
            state["session_state"] = "no_session"
            state["session_resumed_notice"] = ""
        if reset_session_memory:
            state_ops.reset_session_memory(state)
            if bool(state.get("agent_session_active", False)):
                state["session_state"] = "active"
            self.journal.log_runtime_event(
                event_type="session_state_reset",
                payload={"source": source, "reason": "reset_session_memory"},
                status="warning",
            )
        if clear_pending_plan:
            self.journal.log_runtime_event(
                event_type="pending_plan_cleared",
                payload={"source": source},
                status="warning",
            )
        if clear_approval_state:
            self.journal.log_runtime_event(
                event_type="approval_state_cleared",
                payload={"source": source},
                status="warning",
            )
        if reset_transient_state:
            state_ops.reset_transient_state(state)
            self.journal.log_runtime_event(
                event_type="session_state_reset",
                payload={"source": source, "reason": "reset_transient_state"},
                status="warning",
            )
        # Guard: draft-first sessions must never enter the legacy plan/approval
        # machinery. These operations were removed from all active callers (UI and
        # MCP external server) but the TCP bridge still forwards raw socket fields,
        # so we gate here rather than relying solely on callers.
        _skip_legacy_approval_ops = False
        try:
            _v1_guard = self.v1_session_for(resolved)
            _es_guard = getattr(_v1_guard, "execution_state", None)
            _skip_legacy_approval_ops = bool(getattr(_es_guard, "drafting_mode", False)) or (
                getattr(_es_guard, "current_draft", None) is not None
            )
        except Exception:
            pass
        if _skip_legacy_approval_ops and (rebuild_plan or approval_decision is not None):
            self.journal.log_runtime_event(
                event_type="legacy_approval_ops_skipped",
                payload={
                    "source": source,
                    "had_rebuild_plan": bool(rebuild_plan),
                    "had_approval_decision": approval_decision is not None,
                    "reason": "draft_first_session",
                },
                status="warning",
            )
            rebuild_plan = False
            approval_decision = None
        if rebuild_plan:
            rebuilt, rebuild_error = self._rebuild_plan_from_state(state, source=source)
            if not rebuilt:
                state["last_failure"] = rebuild_error
                self.journal.log_runtime_event(
                    event_type="plan_rebuild_failed",
                    payload={"source": source, "reason": rebuild_error},
                    status="error",
                )
        if approval_decision is not None:
            decision = str(approval_decision or "").strip().lower()
            requested_plan_id = str(approval_plan_id or state.get("current_plan_id", "") or "").strip()
            requested_token = str(approval_token or "").strip()
            current_plan_id = str(state.get("current_plan_id", "") or "").strip()
            current_token = str(state.get("approval_token", "") or "").strip()
            if not requested_plan_id or not requested_token:
                self.journal.log_runtime_event(
                    event_type="execution_blocked_invalid_or_missing_approval",
                    payload={"reason": "missing_plan_id_or_approval_token"},
                    status="blocked",
                )
                state["approval_status"] = "pending"
                state["runtime_phase"] = "awaiting_user_approval"
            elif requested_plan_id != current_plan_id or requested_token != current_token:
                self.journal.log_runtime_event(
                    event_type="execution_blocked_invalid_or_missing_approval",
                    payload={
                        "reason": "approval_token_or_plan_id_mismatch",
                        "requested_plan_id": requested_plan_id,
                        "current_plan_id": current_plan_id,
                    },
                    status="blocked",
                )
                state["approval_status"] = "pending"
                state["runtime_phase"] = "awaiting_user_approval"
            elif decision == "granted":
                state["approval_status"] = "granted"
                state["current_plan_status"] = "approved"
                state["approval_source"] = str(approval_source or source or "")
                state["runtime_phase"] = "approved_waiting_execution"
                state["session_state"] = "active"
                self._set_current_stage_status(state, "approved")
                self.journal.log_runtime_event(
                    event_type="approval_granted",
                    payload={
                        "plan_id": current_plan_id,
                        "approval_token": current_token,
                        "approval_source": state["approval_source"],
                    },
                    status="success",
                )
                self.journal.log_runtime_event(
                    event_type="stage_approved",
                    payload={
                        "plan_id": current_plan_id,
                        "stage_id": state.get("current_stage_id", ""),
                        "stage_index": int(state.get("current_stage_index", -1)) + 1,
                        "approval_source": state["approval_source"],
                    },
                    status="success",
                )
                if current_plan_id and current_plan_id == str(state.get("fallback_plan_id", "")):
                    self.journal.log_runtime_event(
                        event_type="fallback_approval_granted",
                        payload={"plan_id": current_plan_id, "approval_token": current_token},
                        status="success",
                    )
            elif decision == "denied":
                state["approval_status"] = "denied"
                state["current_plan_status"] = "expired"
                state["approval_required"] = False
                state["approval_source"] = str(approval_source or source or "")
                state["runtime_phase"] = "planning"
                state["session_state"] = "active" if bool(state.get("agent_session_active", False)) else "no_session"
                self._set_current_stage_status(state, "denied")
                self.journal.log_runtime_event(
                    event_type="approval_denied",
                    payload={
                        "plan_id": current_plan_id,
                        "approval_token": current_token,
                        "approval_source": state["approval_source"],
                    },
                    status="warning",
                )
                self.journal.log_runtime_event(
                    event_type="stage_denied",
                    payload={
                        "plan_id": current_plan_id,
                        "stage_id": state.get("current_stage_id", ""),
                        "stage_index": int(state.get("current_stage_index", -1)) + 1,
                        "approval_source": state["approval_source"],
                    },
                    status="warning",
                )
                self.journal.log_runtime_event(
                    event_type="approval_expired",
                    payload={
                        "plan_id": current_plan_id,
                        "approval_token": current_token,
                        "reason": "approval_denied",
                    },
                    status="warning",
                )
        # --- Drafting mode toggle (V1 session) ---
        if drafting_mode is not None:
            try:
                v1_session = self.v1_session_for(resolved)
                v1_session.execution_state.drafting_mode = bool(drafting_mode)
                self.save_v1_session(v1_session)
            except Exception:
                # Fallback: record on legacy state so it survives round-trips.
                state["drafting_mode"] = bool(drafting_mode)

        self._persist_runtime_state(resolved, state)
        return state

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    def _update_state_after_tool(
        self,
        *,
        state: dict[str, Any],
        canonical_tool: str,
        tool_input: dict[str, Any],
        raw: dict[str, Any],
    ) -> None:
        status = str(raw.get("status", "success"))
        if status != "success":
            return
        result = raw.get("result", {}) if isinstance(raw.get("result"), dict) else {}
        tree_name = _extract_tree_name(tool_input) or str(result.get("tree_name", "")).strip()
        node_name = _extract_node_name(tool_input)

        state_ops.update_session_memory(
            state,
            {
                "target_tree": tree_name or state.get("last_target_tree", ""),
                "relevant_nodes": [node_name] if node_name else [],
            },
        )

        if canonical_tool == "create_frame":
            state_ops.update_session_memory(
                state,
                {"active_frame": str(tool_input.get("frame_name", "")).strip()},
            )

        if canonical_tool in {"set_node_value", "set_node_property"}:
            if node_name:
                param_entry = {
                    "node": node_name,
                    "field": str(tool_input.get("socket_name") or tool_input.get("property_name") or ""),
                    "value": tool_input.get("value"),
                    "ts": int(time.time()),
                }
                state_ops.update_session_memory(state, {"last_parameter_changes": [param_entry]})

        if canonical_tool == "get_selected_nodes_context":
            selected_nodes = []
            if isinstance(result.get("nodes"), list):
                selected_nodes = [
                    str(node.get("name", "")).strip()
                    for node in result.get("nodes", [])
                    if isinstance(node, dict) and node.get("is_selected")
                ]
            local_scope = {
                "scope_type": "selected_nodes",
                "tree_name": tree_name,
                "node_names": [n for n in selected_nodes if n],
                "updated_at": int(time.time()),
            }
            state_ops.set_local_scope(state, local_scope)
            self.journal.log_runtime_event(
                event_type="local_scope_used",
                payload={"scope_type": "selected_nodes", "selected_nodes_count": len(local_scope["node_names"])},
            )

        if canonical_tool == "get_active_frame_context":
            local_scope = {
                "scope_type": "active_frame",
                "tree_name": tree_name,
                "frame_name": str(result.get("frame_name", "")).strip(),
                "active_frame_name": str(result.get("frame_name", "")).strip(),
                "node_names": [
                    str(node.get("name", "")).strip()
                    for node in result.get("nodes", [])
                    if isinstance(node, dict)
                ],
                "updated_at": int(time.time()),
            }
            state_ops.set_local_scope(state, local_scope)
            state_ops.update_session_memory(
                state,
                {
                    "active_frame": local_scope.get("frame_name", ""),
                    "relevant_nodes": local_scope.get("node_names", []),
                },
            )
            self.journal.log_runtime_event(
                event_type="local_scope_used",
                payload={"scope_type": "active_frame", "active_frame_name": local_scope.get("frame_name", "")},
            )

        if canonical_tool == "get_local_subgraph_context":
            local_scope = {
                "scope_type": "subgraph",
                "tree_name": tree_name,
                "node_names": [
                    str(node.get("name", "")).strip()
                    for node in result.get("nodes", [])
                    if isinstance(node, dict)
                ],
                "updated_at": int(time.time()),
            }
            state_ops.set_local_scope(state, local_scope)
            state_ops.update_session_memory(
                state,
                {
                    "focus_subgraph": f"{tree_name}:{result.get('scope_mode', 'subgraph')}",
                    "relevant_nodes": local_scope.get("node_names", []),
                },
            )
            self.journal.log_runtime_event(
                event_type="local_scope_used",
                payload={
                    "scope_type": "subgraph",
                    "selected_nodes_count": len(local_scope.get("node_names", [])),
                },
            )

        if canonical_tool == "resolve_gn_workspace" and isinstance(result, dict):
            selected_tree = str(result.get("selected_tree") or "").strip()
            if selected_tree:
                state["last_target_tree"] = selected_tree
                selected_binding = result.get("selected_binding") if isinstance(result.get("selected_binding"), dict) else {}
                state_ops.update_session_memory(state, {"target_tree": selected_tree})
                self.journal.log_runtime_event(
                    event_type="gn_workspace_resolved",
                    payload={
                        "tree_name": selected_tree,
                        "selection_reason": result.get("selection_reason", ""),
                        "confidence": result.get("confidence", {}),
                        "object_name": selected_binding.get("object_name", ""),
                        "modifier_name": selected_binding.get("modifier_name", ""),
                    },
                )

        if canonical_tool == "build_tree_structural_memory" and isinstance(result, dict):
            memory = result.get("memory") if isinstance(result.get("memory"), dict) else result
            memory_tree = str(memory.get("tree_name") or tree_name or result.get("tree_name") or "").strip()
            if memory_tree:
                state["last_target_tree"] = memory_tree
                state_ops.update_session_memory(state, {"target_tree": memory_tree})
                state_ops.update_tree_structural_memory(state, memory_tree, memory)
                marker = memory.get("marker") if isinstance(memory.get("marker"), dict) else {}
                if marker:
                    state_ops.update_tree_change_marker(state, memory_tree, marker)
                self.journal.log_runtime_event(
                    event_type="tree_structural_memory_updated",
                    payload={
                        "tree_name": memory_tree,
                        "node_count": memory.get("node_count", 0),
                        "phase_dominant": memory.get("phase_dominant", ""),
                        "phase_confidence": memory.get("phase_confidence", 0),
                        "organization": (
                            memory.get("organization_assessment", {}).get("level", "")
                            if isinstance(memory.get("organization_assessment"), dict)
                            else ""
                        ),
                    },
                )

        if canonical_tool in {
            "classify_tree_phases",
            "map_clinical_parameter_roles",
            "interpret_orthosis_tree_logic",
        } and isinstance(result, dict):
            semantic_tree = str(result.get("tree_name") or tree_name or state.get("last_target_tree") or "").strip()
            if semantic_tree:
                state["last_target_tree"] = semantic_tree
                state_ops.update_session_memory(state, {"target_tree": semantic_tree})
                state_ops.update_tree_semantic_memory(state, semantic_tree, canonical_tool, result)
                self.journal.log_runtime_event(
                    event_type="tree_semantic_memory_updated",
                    payload={
                        "tree_name": semantic_tree,
                        "semantic_key": canonical_tool,
                    },
                )

        if canonical_tool == "get_changes_since_last_turn":
            current_marker = result.get("current_marker", {}) if isinstance(result.get("current_marker"), dict) else {}
            update_marker = bool(tool_input.get("update_marker", True))
            if update_marker and tree_name and current_marker:
                state_ops.update_tree_change_marker(state, tree_name=tree_name, marker=current_marker)
            if int(result.get("changes_count", 0) or 0) > 0:
                state_ops.mark_tree_structural_memory_stale(
                    state,
                    tree_name,
                    reason="changes_since_last_turn_detected_changes",
                )
            self.journal.log_runtime_event(
                event_type="changes_since_last_turn",
                payload={
                    "tree_name": tree_name,
                    "changes_since_last_turn_count": int(result.get("changes_count", 0) or 0),
                },
            )

        if self.journal.is_mutation(canonical_tool):
            stale_tree = tree_name or str(state.get("last_target_tree") or "").strip()
            state_ops.mark_tree_structural_memory_stale(
                state,
                stale_tree,
                reason=f"mutation_tool:{canonical_tool}",
            )

    def execute_tool_call(
        self,
        *,
        tool_name: str,
        tool_input: dict[str, Any] | None = None,
        route: str = "product",
        output_mode: str = "compact",
        user_confirmed: bool = False,
        debug_mode: bool | None = None,
        explicit_override_mode: bool | None = None,
        mcp_write_enabled: bool | None = None,
        blend_path: str | None = None,
        journal_session_id: str | None = None,
        journal_run_id: str | None = None,
        journal_goal_id: str | None = None,
    ) -> dict[str, Any]:
        tool_input = tool_input or {}
        call_started = time.time()
        resolved = self._resolve_blend_path(blend_path)
        if journal_run_id:
            try:
                self.journal.bind_run_context(
                    session_id=str(journal_session_id or ""),
                    run_id=str(journal_run_id or ""),
                    blend_file=resolved,
                    goal_id=str(journal_goal_id or ""),
                )
            except Exception:
                pass
        state = self._load_runtime_state(resolved)

        if debug_mode is not None:
            state_ops.set_debug_mode(state, debug_mode)
        if explicit_override_mode is not None:
            state_ops.set_override_mode(state, explicit_override_mode)
        if mcp_write_enabled is not None:
            state_ops.set_mcp_write_enabled(state, mcp_write_enabled)

        canonical_tool = tool_name
        args_preview = self.journal.preview(tool_input)
        tree_name = _extract_tree_name(tool_input)
        node_name = _extract_node_name(tool_input)
        source_route = "mcp_external" if route == "mcp" else "product_bridge"

        safety_ctx = SafetyContext(
            route="mcp" if route == "mcp" else "product",
            debug_mode=bool(state.get("debug_mode", False)),
            explicit_override=bool(state.get("explicit_override_mode", False)),
            user_confirmed=bool(user_confirmed),
            mcp_write_enabled=bool(state.get("mcp_write_enabled", False)),
        )
        decision = evaluate_tool_call(canonical_tool, safety_ctx, tool_input=tool_input)

        self.journal.log_runtime_event(
            event_type="safety_decision",
            payload={
                "tool_name": canonical_tool,
                "route": route,
                "decision": decision.reason,
                "allowed": decision.allowed,
                "level": decision.level,
                "requires_confirmation": decision.requires_confirmation,
                "requires_override": decision.requires_override,
            },
            status="success" if decision.allowed else "blocked",
        )

        if decision.requires_confirmation and not user_confirmed and route == "mcp":
            blocked = {
                "status": "blocked",
                "error": "Tool requires confirmation before apply.",
                "tool_name": canonical_tool,
                "safety": {
                    "level": decision.level,
                    "reason": decision.reason,
                    "requires_confirmation": True,
                    "requires_override": decision.requires_override,
                },
            }
            state_ops.record_action(
                state,
                route=route,
                tool_name=canonical_tool,
                status="blocked",
                safety_level=decision.level,
                details={"reason": decision.reason},
            )
            state_ops.record_risky_event(
                state,
                route=route,
                tool_name=canonical_tool,
                decision_reason=decision.reason,
                allowed=False,
                context={"requires_confirmation": True},
            )
            self._persist_runtime_state(resolved, state)
            self.journal.log_tool_call(
                tool_name=canonical_tool,
                payload_size=len(json.dumps(tool_input, ensure_ascii=False)),
                result_size=len(json.dumps(blocked, ensure_ascii=False)),
                round_time_ms=int((time.time() - call_started) * 1000),
                status="blocked",
                tool_args_preview=args_preview,
                tool_result_preview=self.journal.preview(blocked),
                routing_reason=decision.reason,
                tree_name=tree_name,
                node_name=node_name,
                source_route=source_route,
                used_structured_tool=(canonical_tool != "execute_code"),
                fallback_to_execute_code_reason="blocked_by_confirmation"
                if canonical_tool == "execute_code"
                else "",
                structured_tool_available=None if canonical_tool != "execute_code" else False,
                execute_code_inevitable=None if canonical_tool != "execute_code" else None,
            )
            return blocked

        if not decision.allowed:
            blocked = {
                "status": "blocked",
                "error": "Tool blocked by safety policy.",
                "tool_name": canonical_tool,
                "safety": {
                    "level": decision.level,
                    "reason": decision.reason,
                    "requires_confirmation": decision.requires_confirmation,
                    "requires_override": decision.requires_override,
                },
            }
            state_ops.record_action(
                state,
                route=route,
                tool_name=canonical_tool,
                status="blocked",
                safety_level=decision.level,
                details={"reason": decision.reason},
            )
            state_ops.record_risky_event(
                state,
                route=route,
                tool_name=canonical_tool,
                decision_reason=decision.reason,
                allowed=False,
                context={"requires_override": decision.requires_override},
            )
            self._persist_runtime_state(resolved, state)
            self.journal.log_tool_call(
                tool_name=canonical_tool,
                payload_size=len(json.dumps(tool_input, ensure_ascii=False)),
                result_size=len(json.dumps(blocked, ensure_ascii=False)),
                round_time_ms=int((time.time() - call_started) * 1000),
                status="blocked",
                tool_args_preview=args_preview,
                tool_result_preview=self.journal.preview(blocked),
                routing_reason=decision.reason,
                tree_name=tree_name,
                node_name=node_name,
                source_route=source_route,
                used_structured_tool=(canonical_tool != "execute_code"),
                fallback_to_execute_code_reason="blocked_by_policy"
                if canonical_tool == "execute_code"
                else "",
                structured_tool_available=None if canonical_tool != "execute_code" else False,
                execute_code_inevitable=None if canonical_tool != "execute_code" else None,
            )
            return blocked

        raw = self.dispatcher.execute(
            canonical_tool,
            tool_input,
            output_mode=output_mode,
            session_state=state,
        )
        status = raw.get("status", "success")

        # Onda 5 (Item 5.3): specific journal events for snapshot operations.
        if status == "success":
            if canonical_tool == "take_blend_snapshot":
                try:
                    self.journal.log_runtime_event(
                        event_type="blend_snapshot_taken",
                        payload={
                            "session_id": raw.get("session_id", ""),
                            "revision": raw.get("revision", 0),
                            "snapshot_path": raw.get("snapshot_path", ""),
                            "size_bytes": raw.get("size_bytes", 0),
                        },
                    )
                except Exception:
                    pass
            elif canonical_tool == "restore_blend_snapshot":
                try:
                    self.journal.log_runtime_event(
                        event_type="blend_snapshot_restored",
                        payload={"snapshot_path": raw.get("snapshot_path", "")},
                    )
                except Exception:
                    pass
        self.journal.log_runtime_event(
            event_type="tool_execution",
            payload={
                "tool_name": canonical_tool,
                "route": route,
                "status": status,
                "error": raw.get("error"),
            },
            status=status,
        )
        state_ops.record_action(
            state,
            route=route,
            tool_name=canonical_tool,
            status=status,
            safety_level=decision.level,
            details={"result_keys": sorted(raw.keys())[:10]},
        )
        if decision.level != "auto_apply":
            state_ops.record_risky_event(
                state,
                route=route,
                tool_name=canonical_tool,
                decision_reason=decision.reason,
                allowed=True,
                context={
                    "level": decision.level,
                    "debug_mode": state.get("debug_mode", False),
                    "explicit_override_mode": state.get("explicit_override_mode", False),
                },
            )
        if canonical_tool in {"get_scene_summary", "analyze_scene"}:
            state_ops.update_scene_summary(state, raw.get("result", {}))
        if canonical_tool in {"analyze_gn_state", "build_gn_graph"}:
            state_ops.update_gn_summary(state, raw.get("result", {}))
        self._update_state_after_tool(
            state=state,
            canonical_tool=canonical_tool,
            tool_input=tool_input,
            raw=raw,
        )

        self.journal.log_tool_call(
            tool_name=canonical_tool,
            payload_size=len(json.dumps(tool_input, ensure_ascii=False)),
            result_size=len(json.dumps(raw, ensure_ascii=False)),
            round_time_ms=int((time.time() - call_started) * 1000),
            status=status,
            tool_args_preview=args_preview,
            tool_result_preview=self.journal.preview(raw),
            routing_reason=decision.reason,
            tree_name=tree_name,
            node_name=node_name,
            source_route=source_route,
            used_structured_tool=(canonical_tool != "execute_code"),
            fallback_to_execute_code_reason=(
                "execute_code_bridge_path"
                if canonical_tool == "execute_code"
                else ""
            ),
            structured_tool_available=None if canonical_tool != "execute_code" else False,
            execute_code_inevitable=None if canonical_tool != "execute_code" else None,
            metadata={"safety_level": decision.level},
        )
        if self.journal.is_mutation(canonical_tool):
            operations = tool_input.get("operations") if isinstance(tool_input.get("operations"), list) else None
            self.journal.log_operation(
                tool_name=canonical_tool,
                tree_name=tool_input.get("tree_name", ""),
                operations=operations,
                params=tool_input if operations is None else None,
                status=status,
                error=raw.get("error"),
            )
        if canonical_tool == "execute_code":
            stdout = raw.get("stdout")
            if stdout is None and isinstance(raw.get("result"), dict):
                stdout = raw.get("result", {}).get("stdout")
            self.journal.log_code_execution(
                code=str(tool_input.get("code", "")),
                status=status,
                error=raw.get("error"),
                stdout=stdout if isinstance(stdout, str) else None,
            )

        self._persist_runtime_state(
            resolved,
            state,
            canonical_tool=canonical_tool,
            raw=raw,
            tool_input=tool_input,
        )
        return {
            "status": status,
            "tool_name": canonical_tool,
            "safety": {
                "level": decision.level,
                "reason": decision.reason,
                "requires_confirmation": decision.requires_confirmation,
                "requires_override": decision.requires_override,
            },
            "result": raw.get("result"),
            "error": raw.get("error"),
            "raw": raw,
        }
