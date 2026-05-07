"""Stateless operations on the runtime flat-state dict.

These are plain module-level functions — no class, no instance.
Callers (runtime/core.py, agent_runtime.py) import and call them directly.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

MAX_MEMORY_DECISIONS = 20
MAX_MEMORY_NODES = 40
MAX_MEMORY_PARAMS = 24
MAX_TREE_MARKERS = 8
MAX_TREE_STRUCTURAL_MEMORIES = 8
MAX_CHAT_HISTORY = 80
MAX_CHAT_TEXT = 20000


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

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


_SCHEMA_VERSION = "0.2"


def default_state(blend_path: str = "") -> dict[str, Any]:
    """Return a fresh flat runtime state dict."""
    return {
        "schema_version": _SCHEMA_VERSION,
        "session_id": _new_session_id(),
        "blend_path": blend_path or "",
        "debug_mode": False,
        "explicit_override_mode": False,
        "mcp_write_enabled": False,
        "last_scene_summary": {},
        "last_gn_summary": {},
        "recent_actions": [],
        "last_target_tree": "",
        "turn_counter": 0,
        "last_failure": "",
        "session_memory": _default_session_memory(),
        "structural_index": {},
        "tree_structural_memory": {},
        "tree_change_markers": {},
        "chat_history": [],
        "updated_at": _utc_now_iso(),
    }


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_session_memory(state: dict[str, Any]) -> dict[str, Any]:
    m = state.get("session_memory")
    return m if isinstance(m, dict) else _default_session_memory()


# ---------------------------------------------------------------------------
# Scene / GN summaries
# ---------------------------------------------------------------------------

def update_scene_summary(state: dict[str, Any], summary: dict[str, Any]) -> None:
    state["last_scene_summary"] = summary or {}


def update_gn_summary(state: dict[str, Any], summary: dict[str, Any]) -> None:
    state["last_gn_summary"] = summary or {}


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------

def record_action(
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
    actions.append({
        "timestamp": _utc_now_iso(),
        "route": route,
        "tool_name": tool_name,
        "status": status,
        "safety_level": safety_level,
        "details": details or {},
    })
    if len(actions) > 50:
        del actions[:-50]


def record_risky_event(
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
    events.append({
        "timestamp": _utc_now_iso(),
        "route": route,
        "tool_name": tool_name,
        "decision_reason": decision_reason,
        "allowed": bool(allowed),
        "context": context or {},
    })
    if len(events) > 50:
        del events[:-50]


# ---------------------------------------------------------------------------
# Session memory
# ---------------------------------------------------------------------------

def update_session_memory(
    state: dict[str, Any],
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Merge ``updates`` into ``state['session_memory']`` and return it.

    - ``relevant_nodes`` / ``nodes_precreated_by_user``: append-and-dedup.
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


# ---------------------------------------------------------------------------
# Structural index / change markers
# ---------------------------------------------------------------------------

def update_structural_index(
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


def update_tree_structural_memory(
    state: dict[str, Any],
    tree_name: str,
    memory: dict[str, Any],
) -> None:
    if not tree_name or not isinstance(memory, dict):
        return
    store = state.get("tree_structural_memory")
    if not isinstance(store, dict):
        store = {}
    entry = dict(memory)
    entry.setdefault("tree_name", tree_name)
    entry.setdefault("built_at", _utc_now_iso())
    entry["stale"] = bool(entry.get("stale", False))
    store[tree_name] = entry
    if len(store) > MAX_TREE_STRUCTURAL_MEMORIES:
        del store[next(iter(store))]
    state["tree_structural_memory"] = store


def update_tree_semantic_memory(
    state: dict[str, Any],
    tree_name: str,
    semantic_key: str,
    payload: dict[str, Any],
) -> None:
    if not tree_name or not semantic_key or not isinstance(payload, dict):
        return
    store = state.get("tree_structural_memory")
    if not isinstance(store, dict):
        store = {}
    entry = store.get(tree_name)
    if not isinstance(entry, dict):
        entry = {"tree_name": tree_name, "built_at": _utc_now_iso(), "stale": True}
    semantic = entry.get("semantic")
    if not isinstance(semantic, dict):
        semantic = {}
    semantic[semantic_key] = {
        "updated_at": _utc_now_iso(),
        "payload": dict(payload),
    }
    entry["semantic"] = semantic
    store[tree_name] = entry
    if len(store) > MAX_TREE_STRUCTURAL_MEMORIES:
        del store[next(iter(store))]
    state["tree_structural_memory"] = store


def mark_tree_structural_memory_stale(
    state: dict[str, Any],
    tree_name: str = "",
    *,
    reason: str = "",
) -> None:
    store = state.get("tree_structural_memory")
    if not isinstance(store, dict):
        return
    names = [tree_name] if tree_name else list(store.keys())
    for name in names:
        entry = store.get(name)
        if not isinstance(entry, dict):
            continue
        entry["stale"] = True
        entry["stale_reason"] = reason or "runtime_state_changed"
        entry["stale_at"] = _utc_now_iso()
    state["tree_structural_memory"] = store


def update_tree_change_marker(
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
        del markers[next(iter(markers))]
    state["tree_change_markers"] = markers


# ---------------------------------------------------------------------------
# Focal scope
# ---------------------------------------------------------------------------

def set_local_scope(
    state: dict[str, Any],
    scope: dict[str, Any] | None,
) -> None:
    if scope is None:
        state["local_scope"] = {}
        return
    if not isinstance(scope, dict):
        return
    state["local_scope"] = dict(scope)


# ---------------------------------------------------------------------------
# Runtime flags
# ---------------------------------------------------------------------------

def set_debug_mode(state: dict[str, Any], enabled: bool) -> None:
    state["debug_mode"] = bool(enabled)


def set_override_mode(state: dict[str, Any], enabled: bool) -> None:
    state["explicit_override_mode"] = bool(enabled)


def set_mcp_write_enabled(state: dict[str, Any], enabled: bool) -> None:
    state["mcp_write_enabled"] = bool(enabled)


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

def bump_turn_counter(state: dict[str, Any]) -> int:
    try:
        current = int(state.get("turn_counter", 0))
    except Exception:
        current = 0
    current += 1
    state["turn_counter"] = current
    return current


def reset_session_memory(state: dict[str, Any]) -> None:
    state["session_memory"] = _default_session_memory()
    state["structural_index"] = {}
    state["tree_structural_memory"] = {}
    state["tree_change_markers"] = {}
    state["last_failure"] = ""
    state["last_target_tree"] = ""


def begin_new_session(state: dict[str, Any]) -> None:
    state["session_id"] = _new_session_id()
    state["turn_counter"] = 0
    state["recent_actions"] = []
    state["last_scene_summary"] = {}
    state["last_gn_summary"] = {}
    state["last_target_tree"] = ""
    state["chat_history"] = []
    reset_session_memory(state)


def append_chat_history(state: dict[str, Any], *, role: str, text: str) -> None:
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


def clear_chat_history(state: dict[str, Any]) -> None:
    state["chat_history"] = []


def validate_session_memory_gn(state: dict[str, Any]) -> list[str]:
    """Validate GN-related session_memory fields against live Blender data.

    Must be called BEFORE the system prompt is built for GN-relevant turns,
    so the model never receives stale ``target_tree`` / ``relevant_nodes``.

    Mutates ``state["session_memory"]`` in-place:
    - Clears ``target_tree`` if the node group no longer exists.
    - Removes individual entries from ``relevant_nodes`` that no longer exist
      inside the target tree; valid entries are preserved.

    Returns a list of human-readable warning strings (empty if everything is
    fresh).  Callers are responsible for persisting the state after this call.

    Safe to call outside Blender: if ``bpy`` is unavailable, returns ``[]``
    without touching the state.
    """
    try:
        import bpy as _bpy  # noqa: F401 — lazy import; may not exist outside Blender
    except Exception:
        return []

    memory = state.get("session_memory")
    if not isinstance(memory, dict):
        return []

    warnings: list[str] = []
    target_tree = str(memory.get("target_tree") or "").strip()

    # ------------------------------------------------------------------ #
    # 1.  Validate target_tree                                             #
    # ------------------------------------------------------------------ #
    tree_obj = None
    if target_tree:
        try:
            tree_obj = _bpy.data.node_groups.get(target_tree)
        except Exception:
            tree_obj = None

        if tree_obj is None:
            memory["target_tree"] = ""
            # Also clear the derived fields that depend on a specific tree.
            memory["focus_subgraph"] = ""
            memory["active_frame"] = ""
            warnings.append(
                f"session_memory.target_tree '{target_tree}' no longer exists "
                "in bpy.data.node_groups — field cleared."
            )
            # Without a valid tree we cannot validate node names.
            return warnings

    # ------------------------------------------------------------------ #
    # 2.  Validate relevant_nodes (only when target_tree is valid)         #
    # ------------------------------------------------------------------ #
    relevant = memory.get("relevant_nodes")
    if not isinstance(relevant, list) or not relevant or tree_obj is None:
        return warnings

    try:
        live_node_names: set[str] = {n.name for n in tree_obj.nodes}
    except Exception:
        return warnings  # bpy access failed mid-flight — skip node validation

    stale: list[str] = []
    fresh: list[str] = []
    for node_name in relevant:
        name_str = str(node_name).strip()
        if not name_str:
            continue
        if name_str in live_node_names:
            fresh.append(name_str)
        else:
            stale.append(name_str)

    if stale:
        memory["relevant_nodes"] = fresh  # preserve valid entries only
        warnings.append(
            f"session_memory.relevant_nodes: removed {len(stale)} stale "
            f"node(s) not found in '{target_tree}': {stale}. "
            f"{len(fresh)} valid node(s) kept."
        )

    return warnings


def reset_transient_state(state: dict[str, Any]) -> None:
    state["last_failure"] = ""
