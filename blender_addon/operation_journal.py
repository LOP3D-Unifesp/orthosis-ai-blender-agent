"""Centralized append-only operation journal for GN editing sessions.

Captures entry types in JSONL format:
  - goal_start:      user message + agent strategy when a task begins
  - goal_strategy:   agent reasoning captured from first text response
  - operation:       structured context/draft operations
  - tool_call:       any tool invocation with metrics (payload/result size, timing)
  - goal_end:        when the agent finishes a turn (includes session dashboard)

Outcomes (accept/reject) are recorded separately in outcomes.jsonl
so the user can mark results after the fact.

Storage layout (Onda 3):
  runtime/journal/
    runs/
      <session_id>/
        <run_id>.jsonl
    index/
      sessions.json
      <session_id>.json
    debug/
      <session_id>/
        <run_id>.jsonl
    outcomes.jsonl

Compatibility:
  ``session_file`` now points to the active run file. The key name is kept
  for backward compatibility with existing callers.
  ``index_file`` now points to ``index/sessions.json``.
"""

from __future__ import annotations

import gzip
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


# Direct mutation op names are not live product metrics in draft-first mode.
_GN_MUTATION_OPS = frozenset()

_BROAD_READ_TOOLS = frozenset({
    "get_scene_summary",
    "resolve_gn_workspace",
    "build_tree_structural_memory",
    "classify_tree_phases",
    "map_clinical_parameter_roles",
    "analyze_scene",
})

_FOCAL_READ_TOOLS = frozenset({
    "get_node_context",
})

_READ_TOOLS = _BROAD_READ_TOOLS | _FOCAL_READ_TOOLS | frozenset({
    "get_gn_hosts",
    "get_tree_parameters",
})

_DASHBOARD_EVENT_COUNTERS = (
    "script_draft_write_attempted",
    "script_draft_write_succeeded",
    "script_draft_write_failed",
    "script_draft_written",
    "script_draft_refined",
    "script_draft_execution_feedback",
    "draft_state_control",
    "tree_structural_memory_used",
    "tree_structural_memory_updated",
    "local_scope_used",
    "session_resumed",
    "resumed_session_state",
    "session_state_reset",
    "session_state_inconsistency",
    "context_requested_from_user",
    "context_provided_by_user_text",
    "context_provided_by_user_screenshot",
    "context_captured_by_tool",
)

_TOOL_PREVIEW_MAX_CHARS = 480
_MAX_SESSION_JOURNALS = 12
_ROTATE_AFTER_DAYS = 14
_ROTATE_AFTER_BYTES = 2_000_000
_VERBOSE_RUNTIME_EVENTS = frozenset({
    "api_usage",
    "tool_dispatched",
    "routing_classified",
    "parsimony_decision",
    "ui_history_hydration_trace",
})


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_metadata_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _new_goal_id() -> str:
    return f"g-{uuid4().hex[:8]}"


def _preview_value(value: Any, max_chars: int = _TOOL_PREVIEW_MAX_CHARS) -> str:
    """Convert any payload to safe compact preview text with truncation."""
    try:
        if isinstance(value, str):
            text = value
        else:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        text = str(value)
    text = (text or "").replace("\r\n", "\n").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + f"... [truncated {len(text) - max_chars} chars]"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _gzip_rotate(path: Path) -> None:
    gz_path = path.with_suffix(path.suffix + ".gz")
    if gz_path.exists():
        try:
            path.unlink()
        except Exception:
            pass
        return
    try:
        with path.open("rb") as src, gzip.open(gz_path, "wb") as dst:
            while True:
                chunk = src.read(1024 * 256)
                if not chunk:
                    break
                dst.write(chunk)
        path.unlink()
    except Exception:
        try:
            if gz_path.exists():
                gz_path.unlink()
        except Exception:
            pass


def _runtime_tool_call_fallback(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    derived: list[dict[str, Any]] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        if str(ev.get("event_type", "")) != "tool_dispatched":
            continue
        payload = ev.get("payload", {})
        if not isinstance(payload, dict):
            payload = {}
        tool_name = str(payload.get("tool") or payload.get("tool_name") or "").strip()
        if not tool_name:
            continue
        derived.append({
            "tool_name": tool_name,
            "payload_size": _safe_int(payload.get("payload_size"), 0),
            "result_size": _safe_int(payload.get("result_size"), 0),
            "round_time_ms": _safe_int(payload.get("elapsed_ms"), 0),
            "status": str(payload.get("status") or "success"),
            "tree_name": str(payload.get("tree_name") or "").strip(),
            "node_name": str(payload.get("node_name") or "").strip(),
            "used_structured_tool": bool(payload.get("used_structured_tool", tool_name != "execute_code")),
            "fallback_to_execute_code_reason": str(payload.get("fallback_to_execute_code_reason") or ""),
            "staged": bool(payload.get("staged", False)),
        })
    return derived


class OperationJournal:
    """Append-only JSONL journal for GN operations and goal context."""

    def __init__(self, project_root: Path):
        self._base_dir = project_root / "runtime" / "journal"
        self._runs_dir = self._base_dir / "runs"
        self._debug_dir = self._base_dir / "debug"
        self._index_dir = self._base_dir / "index"
        self._sessions_index_path = self._index_dir / "sessions.json"
        # Legacy folders kept for migration/recovery helpers.
        self._sessions_dir = self._base_dir / "sessions"
        self._trash_dir = self._sessions_dir / "_trash"
        self._runs_dir.mkdir(parents=True, exist_ok=True)
        self._debug_dir.mkdir(parents=True, exist_ok=True)
        self._index_dir.mkdir(parents=True, exist_ok=True)
        self._sessions_dir.mkdir(parents=True, exist_ok=True)
        self._trash_dir.mkdir(parents=True, exist_ok=True)
        pass  # migration from v1 project root done
        self._lock = threading.Lock()

        self._session_id: str = ""
        self._run_id: str = ""
        self._session_file: Path | None = None
        self._debug_file: Path | None = None
        self._current_goal_id: str = ""
        self._goal_op_count: int = 0
        self._goal_code_exec_count: int = 0
        self._goal_structured_op_count: int = 0
        self._goal_tool_calls: list[dict[str, Any]] = []
        self._goal_runtime_events: list[dict[str, Any]] = []
        self._blend_file: str = ""
        # Accumulated token usage for the current goal
        self._goal_input_tokens: int = 0
        self._goal_output_tokens: int = 0
        # Snapshot of the last completed goal — readable after end_goal()
        self._last_turn_tokens: tuple[int, int] = (0, 0)

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def session_file(self) -> Path | None:
        return self._session_file

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def current_goal_id(self) -> str:
        return self._current_goal_id

    def get_paths(self) -> dict[str, str]:
        session_index_file = (
            str(self._index_dir / f"{self._session_id}.json")
            if self._session_id
            else ""
        )
        return {
            "base_dir": str(self._base_dir),
            "runs_dir": str(self._runs_dir),
            "debug_dir": str(self._debug_dir),
            "run_file": str(self._session_file) if self._session_file else "",
            "debug_file": str(self._debug_file) if self._debug_file else "",
            "run_id": self._run_id,
            "session_index_file": session_index_file,
            "sessions_index_file": str(self._sessions_index_path),
            # Backward-compatible aliases.
            "sessions_dir": str(self._sessions_dir),
            "session_file": str(self._session_file) if self._session_file else "",
            "index_file": str(self._sessions_index_path),
        }

    @staticmethod
    def preview(value: Any, max_chars: int = _TOOL_PREVIEW_MAX_CHARS) -> str:
        return _preview_value(value, max_chars=max_chars)

    def start_session(self, session_id: str, blend_file: str = "") -> None:
        """Bind the journal to a session id (run files are opened per turn)."""
        with self._lock:
            self._session_id = session_id
            self._blend_file = blend_file
            self._run_id = ""
            self._session_file = None
            self._debug_file = None
            self._current_goal_id = ""
            self._goal_op_count = 0
        self._write_index_snapshot(last_event_type="session_start", last_event_status="success")

    def start_run(
        self,
        *,
        run_id: str = "",
        session_id: str = "",
        blend_file: str = "",
    ) -> str:
        """Open a per-turn run file under ``runtime/journal/runs/<session_id>/``."""
        with self._lock:
            sid = str(session_id or self._session_id or "").strip()
            if not sid:
                sid = f"sess-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
            self._session_id = sid

            if blend_file:
                self._blend_file = blend_file

            rid = str(run_id or "").strip()
            if not rid:
                rid = f"run-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
            self._run_id = rid

            session_runs_dir = self._runs_dir / sid
            session_runs_dir.mkdir(parents=True, exist_ok=True)
            self._session_file = session_runs_dir / f"{rid}.jsonl"
            session_debug_dir = self._debug_dir / sid
            session_debug_dir.mkdir(parents=True, exist_ok=True)
            self._debug_file = session_debug_dir / f"{rid}.jsonl"
            self._rotate_journal_files(session_runs_dir, exclude=self._session_file)
            self._rotate_journal_files(session_debug_dir, exclude=self._debug_file)

            self._current_goal_id = ""
            self._goal_op_count = 0
            self._goal_code_exec_count = 0
            self._goal_structured_op_count = 0
            self._goal_tool_calls = []
            self._goal_runtime_events = []
            self._goal_input_tokens = 0
            self._goal_output_tokens = 0

        self._write_index_snapshot(last_event_type="run_start", last_event_status="success")
        return self._run_id

    def bind_run_context(
        self,
        *,
        session_id: str = "",
        run_id: str = "",
        blend_file: str = "",
        goal_id: str = "",
    ) -> None:
        """Attach an external runtime process to an existing agent run."""
        sid = str(session_id or self._session_id or "").strip()
        rid = str(run_id or self._run_id or "").strip()
        if not sid or not rid:
            return
        with self._lock:
            self._session_id = sid
            self._run_id = rid
            if blend_file:
                self._blend_file = blend_file
            session_runs_dir = self._runs_dir / sid
            session_runs_dir.mkdir(parents=True, exist_ok=True)
            self._session_file = session_runs_dir / f"{rid}.jsonl"
            session_debug_dir = self._debug_dir / sid
            session_debug_dir.mkdir(parents=True, exist_ok=True)
            self._debug_file = session_debug_dir / f"{rid}.jsonl"
            if goal_id:
                self._current_goal_id = goal_id
        self._write_index_snapshot(last_event_type="run_bind", last_event_status="success")

    def _rotate_journal_files(self, directory: Path, *, exclude: Path | None = None) -> None:
        try:
            now_ts = datetime.now(timezone.utc).timestamp()
            cutoff_seconds = _ROTATE_AFTER_DAYS * 24 * 60 * 60
            excluded = exclude.resolve() if exclude else None
            for path in directory.glob("*.jsonl"):
                try:
                    if excluded and path.resolve() == excluded:
                        continue
                    stat = path.stat()
                    too_old = (now_ts - stat.st_mtime) > cutoff_seconds
                    too_large = stat.st_size > _ROTATE_AFTER_BYTES
                    if too_old or too_large:
                        _gzip_rotate(path)
                except Exception:
                    continue
        except Exception:
            pass

    def _ensure_session(self) -> Path:
        if self._session_file is None:
            self.start_run()
        return self._session_file  # type: ignore[return-value]

    def _append(self, entry: dict[str, Any]) -> None:
        path = self._ensure_session()
        entry["session_id"] = self._session_id
        entry["run_id"] = self._run_id
        with self._lock:
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._write_index_snapshot(
            last_event_type=str(entry.get("type", "event")),
            last_event_status=str(entry.get("status", "success")),
        )

    def _append_debug(self, entry: dict[str, Any]) -> None:
        if self._debug_file is None:
            self._ensure_session()
        if self._debug_file is None:
            return
        entry["session_id"] = self._session_id
        entry["run_id"] = self._run_id
        with self._lock:
            with self._debug_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _write_index_snapshot(self, *, last_event_type: str, last_event_status: str) -> None:
        """Write Onda 3 indexes: per-session and global sessions index."""
        if not self._session_id:
            return

        now = _utc_now_iso()
        session_path = str(self._session_file) if self._session_file else ""
        run_entry = {
            "run_id": self._run_id,
            "run_file": session_path,
            "blend_file": self._blend_file,
            "updated_at": now,
            "last_event_type": last_event_type,
            "last_event_status": last_event_status,
        }
        session_index_path = self._index_dir / f"{self._session_id}.json"
        session_payload: dict[str, Any] = {
            "schema_version": "1.0",
            "session_id": self._session_id,
            "updated_at": now,
            "journal_base_dir": str(self._base_dir),
            "active_run_id": self._run_id,
            "active_run_file": session_path,
            "runs": [],
        }

        try:
            if session_index_path.exists():
                with session_index_path.open("r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    session_payload.update({k: v for k, v in loaded.items() if k in session_payload})
                    if isinstance(loaded.get("runs"), list):
                        session_payload["runs"] = loaded["runs"]
        except Exception:
            pass

        runs = session_payload.get("runs", [])
        if not isinstance(runs, list):
            runs = []
        if self._run_id and session_path:
            runs = [
                entry for entry in runs
                if not (isinstance(entry, dict) and str(entry.get("run_id", "") or "") == self._run_id)
            ]
            runs.append(run_entry)
        session_payload["runs"] = runs[-_MAX_SESSION_JOURNALS:]
        session_payload["updated_at"] = now
        session_payload["active_run_id"] = self._run_id
        session_payload["active_run_file"] = session_path

        try:
            with session_index_path.open("w", encoding="utf-8") as f:
                json.dump(session_payload, f, indent=2, ensure_ascii=False)
                f.write("\n")
        except Exception:
            pass
        self._write_sessions_index_snapshot(now=now, run_entry=run_entry)

    def _write_sessions_index_snapshot(self, *, now: str, run_entry: dict[str, Any]) -> None:
        payload: dict[str, Any] = {
            "schema_version": "1.0",
            "updated_at": now,
            "journal_base_dir": str(self._base_dir),
            "sessions": [],
        }
        try:
            if self._sessions_index_path.exists():
                with self._sessions_index_path.open("r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    payload.update({k: v for k, v in loaded.items() if k in payload})
                    if isinstance(loaded.get("sessions"), list):
                        payload["sessions"] = loaded["sessions"]
        except Exception:
            pass

        sessions = payload.get("sessions", [])
        if not isinstance(sessions, list):
            sessions = []

        current_entry = {
            "session_id": self._session_id,
            "active_run_id": self._run_id,
            "active_run_file": run_entry.get("run_file", ""),
            "blend_file": self._blend_file,
            "updated_at": now,
            "last_event_type": run_entry.get("last_event_type", ""),
            "last_event_status": run_entry.get("last_event_status", ""),
        }
        sessions = [
            entry for entry in sessions
            if not (isinstance(entry, dict) and str(entry.get("session_id", "") or "") == self._session_id)
        ]
        sessions.append(current_entry)
        payload["sessions"] = sessions[-_MAX_SESSION_JOURNALS:]
        payload["updated_at"] = now

        try:
            with self._sessions_index_path.open("w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
                f.write("\n")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Goal lifecycle
    # ------------------------------------------------------------------

    def start_goal(
        self,
        *,
        user_message: str,
        agent_strategy: str = "",
        tree_name: str = "",
        blend_file: str = "",
    ) -> str:
        """Record that a new user goal has started. Returns the goal_id."""
        self._ensure_session()
        goal_id = _new_goal_id()
        self._current_goal_id = goal_id
        self._goal_op_count = 0
        self._goal_code_exec_count = 0
        self._goal_structured_op_count = 0
        self._goal_tool_calls = []
        self._goal_runtime_events = []
        self._goal_input_tokens = 0
        self._goal_output_tokens = 0
        if blend_file:
            self._blend_file = blend_file

        self._append({
            "type": "goal_start",
            "goal_id": goal_id,
            "timestamp": _utc_now_iso(),
            "blend_file": self._blend_file,
            "user_message": user_message,
            "agent_strategy": agent_strategy,
            "tree_name": tree_name,
        })
        return goal_id

    def update_strategy(self, strategy_text: str) -> None:
        """Append agent strategy text discovered after goal_start.

        This captures the full agent reasoning from the first text response.
        """
        if not self._current_goal_id:
            return
        self._append({
            "type": "goal_strategy",
            "goal_id": self._current_goal_id,
            "timestamp": _utc_now_iso(),
            "agent_strategy": strategy_text,
        })

    def end_goal(self, *, final_status: str = "completed") -> None:
        """Record that the current goal turn has ended, including a session dashboard."""
        if not self._current_goal_id:
            return

        effective_tool_calls = list(self._goal_tool_calls)
        if not effective_tool_calls:
            effective_tool_calls = _runtime_tool_call_fallback(self._goal_runtime_events)

        # Build per-tool breakdown
        tool_breakdown: dict[str, int] = {}
        total_payload_bytes = 0
        total_result_bytes = 0
        structured_tool_calls = 0
        code_tool_calls = 0
        broad_reads_count = 0
        focal_reads_count = 0
        execute_code_fallbacks = 0
        read_tool_counts: dict[str, int] = {}
        staged_execute_code_calls = 0
        for tc in effective_tool_calls:
            tn = tc.get("tool_name", "?")
            tool_breakdown[tn] = tool_breakdown.get(tn, 0) + 1
            total_payload_bytes += tc.get("payload_size", 0)
            total_result_bytes += tc.get("result_size", 0)
            if bool(tc.get("used_structured_tool", False)):
                structured_tool_calls += 1
            if tn == "execute_code":
                code_tool_calls += 1
                if bool(tc.get("staged", False)):
                    staged_execute_code_calls += 1
                if tc.get("fallback_to_execute_code_reason"):
                    execute_code_fallbacks += 1
            if tc.get("status") != "blocked" and tn in _BROAD_READ_TOOLS:
                broad_reads_count += 1
            if tc.get("status") != "blocked" and tn in _FOCAL_READ_TOOLS:
                focal_reads_count += 1
            if tc.get("status") != "blocked" and tn in _READ_TOOLS:
                read_tool_counts[tn] = read_tool_counts.get(tn, 0) + 1

        repeated_reads_count = sum(max(0, c - 1) for c in read_tool_counts.values())

        runtime_event_counts: dict[str, int] = {}
        skipped_reads_count = 0
        total_api_rounds = 0
        knowledge_files_injected = 0
        knowledge_tokens_estimated = 0
        analytical_skills_used = 0
        session_memory_used = False
        session_memory_updated = False
        structural_index_used = False
        structural_index_updated = False
        tree_structural_memory_used = False
        tree_structural_memory_updated = False
        local_scope_used = False
        selected_nodes_count = 0
        active_frame_name = ""
        changes_since_last_turn_count = 0
        nodes_precreated_by_user = 0
        agent_scope = ""
        manual_execution_roundtrip = False
        memory_vs_runtime_read_reason = ""
        staged_payload_classification = ""
        staged_expected_visible_scene_change = ""
        staged_script_behavior = ""
        staged_target_summary: dict[str, Any] = {}
        canonical_gn_target: dict[str, Any] = {}
        canonical_gn_target_source = ""
        canonical_gn_target_explicit = False
        execute_code_calls_read_only = 0
        execute_code_calls_mutating = 0
        code_executions_read_only = 0
        code_executions_mutating = 0
        code_executions_from_runtime_events = 0
        for ev in self._goal_runtime_events:
            etype = str(ev.get("event_type", "unknown"))
            runtime_event_counts[etype] = runtime_event_counts.get(etype, 0) + 1
            payload = ev.get("payload", {}) if isinstance(ev.get("payload"), dict) else {}
            if etype == "read_skipped_parsimony":
                skipped_reads_count += 1
            if etype == "api_usage":
                total_api_rounds += 1
            if etype == "knowledge_selected":
                injected = payload.get("injected_files", payload.get("selected_files", []))
                if isinstance(injected, list):
                    knowledge_files_injected = len(injected)
                tokens = payload.get("estimated_tokens_total", payload.get("estimated_tokens", 0))
                try:
                    knowledge_tokens_estimated = int(tokens)
                except Exception:
                    knowledge_tokens_estimated = 0
            if etype == "skills_activated":
                used = payload.get("skills_used", payload.get("skills", []))
                if isinstance(used, list):
                    analytical_skills_used = len(used)
            if etype == "session_memory_used":
                try:
                    relevant_nodes_count = int(payload.get("relevant_nodes_count", 0) or 0)
                except Exception:
                    relevant_nodes_count = 0
                if "used" in payload:
                    event_used = bool(payload.get("used", False))
                else:
                    event_used = bool(
                        payload.get("keys")
                        or payload.get("has_goal")
                        or payload.get("has_hypothesis")
                        or relevant_nodes_count > 0
                        or payload
                    )
                session_memory_used = session_memory_used or event_used
            if etype == "session_memory_updated":
                session_memory_updated = session_memory_updated or bool(payload.get("session_memory_updated", True))
            if etype == "structural_index_used":
                structural_index_used = structural_index_used or bool(payload.get("used", False))
            if etype == "structural_index_updated":
                structural_index_updated = structural_index_updated or bool(payload.get("structural_index_updated", True))
            if etype == "tree_structural_memory_used":
                tree_structural_memory_used = True
            if etype == "tree_structural_memory_updated":
                tree_structural_memory_updated = True
            if etype == "local_scope_used":
                local_scope_used = True
                selected_nodes_count = max(selected_nodes_count, int(payload.get("selected_nodes_count", 0) or 0))
                scope_name = str(payload.get("active_frame_name", "")).strip()
                if scope_name:
                    active_frame_name = scope_name
                scope_type = str(payload.get("scope_type", "")).strip()
                if scope_type:
                    agent_scope = scope_type
            if etype == "changes_since_last_turn":
                changes_since_last_turn_count = max(
                    changes_since_last_turn_count,
                    int(payload.get("changes_since_last_turn_count", 0) or 0),
                )
            if etype == "manual_execution_roundtrip":
                manual_execution_roundtrip = True
                nodes = payload.get("nodes", [])
                if isinstance(nodes, list):
                    nodes_precreated_by_user = max(nodes_precreated_by_user, len(nodes))
            if etype == "memory_vs_runtime_read_reason":
                memory_vs_runtime_read_reason = str(payload.get("reason", "") or memory_vs_runtime_read_reason)
            if etype == "staged_plan_created":
                staged_payload_classification = str(
                    payload.get("classification", "") or staged_payload_classification
                ).strip()
                staged_expected_visible_scene_change = str(
                    payload.get("expected_visible_scene_change", "")
                    or staged_expected_visible_scene_change
                ).strip()
                staged_script_behavior = str(payload.get("script_behavior", "") or staged_script_behavior).strip()
                target_summary = payload.get("target_summary")
                if isinstance(target_summary, dict) and target_summary:
                    staged_target_summary = dict(target_summary)
            if etype == "canonical_gn_target_resolved":
                target = payload.get("target")
                if isinstance(target, dict) and target:
                    canonical_gn_target = dict(target)
                canonical_gn_target_source = str(payload.get("source", "") or canonical_gn_target_source).strip()
                canonical_gn_target_explicit = bool(payload.get("explicit", canonical_gn_target_explicit))
            if etype == "execute_code_attempt":
                classification = str(payload.get("classification", "") or "").strip()
                staged = bool(payload.get("staged", False))
                if classification == "mutating":
                    execute_code_calls_mutating += 1
                elif classification == "read_only":
                    execute_code_calls_read_only += 1
                if staged:
                    continue
                code_executions_from_runtime_events += 1
                if classification == "mutating":
                    code_executions_mutating += 1
                elif classification == "read_only":
                    code_executions_read_only += 1

        code_executions = max(self._goal_code_exec_count, code_executions_from_runtime_events)
        code_tool_calls = max(code_tool_calls, runtime_event_counts.get("execute_code_attempt", 0))

        ratio_value: str | float
        if code_tool_calls == 0:
            ratio_value = "structured_only"
        else:
            ratio_value = round(structured_tool_calls / max(code_tool_calls, 1), 3)

        dashboard = {
            "structured_ops": self._goal_structured_op_count,
            "code_executions": code_executions,
            "total_tool_calls": len(effective_tool_calls),
            "runtime_events": len(self._goal_runtime_events),
            "tool_breakdown": tool_breakdown,
            "total_payload_bytes": total_payload_bytes,
            "total_result_bytes": total_result_bytes,
            "input_tokens": self._goal_input_tokens,
            "output_tokens": self._goal_output_tokens,
            "total_tokens": self._goal_input_tokens + self._goal_output_tokens,
            "structured_vs_code_ratio": {
                "structured_tool_calls": structured_tool_calls,
                "execute_code_calls": code_tool_calls,
                "ratio": ratio_value,
            },
            "total_api_rounds": total_api_rounds,
            "knowledge_files_injected": knowledge_files_injected,
            "knowledge_tokens_estimated": knowledge_tokens_estimated,
            "analytical_skills_used": analytical_skills_used,
            "broad_reads_count": broad_reads_count,
            "focal_reads_count": focal_reads_count,
            "skipped_reads_count": skipped_reads_count,
            "execute_code_fallbacks": execute_code_fallbacks,
            "repeated_reads_count": repeated_reads_count,
            "runtime_event_breakdown": runtime_event_counts,
            "session_memory_used": session_memory_used,
            "session_memory_updated": session_memory_updated,
            "structural_index_used": structural_index_used,
            "structural_index_updated": structural_index_updated,
            "tree_structural_memory_used": tree_structural_memory_used,
            "tree_structural_memory_updated": tree_structural_memory_updated,
            "local_scope_used": local_scope_used,
            "selected_nodes_count": selected_nodes_count,
            "active_frame_name": active_frame_name,
            "changes_since_last_turn_count": changes_since_last_turn_count,
            "nodes_precreated_by_user": nodes_precreated_by_user,
            "template_used": "",
            "agent_scope": agent_scope,
            "manual_execution_roundtrip": manual_execution_roundtrip,
            "memory_vs_runtime_read_reason": memory_vs_runtime_read_reason,
            "staged_payload_classification": staged_payload_classification,
            "staged_expected_visible_scene_change": staged_expected_visible_scene_change,
            "staged_script_behavior": staged_script_behavior,
            "staged_target_summary": staged_target_summary,
            "canonical_gn_target": canonical_gn_target,
            "canonical_gn_target_source": canonical_gn_target_source,
            "canonical_gn_target_explicit": canonical_gn_target_explicit,
            "execute_code_calls_read_only": execute_code_calls_read_only,
            "execute_code_calls_mutating": execute_code_calls_mutating,
            "code_executions_read_only": code_executions_read_only,
            "code_executions_mutating": code_executions_mutating,
            "staged_execute_code_calls": staged_execute_code_calls,
        }
        for obsolete_key in (
            "structured_vs_code_ratio",
            "execute_code_fallbacks",
            "staged_payload_classification",
            "staged_expected_visible_scene_change",
            "staged_script_behavior",
            "staged_target_summary",
            "execute_code_calls_read_only",
            "execute_code_calls_mutating",
            "code_executions_read_only",
            "code_executions_mutating",
            "staged_execute_code_calls",
        ):
            dashboard.pop(obsolete_key, None)
        for event_name in _DASHBOARD_EVENT_COUNTERS:
            dashboard[f"{event_name}_count"] = int(runtime_event_counts.get(event_name, 0))

        self._append({
            "type": "goal_end",
            "goal_id": self._current_goal_id,
            "timestamp": _utc_now_iso(),
            "operations_count": self._goal_op_count,
            "final_status": final_status,
            "outcome": None,
            "dashboard": dashboard,
        })
        self._last_turn_tokens = (self._goal_input_tokens, self._goal_output_tokens)
        self._current_goal_id = ""
        self._goal_op_count = 0
        self._goal_code_exec_count = 0
        self._goal_structured_op_count = 0
        self._goal_tool_calls = []
        self._goal_runtime_events = []
        self._goal_input_tokens = 0
        self._goal_output_tokens = 0

    # ------------------------------------------------------------------
    # Operation logging
    # ------------------------------------------------------------------

    def get_last_turn_tokens(self) -> tuple[int, int]:
        """Return ``(input_tokens, output_tokens)`` from the last completed turn."""
        return self._last_turn_tokens

    def accumulate_tokens(self, input_tokens: int, output_tokens: int) -> None:
        """Add API token usage for the current goal."""
        self._goal_input_tokens += input_tokens
        self._goal_output_tokens += output_tokens

    def log_tool_call(
        self,
        *,
        tool_name: str,
        payload_size: int,
        result_size: int,
        round_time_ms: int,
        status: str = "success",
        tool_args_preview: str = "",
        tool_result_preview: str = "",
        routing_reason: str = "",
        tree_name: str = "",
        node_name: str = "",
        source_route: str = "",
        used_structured_tool: bool | None = None,
        fallback_to_execute_code_reason: str = "",
        structured_tool_available: bool | None = None,
        execute_code_inevitable: bool | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Log every tool invocation with size and timing metrics."""
        structured = bool(used_structured_tool) if used_structured_tool is not None else (tool_name != "execute_code")
        entry = {
            "tool_name": tool_name,
            "payload_size": payload_size,
            "result_size": result_size,
            "round_time_ms": round_time_ms,
            "status": status,
            "tool_args_preview": _preview_value(tool_args_preview),
            "tool_result_preview": _preview_value(tool_result_preview),
            "routing_reason": routing_reason,
            "tree_name": tree_name,
            "node_name": node_name,
            "source_route": source_route,
            "used_structured_tool": structured,
            "fallback_to_execute_code_reason": fallback_to_execute_code_reason,
            "structured_tool_available": structured_tool_available,
            "execute_code_inevitable": execute_code_inevitable,
            "metadata": metadata or {},
        }
        self._goal_tool_calls.append(entry)
        self._append({
            "type": "tool_call",
            "goal_id": self._current_goal_id or "untracked",
            "timestamp": _utc_now_iso(),
            **entry,
        })

    def log_runtime_event(
        self,
        *,
        event_type: str,
        payload: dict[str, Any] | None = None,
        status: str = "info",
    ) -> None:
        """Log orchestration/runtime events beyond plain tool calls."""
        entry = {
            "event_type": event_type,
            "status": status,
            "payload": payload or {},
        }
        self._goal_runtime_events.append(entry)
        journal_entry = {
            "type": "runtime_event",
            "goal_id": self._current_goal_id or "untracked",
            "timestamp": _utc_now_iso(),
            **entry,
        }
        if event_type in _VERBOSE_RUNTIME_EVENTS:
            self._append_debug(journal_entry)
            return
        self._append(journal_entry)

    def is_mutation(self, tool_name: str) -> bool:
        """Return True if this tool name should be journaled."""
        return tool_name in _GN_MUTATION_OPS

    def log_operation(
        self,
        *,
        tool_name: str,
        tree_name: str,
        operations: list[dict[str, Any]] | None = None,
        params: dict[str, Any] | None = None,
        status: str = "success",
        error: str | None = None,
    ) -> None:
        """Log one GN mutation operation."""
        if not self.is_mutation(tool_name):
            return

        goal_id = self._current_goal_id or "untracked"

        self._goal_op_count += 1
        self._goal_structured_op_count += 1
        self._append({
            "type": "operation",
            "goal_id": goal_id,
            "timestamp": _utc_now_iso(),
            "tree_name": tree_name,
            "op": tool_name,
            "params": params or {},
            "status": status,
            "error": error,
        })

    def log_code_execution(
        self,
        *,
        code: str,
        status: str = "success",
        error: str | None = None,
        stdout: str | None = None,
    ) -> None:
        """Log an execute_code call with its full Python code."""
        goal_id = self._current_goal_id or "untracked"
        self._goal_op_count += 1
        self._goal_code_exec_count += 1
        self._append({
            "type": "code_execution",
            "goal_id": goal_id,
            "timestamp": _utc_now_iso(),
            "code": code,
            "status": status,
            "error": error,
            "stdout": stdout[:500] if stdout and len(stdout) > 500 else stdout,
        })

    # ------------------------------------------------------------------
    # Outcome recording (user-driven)
    # ------------------------------------------------------------------

    def record_outcome(
        self,
        *,
        goal_id: str,
        outcome: str,
        notes: str = "",
    ) -> None:
        """Record user's accept/reject judgment for a goal."""
        outcomes_path = self._base_dir / "outcomes.jsonl"
        entry = {
            "goal_id": goal_id,
            "session_id": self._session_id,
            "outcome": outcome,
            "notes": notes,
            "timestamp": _utc_now_iso(),
        }
        with self._lock:
            with outcomes_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def record_last_outcome(self, outcome: str, notes: str = "") -> dict[str, Any]:
        """Record outcome for the most recent goal in this session.

        Returns info about what was recorded, or error if no goal found.
        """
        last_goal = self._find_last_goal_id()
        if not last_goal:
            return {"status": "error", "error": "No recent goal found to mark."}

        self.record_outcome(goal_id=last_goal, outcome=outcome, notes=notes)
        return {
            "status": "success",
            "goal_id": last_goal,
            "outcome": outcome,
        }

    def _find_last_goal_id(self) -> str:
        """Find the most recent goal_id from the current session file."""
        path = self._session_file
        if not path or not path.exists():
            return ""
        last_goal = ""
        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if entry.get("type") in ("goal_start", "goal_end"):
                        last_goal = entry.get("goal_id", "")
        except Exception:
            pass
        return last_goal

    # ------------------------------------------------------------------
    # Session recovery — read last session for context injection
    # ------------------------------------------------------------------

    def get_last_session_summary(self, max_goals: int = 3) -> str:
        """Build a compact text summary of the most recent session for system prompt injection."""
        session_files = self._sorted_session_files()
        if not session_files:
            return ""

        # Use the most recent file (could be current or previous session)
        target = session_files[-1]
        # If current session is empty, use the one before it
        if target == self._session_file and len(session_files) > 1:
            if target.stat().st_size == 0:
                target = session_files[-2]

        return self._summarize_session_file(target, max_goals=max_goals)

    def get_previous_session_summary(self, max_goals: int = 3) -> str:
        """Build summary from the session BEFORE the current one."""
        session_files = self._sorted_session_files()
        # Filter out current session
        previous = [f for f in session_files if f != self._session_file]
        if not previous:
            return ""
        return self._summarize_session_file(previous[-1], max_goals=max_goals)

    def _sorted_session_files(self) -> list[Path]:
        session_files: list[Path] = []
        # Onda 3 layout: runs/<session_id>/<run_id>.jsonl
        if self._session_id:
            session_runs_dir = self._runs_dir / self._session_id
            if session_runs_dir.exists():
                session_files.extend([path for path in session_runs_dir.glob("*.jsonl") if path.is_file()])

        # Legacy layout kept for backwards-compatible summarisation.
        session_files.extend([path for path in self._sessions_dir.glob("*.jsonl") if path.is_file()])
        if not session_files:
            return []

        def _sort_key(path: Path) -> tuple[int, float, str]:
            try:
                resolved = path.resolve()
            except Exception:
                resolved = path
            try:
                mtime = path.stat().st_mtime
            except Exception:
                mtime = float("-inf")
            return (1, mtime, resolved.name)

        return sorted(session_files, key=_sort_key)

    def _summarize_session_file(self, path: Path, max_goals: int = 3) -> str:
        """Parse a JSONL session file and produce a compact text summary."""
        if not path.exists():
            return ""

        goals: list[dict[str, Any]] = []
        current_goal: dict[str, Any] = {}
        ops_for_goal: list[str] = []

        try:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    etype = entry.get("type")

                    if etype == "goal_start":
                        if current_goal:
                            current_goal["ops"] = ops_for_goal
                            goals.append(current_goal)
                        current_goal = {
                            "goal_id": entry.get("goal_id", ""),
                            "user_message": entry.get("user_message", ""),
                            "strategy": entry.get("agent_strategy", ""),
                            "tree": entry.get("tree_name", ""),
                            "ops": [],
                            "status": "in_progress",
                            "outcome": None,
                        }
                        ops_for_goal = []

                    elif etype == "goal_strategy":
                        if current_goal:
                            current_goal["strategy"] = entry.get("agent_strategy", "")

                    elif etype == "operation":
                        op = entry.get("op", "?")
                        params = entry.get("params", {})
                        op_desc = self._describe_op(op, params)
                        ops_for_goal.append(op_desc)

                    elif etype == "goal_end":
                        if current_goal:
                            current_goal["status"] = entry.get("final_status", "completed")
                            current_goal["op_count"] = entry.get("operations_count", len(ops_for_goal))

            # Capture last goal if file didn't end with goal_end
            if current_goal:
                current_goal["ops"] = ops_for_goal
                goals.append(current_goal)

        except Exception:
            return ""

        if not goals:
            return ""

        # Load outcomes
        outcomes = self._load_outcomes()

        # Build summary text from last N goals
        recent_goals = goals[-max_goals:]
        lines = [f"Previous session ({path.stem}):"]

        for g in recent_goals:
            outcome = outcomes.get(g["goal_id"])
            outcome_str = f", outcome: {outcome}" if outcome else ""
            lines.append(f"- Goal: \"{g['user_message'][:120]}\"")
            if g.get("strategy"):
                lines.append(f"  Strategy: \"{g['strategy'][:200]}\"")
            if g.get("tree"):
                lines.append(f"  Tree: {g['tree']}")
            lines.append(f"  Operations: {g.get('op_count', len(g['ops']))}, status: {g['status']}{outcome_str}")
            if g["ops"]:
                for op_line in g["ops"][:8]:
                    lines.append(f"    - {op_line}")
                if len(g["ops"]) > 8:
                    lines.append(f"    ... +{len(g['ops']) - 8} more")

        return "\n".join(lines)

    def _load_outcomes(self) -> dict[str, str]:
        """Load all outcomes into a goal_id -> outcome mapping."""
        outcomes_path = self._base_dir / "outcomes.jsonl"
        if not outcomes_path.exists():
            return {}
        result: dict[str, str] = {}
        try:
            with outcomes_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        gid = entry.get("goal_id", "")
                        if gid:
                            result[gid] = entry.get("outcome", "unknown")
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass
        return result

    @staticmethod
    def _describe_op(op: str, params: dict[str, Any]) -> str:
        """Produce a compact human-readable description of one operation."""
        if op == "create_node":
            return f"create {params.get('type', '?')} as \"{params.get('name', '?')}\""
        if op == "connect_nodes":
            return (
                f"connect {params.get('from_node', '?')}:{params.get('from_socket', '?')} "
                f"-> {params.get('to_node', '?')}:{params.get('to_socket', '?')}"
            )
        if op == "disconnect_nodes":
            return (
                f"disconnect {params.get('from_node', '?')}:{params.get('from_socket', '?')} "
                f"-x- {params.get('to_node', '?')}:{params.get('to_socket', '?')}"
            )
        if op == "set_node_value":
            return f"set {params.get('node', '?')}:{params.get('socket', '?')} = {params.get('value', '?')}"
        if op == "set_node_property":
            return f"set {params.get('node', '?')}.{params.get('property', '?')} = {params.get('value', '?')}"
        if op == "delete_node":
            return f"delete \"{params.get('name', '?')}\""
        if op == "move_node":
            loc = params.get("location", [0, 0])
            return f"move \"{params.get('name', '?')}\" to ({loc[0]}, {loc[1]})"
        if op == "create_frame":
            children = params.get("children", [])
            return f"frame \"{params.get('name', '?')}\" with {len(children)} children"
        if op == "insert_existing_group":
            return f"insert group \"{params.get('group_name', '?')}\" as \"{params.get('name', '?')}\""
        return f"{op} {json.dumps(params, ensure_ascii=False)[:80]}"
