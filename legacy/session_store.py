"""LEGACY — não é mais importado pelo runtime ativo.

Mantido apenas como referência de migração e para testes legados em legacy/tests/.
State operations: runtime/state_ops.py
Session persistence: session/store.py (SessionV1Store)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


SCHEMA_VERSION = "0.2"

MAX_MEMORY_DECISIONS = 20
MAX_MEMORY_NODES = 40
MAX_MEMORY_PARAMS = 24
MAX_TREE_MARKERS = 8
MAX_CHAT_HISTORY = 80
MAX_CHAT_TEXT = 20000

# Fields that existed in schema 0.1 but are no longer used.
# They are actively removed from loaded session dicts to keep state lean.
_VESTIGIAL_FIELDS = frozenset({
    "last_task_class", "last_routing_reason", "last_plan_summary", "last_plan_gate",
    "last_turn_tools", "audit_trail", "agent_session_active", "session_started_at",
    "control_owner", "control_owner_locked", "control_owner_enforced", "control_owner_updated_at",
    "runtime_phase", "session_state", "session_resumed_notice",
    "current_plan_id", "current_plan_type", "current_plan_mode", "current_plan_status",
    "approval_required", "approval_token", "approval_status", "approval_source",
    "superseded_plan_id", "execution_plan_id", "execution_approval_token",
    "fallback_plan_id", "fallback_approval_token",
    "presented_plan_summary", "presented_plan_type", "presented_plan_mode",
    "presented_plan_reasoning", "presented_conversation_opening",
    "presented_collaboration_options", "presented_continuity_summary",
    "presented_context_source_labels", "presented_next_step_strategy",
    "presented_next_step_strategy_summary", "presented_plan_steps",
    "presented_plan_impacts", "presented_plan_tools", "presented_proposed_tools_if_needed",
    "presented_context_reads", "presented_context_requirements",
    "presented_fallback_possible", "presented_execute_code_risk", "presented_plan_stages",
    "current_stage_id", "current_stage_index", "current_stage_status",
    "execution_policy", "last_replan", "pending_original_goal",
    "legacy_chat_history_enabled",
    # Also remove old workflow fields
    "workflow_mode", "pending_approval", "pending_approval_scope",
})


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _new_session_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"sess-{ts}-{uuid4().hex[:8]}"


def _default_session_memory() -> dict[str, Any]:
    return {
        "last_goal": "",
        "target_tree": "",
        "focus_subgraph": "",
        "active_frame": "",
        "relevant_nodes": [],
        "last_parameter_changes": [],
        "last_hypothesis": "",
        "decisions": [],
        "aliases": {},
        "nodes_precreated_by_user": [],
        "last_manual_roundtrip_note": "",
    }


def _default_state(blend_path: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "session_id": _new_session_id(),
        "blend_path": blend_path or "",
        # Runtime flags read by execution/dispatcher.py
        "debug_mode": False,
        "explicit_override_mode": False,
        "mcp_write_enabled": False,
        # Scene/tree state caches (used by runtime_dispatch.py)
        "last_scene_summary": {},
        "last_gn_summary": {},
        "recent_actions": [],
        "last_target_tree": "",
        # Counters and bookkeeping
        "turn_counter": 0,
        "last_failure": "",
        # Working memory for the agent
        "session_memory": _default_session_memory(),
        "structural_index": {},
        "tree_change_markers": {},
        # Chat transcript for Blender UI panel
        "chat_history": [],
        "updated_at": _utc_now_iso(),
    }


@dataclass
class SessionStore:
    project_root: Path

    def _session_path(self) -> Path:
        runtime_sessions = self.project_root / "runtime" / "sessions"
        runtime_sessions.mkdir(parents=True, exist_ok=True)
        return runtime_sessions / "session.json"

    def load(self, blend_path: str = "") -> dict[str, Any]:
        path = self._session_path()
        if not path.exists():
            return _default_state(blend_path)
        try:
            with path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            return _default_state(blend_path)
        if not isinstance(payload, dict):
            return _default_state(blend_path)

        # Strip vestigial fields from old session files.
        for key in _VESTIGIAL_FIELDS:
            payload.pop(key, None)

        # Ensure all current fields are present.
        payload.setdefault("schema_version", SCHEMA_VERSION)
        payload.setdefault("session_id", _new_session_id())
        payload.setdefault("blend_path", blend_path or "")
        payload.setdefault("debug_mode", False)
        payload.setdefault("explicit_override_mode", False)
        payload.setdefault("mcp_write_enabled", False)
        payload.setdefault("last_scene_summary", {})
        payload.setdefault("last_gn_summary", {})
        payload.setdefault("recent_actions", [])
        payload.setdefault("last_target_tree", "")
        payload.setdefault("turn_counter", 0)
        payload.setdefault("last_failure", "")
        payload.setdefault("session_memory", _default_session_memory())
        payload.setdefault("structural_index", {})
        payload.setdefault("tree_change_markers", {})
        payload.setdefault("chat_history", [])
        payload.setdefault("updated_at", _utc_now_iso())

        self._normalize_state(payload)
        return payload

    def _normalize_state(self, state: dict[str, Any]) -> None:
        # Runtime flags
        state["debug_mode"] = bool(state.get("debug_mode", False))
        state["explicit_override_mode"] = bool(state.get("explicit_override_mode", False))
        state["mcp_write_enabled"] = bool(state.get("mcp_write_enabled", False))

        # Counters
        try:
            state["turn_counter"] = int(state.get("turn_counter", 0))
        except Exception:
            state["turn_counter"] = 0

        # Simple string fields
        state["last_target_tree"] = str(state.get("last_target_tree", "") or "")
        state["last_failure"] = str(state.get("last_failure", "") or "")

        # Dict fields
        if not isinstance(state.get("last_scene_summary"), dict):
            state["last_scene_summary"] = {}
        if not isinstance(state.get("last_gn_summary"), dict):
            state["last_gn_summary"] = {}
        if not isinstance(state.get("structural_index"), dict):
            state["structural_index"] = {}
        if not isinstance(state.get("tree_change_markers"), dict):
            state["tree_change_markers"] = {}

        # List fields
        if not isinstance(state.get("recent_actions"), list):
            state["recent_actions"] = []

        # session_memory
        memory = state.get("session_memory")
        if not isinstance(memory, dict):
            memory = _default_session_memory()
        merged = _default_session_memory()
        merged.update(memory)
        merged["relevant_nodes"] = [
            str(v) for v in merged.get("relevant_nodes", []) if str(v).strip()
        ][-MAX_MEMORY_NODES:]
        merged["decisions"] = [
            str(v) for v in merged.get("decisions", []) if str(v).strip()
        ][-MAX_MEMORY_DECISIONS:]
        if not isinstance(merged.get("last_parameter_changes"), list):
            merged["last_parameter_changes"] = []
        merged["last_parameter_changes"] = merged["last_parameter_changes"][-MAX_MEMORY_PARAMS:]
        merged["nodes_precreated_by_user"] = [
            str(v) for v in merged.get("nodes_precreated_by_user", []) if str(v).strip()
        ][-MAX_MEMORY_NODES:]
        if not isinstance(merged.get("aliases"), dict):
            merged["aliases"] = {}
        state["session_memory"] = merged

        # chat_history
        if not isinstance(state.get("chat_history"), list):
            state["chat_history"] = []
        normalized: list[dict[str, Any]] = []
        for item in state.get("chat_history", []):
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", "") or "").strip().lower()
            if role not in {"user", "assistant", "system"}:
                continue
            text = str(item.get("text", "") or "")
            if not text.strip():
                continue
            normalized.append({
                "role": role,
                "text": text[:MAX_CHAT_TEXT],
                "timestamp": str(item.get("timestamp", "") or _utc_now_iso()),
            })
        state["chat_history"] = normalized[-MAX_CHAT_HISTORY:]

    def save(self, state: dict[str, Any], blend_path: str = "") -> Path:
        path = self._session_path()
        self._normalize_state(state)
        state["updated_at"] = _utc_now_iso()
        with path.open("w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
            f.write("\n")
        return path

    def get_session_memory(self, state: dict[str, Any]) -> dict[str, Any]:
        m = state.get("session_memory")
        return m if isinstance(m, dict) else _default_session_memory()

    def update_scene_summary(self, state: dict[str, Any], summary: dict[str, Any]) -> None:
        state["last_scene_summary"] = summary or {}

    def update_gn_summary(self, state: dict[str, Any], summary: dict[str, Any]) -> None:
        state["last_gn_summary"] = summary or {}

    def record_action(
        self,
        state: dict[str, Any],
        *,
        route: str,
        tool_name: str,
        status: str,
        safety_level: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        actions = state.setdefault("recent_actions", [])
        if not isinstance(actions, list):
            actions = []
            state["recent_actions"] = actions
        actions.append(
            {
                "timestamp": _utc_now_iso(),
                "route": route,
                "tool_name": tool_name,
                "status": status,
                "safety_level": safety_level,
                "details": details or {},
            }
        )
        if len(actions) > 50:
            del actions[:-50]

    def record_risky_event(
        self,
        state: dict[str, Any],
        *,
        route: str,
        tool_name: str,
        decision_reason: str,
        allowed: bool,
        context: dict[str, Any] | None = None,
    ) -> None:
        events = state.setdefault("risky_events", [])
        if not isinstance(events, list):
            events = []
            state["risky_events"] = events
        events.append(
            {
                "timestamp": _utc_now_iso(),
                "route": route,
                "tool_name": tool_name,
                "decision_reason": decision_reason,
                "allowed": bool(allowed),
                "context": context or {},
            }
        )
        if len(events) > 50:
            del events[:-50]

    def update_session_memory(
        self,
        state: dict[str, Any],
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        """Merge ``updates`` into ``state['session_memory']`` and return it.

        Semantics (aligned with legacy/tests/test_session_store.py):
        - ``relevant_nodes`` / ``nodes_precreated_by_user``: append-and-dedup
          preserving order; an empty update leaves existing entries intact.
        - ``last_parameter_changes``: keep only the latest single entry.
        - ``decisions``: append.
        - ``aliases``: dict merge.
        - Any other key: overwrite when a non-empty value is provided.
        """
        memory = state.get("session_memory")
        if not isinstance(memory, dict):
            memory = _default_session_memory()
            state["session_memory"] = memory
        if not isinstance(updates, dict):
            return memory

        def _dedup_append(existing: Any, incoming: list[Any]) -> list[Any]:
            base = list(existing) if isinstance(existing, list) else []
            for item in incoming:
                if item not in base:
                    base.append(item)
            return base

        for key, value in updates.items():
            if key in ("relevant_nodes", "nodes_precreated_by_user") and isinstance(value, list):
                if not value:
                    continue
                memory[key] = _dedup_append(memory.get(key), value)
            elif key == "last_parameter_changes" and isinstance(value, list):
                memory[key] = value[-1:] if value else []
            elif key == "decisions" and isinstance(value, list):
                existing = memory.get("decisions")
                base = list(existing) if isinstance(existing, list) else []
                memory["decisions"] = base + list(value)
            elif key == "aliases" and isinstance(value, dict):
                aliases = memory.get("aliases")
                merged = dict(aliases) if isinstance(aliases, dict) else {}
                merged.update(value)
                memory["aliases"] = merged
            else:
                if value in ("", None):
                    continue
                memory[key] = value

        # Cap list fields defensively per existing constants.
        nodes = memory.get("relevant_nodes")
        if isinstance(nodes, list) and len(nodes) > MAX_MEMORY_NODES:
            memory["relevant_nodes"] = nodes[-MAX_MEMORY_NODES:]
        params = memory.get("last_parameter_changes")
        if isinstance(params, list) and len(params) > MAX_MEMORY_PARAMS:
            memory["last_parameter_changes"] = params[-MAX_MEMORY_PARAMS:]
        decisions = memory.get("decisions")
        if isinstance(decisions, list) and len(decisions) > MAX_MEMORY_DECISIONS:
            memory["decisions"] = decisions[-MAX_MEMORY_DECISIONS:]

        return memory

    def update_structural_index(
        self,
        state: dict[str, Any],
        tree_name: str,
        index_entry: dict[str, Any],
    ) -> None:
        if not tree_name or not isinstance(index_entry, dict):
            return
        index = state.get("structural_index")
        if not isinstance(index, dict):
            index = {}
        index[tree_name] = index_entry
        state["structural_index"] = index

    def update_tree_change_marker(
        self,
        state: dict[str, Any],
        tree_name: str,
        marker: dict[str, Any],
    ) -> None:
        if not tree_name or not isinstance(marker, dict):
            return
        markers = state.get("tree_change_markers")
        if not isinstance(markers, dict):
            markers = {}
        markers[tree_name] = marker
        if len(markers) > MAX_TREE_MARKERS:
            oldest = next(iter(markers))
            del markers[oldest]
        state["tree_change_markers"] = markers

    def set_local_scope(
        self,
        state: dict[str, Any],
        scope: dict[str, Any] | None,
    ) -> None:
        """Persist the transient focal scope used by context-reader tools.

        Callers (``runtime/core.py`` and ``runtime_state_sync.py``) pass dicts
        shaped like ``{"scope_type": ..., "tree_name": ..., "node_names": [...], ...}``
        or ``None`` to clear. Stored under ``state['local_scope']``.
        """
        if scope is None:
            state["local_scope"] = {}
            return
        if not isinstance(scope, dict):
            return
        state["local_scope"] = dict(scope)

    def set_debug_mode(self, state: dict[str, Any], enabled: bool) -> None:
        state["debug_mode"] = bool(enabled)

    def set_override_mode(self, state: dict[str, Any], enabled: bool) -> None:
        state["explicit_override_mode"] = bool(enabled)

    def set_mcp_write_enabled(self, state: dict[str, Any], enabled: bool) -> None:
        state["mcp_write_enabled"] = bool(enabled)

    def bump_turn_counter(self, state: dict[str, Any]) -> int:
        try:
            current = int(state.get("turn_counter", 0))
        except Exception:
            current = 0
        current += 1
        state["turn_counter"] = current
        return current

    def reset_session_memory(self, state: dict[str, Any]) -> None:
        state["session_memory"] = _default_session_memory()
        state["structural_index"] = {}
        state["tree_change_markers"] = {}
        state["last_failure"] = ""
        state["last_target_tree"] = ""

    def begin_new_session(self, state: dict[str, Any]) -> None:
        state["session_id"] = _new_session_id()
        state["turn_counter"] = 0
        state["recent_actions"] = []
        state["last_scene_summary"] = {}
        state["last_gn_summary"] = {}
        state["last_target_tree"] = ""
        state["chat_history"] = []
        self.reset_session_memory(state)

    def append_chat_history(self, state: dict[str, Any], *, role: str, text: str) -> None:
        role_name = str(role or "").strip().lower()
        if role_name not in {"user", "assistant", "system"}:
            return
        content = str(text or "")
        if not content.strip():
            return
        history = state.get("chat_history")
        if not isinstance(history, list):
            history = []
        history.append({
            "role": role_name,
            "text": content[:MAX_CHAT_TEXT],
            "timestamp": _utc_now_iso(),
        })
        state["chat_history"] = history[-MAX_CHAT_HISTORY:]

    def clear_chat_history(self, state: dict[str, Any]) -> None:
        state["chat_history"] = []

    def reset_transient_state(self, state: dict[str, Any]) -> None:
        state["last_failure"] = ""
