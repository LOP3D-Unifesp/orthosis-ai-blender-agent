"""Persistence and legacy migration for the v1 structured session schema.

Per-file session design
=======================

Each .blend file gets its own session file keyed by an 8-char MD5 hash of
the normalised absolute blend path:

    runtime/sessions_v1/session_<hash8>.json   ← per-file v1 session
    runtime/sessions_v1/session.json           ← fallback when blend_path unknown
    runtime/sessions/session.json              ← legacy flat-dict (migration only)
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from .schema import (
    SCHEMA_VERSION,
    BaselineWorkspace,
    ExecutionState,
    Focus,
    History,
    HistoryMessage,
    Identity,
    LastFailure,
    Lifecycle,
    OperationalState,
    Session,
    UIState,
    compute_focus_signature,
    new_continuity_token,
    new_session_id,
    utc_now_iso,
)


V1_SUBDIR = "sessions_v1"
LEGACY_SUBDIR = "sessions"
SESSION_FILENAME = "session.json"


def _blend_path_to_session_name(blend_path: str) -> str:
    """Return the session filename for a given blend file path.

    Uses an 8-char MD5 hash of the normalised absolute path so each .blend
    file has its own session file. Falls back to SESSION_FILENAME when
    blend_path is empty (Blender not yet pointing at any file).
    """
    if not blend_path:
        return SESSION_FILENAME
    normalized = Path(blend_path).resolve().as_posix().lower()
    h = hashlib.md5(normalized.encode("utf-8")).hexdigest()[:8]
    return f"session_{h}.json"


# DIAG: helper — print + return value for easy removal
def _diag(tag: str, msg: str) -> None:
    import sys
    print(f"[DIAG/{tag}] {msg}", file=sys.stderr, flush=True)


@dataclass
class SessionV1Store:
    """Filesystem-backed store for v1 :class:`Session` objects."""

    project_root: Path

    def __post_init__(self) -> None:
        from .chat_store import ChatHistoryStore
        self._chat_store = ChatHistoryStore(self.project_root)

    # ---- paths -----------------------------------------------------------

    def _v1_dir(self) -> Path:
        path = self.project_root / "runtime" / V1_SUBDIR
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _legacy_dir(self) -> Path:
        return self.project_root / "runtime" / LEGACY_SUBDIR

    def _archive_dir(self) -> Path:
        path = self._v1_dir() / "archive"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _quarantine_dir(self) -> Path:
        path = self._v1_dir() / "archive" / "quarantine"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _quarantine_invalid_file(self, path: Path, reason: str) -> Path:
        """Move a corrupt/truncated session file to archive/quarantine/."""
        import time as _time
        ts = _time.strftime("%Y%m%dT%H%M%SZ", _time.gmtime())
        dest = self._quarantine_dir() / f"{path.stem}__{reason}__{ts}{path.suffix}"
        try:
            path.rename(dest)
            _diag("store.quarantine", f"MOVED {path.name} → quarantine/{dest.name}")
        except Exception as exc:
            _diag("store.quarantine", f"FAILED to move {path.name}: {exc}")
        return dest

    def v1_path(self, blend_path: str = "") -> Path:
        return self._v1_dir() / _blend_path_to_session_name(blend_path)

    def legacy_path(self) -> Path:
        return self._legacy_dir() / SESSION_FILENAME

    # ---- public API ------------------------------------------------------

    def load(self, blend_path: str = "") -> Session:
        """Load the session for ``blend_path`` from the current runtime only.

        Each blend file has its own session file keyed by an 8-char hash of
        the path. When the hash-based file doesn't exist, the directory is
        scanned for any session whose focus.blend_path matches — this handles
        files created by older naming conventions. A match is re-saved under
        the new name so subsequent loads skip the scan.

        Legacy import from sibling project roots is intentionally *not*
        performed here. Recovery/import is an explicit operation exposed via
        :meth:`import_legacy_sessions_explicit`.
        """
        import time as _time
        _t0 = _time.time()

        # DIAG: throttle to avoid flooding on every draw tick
        _normalized_for_diag = Path(blend_path).resolve().as_posix().lower() if blend_path else "(empty)"
        _hash_for_diag = _blend_path_to_session_name(blend_path)
        _prev_load = getattr(self, "_diag_last_blend_path", None)
        _diag_active = (blend_path != _prev_load)
        if _diag_active:
            self._diag_last_blend_path = blend_path  # type: ignore[attr-defined]
            _diag("store.load", f"ENTER blend_path={blend_path!r}")
            _diag("store.load", f"  normalized={_normalized_for_diag}")
            _diag("store.load", f"  hash_file={_hash_for_diag}")
        if not bool(getattr(self, "_diag_auto_import_disabled_emitted", False)):
            _diag("store.load", "  LEGACY_IMPORT_AUTO=disabled (explicit import only)")
            self._diag_auto_import_disabled_emitted = True  # type: ignore[attr-defined]

        v1 = self.v1_path(blend_path)
        if _diag_active:
            _diag("store.load", f"  v1_path={v1}  exists={v1.exists()}")
        if v1.exists():
            _mtime = v1.stat().st_mtime
            payload = _read_json(v1)
            if isinstance(payload, dict):
                session = Session.from_dict(payload)
                session = self._hydrate_chat_history(session)
                _msgs = getattr(getattr(session, "history", None), "messages", [])
                _first = getattr(_msgs[0], "content", "")[:60] if _msgs else "(none)"
                _last  = getattr(_msgs[-1], "content", "")[:60] if _msgs else "(none)"
                _diag("store.load", f"  SOURCE=V1_HASH  msg_count={len(_msgs)}  mtime={_mtime:.0f}")
                _diag("store.load", f"  first={_first!r}  last={_last!r}")
                return session
            else:
                # File exists but is not valid JSON (truncated or corrupted).
                # Quarantine it so subsequent loads start fresh without losing the file.
                self._quarantine_invalid_file(v1, "invalid_json")
                _diag("store.load", f"  V1_HASH invalid JSON — quarantined, falling through to fresh session")

        if blend_path:
            found = self._find_session_by_blend_path(blend_path)
            if found is not None:
                found = self._hydrate_chat_history(found)
                _msgs = getattr(getattr(found, "history", None), "messages", [])
                _diag("store.load", f"  SOURCE=V1_SCAN  msg_count={len(_msgs)}")
                self.save(found, blend_path)
                return found
            if _diag_active:
                _diag("store.load", "  V1_SCAN found nothing")

        # Only use the generic session.json (non-path-specific) when blend_path
        # is unknown.  When blend_path is provided and no matching V1 or
        # path-scanned session was found, session.json belongs to a *different*
        # blend file (the last one that was open), so loading it would ghost
        # its history into the wrong panel.
        if not blend_path:
            legacy = self.legacy_path()
            if _diag_active:
                _diag("store.load", f"  legacy_path={legacy}  exists={legacy.exists()}")
            if legacy.exists():
                legacy_payload = _read_json(legacy)
                if isinstance(legacy_payload, dict):
                    session = migrate_legacy_state(legacy_payload, blend_path=blend_path)
                    session = self._hydrate_chat_history(session)
                    _msgs = getattr(getattr(session, "history", None), "messages", [])
                    _diag("store.load", f"  SOURCE=LEGACY_SESSION_JSON  msg_count={len(_msgs)}")
                    return session
        else:
            if _diag_active:
                legacy = self.legacy_path()
                _diag("store.load", f"  LEGACY_SESSION_JSON skipped (blend_path provided)  legacy={legacy}  exists={legacy.exists()}")

        # Last-resort: scan runtime/sessions/ for a hash-named legacy flat
        # session whose blend_path matches.  These files are orphaned by the
        # current session_<hash8>.json naming convention and are never reached
        # by legacy_path() above.  Migrating here recovers any useful history
        # while migrate_legacy_state() explicitly discards approval/plan state.
        if blend_path:
            legacy_flat = self._find_legacy_flat_session_by_blend_path(blend_path)
            if legacy_flat is not None:
                migrated = migrate_legacy_state(legacy_flat, blend_path=blend_path)
                migrated = self._hydrate_chat_history(migrated)
                _msgs = getattr(getattr(migrated, "history", None), "messages", [])
                _diag("store.load", f"  SOURCE=LEGACY_FLAT_SCAN  msg_count={len(_msgs)}")
                self.save(migrated, blend_path)
                return migrated
            if _diag_active:
                _diag("store.load", "  LEGACY_FLAT_SCAN found nothing")

        if _diag_active:
            _diag("store.load", f"  SOURCE=NEW_EMPTY  elapsed={(_time.time()-_t0)*1000:.1f}ms")
        return Session.new(blend_path=blend_path)

    def import_legacy_sessions_explicit(self, blend_path: str = "") -> list[Path]:
        """No-op: v1→v2 migration completed. Kept for API compat."""
        return []

    def diagnose_v1_session(self, blend_path: str = "") -> dict[str, Any]:
        """Describe the current V1 session, sibling candidates, and archives."""
        current_path = self.v1_path(blend_path)
        current_info = self._describe_session_file(current_path, current=True)
        candidates = self._candidate_v1_sessions(blend_path, include_archive=False)
        archives = self._candidate_v1_sessions(blend_path, include_archive=True)
        return {
            "blend_path": str(blend_path or ""),
            "current": current_info,
            "candidates": candidates,
            "archive": {
                "exists": bool(archives),
                "files": archives,
            },
        }

    def archive_and_reset_v1_session(self, blend_path: str = "") -> dict[str, Any]:
        """Archive the current V1 session file and replace it with a new empty one.

        This operation is explicit and never imports legacy artifacts. The old
        file is moved into ``runtime/sessions_v1/archive`` with a timestamped
        name; the active path then receives a brand-new empty session bound to
        the same ``blend_path``.
        """
        effective_blend = str(blend_path or "").strip()
        current_path = self.v1_path(effective_blend)
        archive_path = None
        archived = False
        archived_summary: dict[str, Any] | None = None
        previous_session_id = ""

        if current_path.exists():
            archived_summary = self._describe_session_file(current_path, current=True)
            previous_session_id = str(archived_summary.get("session_id") or "")
            archive_path = self._archive_destination_for(current_path)
            current_path.replace(archive_path)
            archived = True
            _diag("store.reset", f"ARCHIVED current={current_path} archive={archive_path}")
        else:
            _diag("store.reset", f"ARCHIVE skipped current_missing={current_path}")

        session = Session.new(blend_path=effective_blend)
        session.lifecycle.add_note(
            "session_archived_and_reset"
            if archived
            else "session_reset_without_existing_v1"
        )
        if archived and previous_session_id:
            session.lifecycle.remember_prior_session(previous_session_id)
            session.lifecycle.add_note(f"archived_previous_session_id:{previous_session_id}")
        saved_path = self.save(session, effective_blend)
        _diag("store.reset", f"RESET new_session_file={saved_path}")
        return {
            "blend_path": effective_blend,
            "status": "archived_and_reset" if archived else "created_fresh",
            "current_session_file": str(saved_path),
            "archive_file": str(archive_path) if archive_path else "",
            "archived": archived,
            "archived_session": archived_summary,
            "new_session_id": str(session.identity.session_id or ""),
        }

    def _find_session_by_blend_path(self, blend_path: str) -> "Session | None":
        """Scan sessions_v1 for any session whose focus.blend_path matches.

        Used as a migration path when the expected hash-based filename doesn't
        exist yet (files created by older naming schemes are found here).
        """
        target = Path(blend_path).resolve().as_posix().lower()
        expected_name = _blend_path_to_session_name(blend_path)
        try:
            for f in self._v1_dir().iterdir():
                if not f.name.endswith(".json"):
                    continue
                if f.name == expected_name or f.name == SESSION_FILENAME:
                    continue
                payload = _read_json(f)
                if not isinstance(payload, dict):
                    continue
                focus = payload.get("focus", {})
                if not isinstance(focus, dict):
                    continue
                saved = str(focus.get("blend_path", "") or "").strip()
                if saved and Path(saved).resolve().as_posix().lower() == target:
                    return Session.from_dict(payload)
        except Exception:
            pass
        return None

    def _find_legacy_flat_session_by_blend_path(self, blend_path: str) -> "dict[str, Any] | None":
        """Scan runtime/sessions/ for a hash-named legacy flat dict whose blend_path matches.

        This covers files created by naming conventions older than the current
        ``session_<hash8>.json`` scheme. These files are never reached by
        ``legacy_path()`` (which only opens the un-hashed ``session.json``) and
        would otherwise be silently orphaned, losing any stored history.

        Returns the raw legacy dict so the caller can pass it to
        ``migrate_legacy_state()``, which explicitly discards approval/plan state.
        """
        if not blend_path:
            return None
        try:
            target = Path(blend_path).resolve().as_posix().lower()
        except Exception:
            return None
        legacy_dir = self._legacy_dir()
        if not legacy_dir.exists():
            return None
        try:
            for f in legacy_dir.glob("*.json"):
                if f.name == SESSION_FILENAME:
                    continue  # already handled by legacy_path()
                payload = _read_json(f)
                if not isinstance(payload, dict):
                    continue
                bp = str(payload.get("blend_path", "") or "").strip()
                if not bp:
                    continue
                try:
                    if Path(bp).resolve().as_posix().lower() == target:
                        return payload
                except Exception:
                    continue
        except Exception:
            pass
        return None

    def save(self, session: Session, blend_path: str = "") -> Path:
        """Persist ``session`` to the per-file v1 path and return it.

        ``history.messages`` are stored in the separate chat_history JSONL
        and stripped from the session JSON to keep it small.
        """
        effective_blend = blend_path or getattr(getattr(session, "focus", None), "blend_path", "") or ""
        if effective_blend and not session.focus.blend_path:
            session.focus = replace(session.focus, blend_path=effective_blend)
        path = self.v1_path(effective_blend)
        session.identity.schema_version = SCHEMA_VERSION
        session.touch()
        payload = session.to_dict()
        # Messages live in chat_history/<session_id>.jsonl — exclude from JSON.
        if "history" in payload and isinstance(payload["history"], dict):
            payload["history"]["messages"] = []
        tmp_path = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
        try:
            with tmp_path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except OSError:
                    pass
            _replace_with_retry(tmp_path, path)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
        return path

    # ---- chat history helpers --------------------------------------------

    def _hydrate_chat_history(self, session: Session) -> Session:
        """Populate session.history.messages from the JSONL store.

        On first access of an existing session (JSONL missing but messages
        present in the JSON), migrates them to JSONL automatically.
        """
        session_id = getattr(getattr(session, "identity", None), "session_id", None) or ""
        if not session_id:
            return session

        existing_msgs = list(getattr(getattr(session, "history", None), "messages", []))

        # One-shot migration: write JSON messages to JSONL if not done yet.
        if existing_msgs:
            self._chat_store.migrate_from_messages(session_id, existing_msgs)

        # Load from JSONL (authoritative).
        jsonl_msgs = self._chat_store.load(session_id)
        session.history.messages = [
            HistoryMessage.from_dict(m) for m in jsonl_msgs if isinstance(m, dict)
        ]
        return session

    def append_chat_message(
        self,
        session_id: str,
        *,
        role: str,
        content: str,
        ts: str = "",
        turn_class: str = "",
    ) -> None:
        """Write one message to the chat JSONL immediately."""
        self._chat_store.append(session_id, role=role, content=content, ts=ts, turn_class=turn_class)

    def clear_chat_history(self, session_id: str) -> None:
        """Delete the chat JSONL for the session (used by Clear button)."""
        self._chat_store.clear(session_id)

    def reattach_session_result(self, old_blend_path: str = "", new_blend_path: str = "") -> dict[str, Any]:
        """Return an explicit outcome for reattaching one session binding to another."""
        old_path = str(old_blend_path or "")
        new_path = str(new_blend_path or "")
        if not new_path or old_path == new_path:
            return {
                "status": "noop",
                "old_blend_path": old_path,
                "new_blend_path": new_path,
            }

        source_path = self.v1_path(old_path)
        if not source_path.exists():
            return {
                "status": "source_missing",
                "old_blend_path": old_path,
                "new_blend_path": new_path,
                "source_session_file": str(source_path),
            }

        target_path = self.v1_path(new_path)
        if target_path.exists():
            return {
                "status": "target_exists",
                "old_blend_path": old_path,
                "new_blend_path": new_path,
                "source_session_file": str(source_path),
                "target_session_file": str(target_path),
            }

        payload = _read_json(source_path)
        if not isinstance(payload, dict):
            return {
                "status": "invalid_source",
                "old_blend_path": old_path,
                "new_blend_path": new_path,
                "source_session_file": str(source_path),
            }

        session = Session.from_dict(payload)
        session.update_focus(blend_path=new_path)
        saved_path = self.save(session, new_path)

        if source_path != saved_path:
            try:
                source_path.unlink()
            except Exception:
                pass
        return {
            "status": "reattached",
            "old_blend_path": old_path,
            "new_blend_path": new_path,
            "source_session_file": str(source_path),
            "saved_path": str(saved_path),
        }

    def reattach_session(self, old_blend_path: str = "", new_blend_path: str = "") -> Path | None:
        """Move the current session binding from *old_blend_path* to *new_blend_path*.

        This is used for:
        - first save of an unsaved .blend (temporary session -> saved file)
        - Save As to a new path (existing file session -> new file identity)

        The move is intentionally conservative: if the target session file
        already exists, this method does nothing rather than overwriting it.
        """
        result = self.reattach_session_result(old_blend_path, new_blend_path)
        if str(result.get("status") or "") != "reattached":
            return None
        saved_path = str(result.get("saved_path") or "").strip()
        return Path(saved_path) if saved_path else None

    def has_v1_file(self, blend_path: str = "") -> bool:
        return self.v1_path(blend_path).exists()

    def has_legacy_file(self) -> bool:
        return self.legacy_path().exists()

    # ---- diagnostics / archive helpers ----------------------------------

    def _candidate_v1_sessions(self, blend_path: str, *, include_archive: bool) -> list[dict[str, Any]]:
        if not blend_path:
            return []
        roots = [self._archive_dir()] if include_archive else [self._v1_dir()]
        current_name = self.v1_path(blend_path).name
        try:
            target = Path(blend_path).resolve().as_posix().lower()
        except Exception:
            return []

        matches: list[dict[str, Any]] = []
        for root in roots:
            try:
                for path in root.glob("*.json"):
                    if not include_archive and path.name in {current_name, SESSION_FILENAME}:
                        continue
                    payload = _read_json(path)
                    if not isinstance(payload, dict):
                        continue
                    focus = payload.get("focus", {}) if isinstance(payload.get("focus"), dict) else {}
                    saved = str(focus.get("blend_path", "") or "").strip()
                    if not saved:
                        continue
                    try:
                        normalized = Path(saved).resolve().as_posix().lower()
                    except Exception:
                        normalized = saved.replace("\\", "/").lower()
                    if normalized != target:
                        continue
                    matches.append(self._describe_session_file(path, current=False))
            except Exception:
                continue
        matches.sort(key=lambda item: str(item.get("mtime", "") or ""), reverse=True)
        return matches

    def _archive_destination_for(self, current_path: Path) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive_dir = self._archive_dir()
        stem = current_path.stem
        suffix = current_path.suffix or ".json"
        candidate = archive_dir / f"{stem}__archived_{stamp}{suffix}"
        counter = 2
        while candidate.exists():
            candidate = archive_dir / f"{stem}__archived_{stamp}_{counter}{suffix}"
            counter += 1
        return candidate

    def _describe_session_file(self, path: Path, *, current: bool) -> dict[str, Any]:
        payload = _read_json(path)
        summary: dict[str, Any] = {
            "path": str(path),
            "exists": path.exists(),
            "current": bool(current),
            "session_id": "",
            "blend_path": "",
            "msg_count": 0,
            "first": "",
            "last": "",
            "mtime": "",
            "invalid": False,
        }
        if path.exists():
            try:
                summary["mtime"] = datetime.fromtimestamp(
                    path.stat().st_mtime,
                    tz=timezone.utc,
                ).replace(microsecond=0).isoformat()
            except Exception:
                summary["mtime"] = ""
        if not isinstance(payload, dict):
            summary["invalid"] = bool(path.exists())
            return summary

        identity = payload.get("identity", {}) if isinstance(payload.get("identity"), dict) else {}
        focus = payload.get("focus", {}) if isinstance(payload.get("focus"), dict) else {}
        history = payload.get("history", {}) if isinstance(payload.get("history"), dict) else {}
        messages = history.get("messages", []) if isinstance(history.get("messages"), list) else []
        first = messages[0] if messages else {}
        last = messages[-1] if messages else {}

        summary.update({
            "session_id": str(identity.get("session_id", "") or ""),
            "blend_path": str(focus.get("blend_path", "") or ""),
            "msg_count": len(messages),
            "first": str(first.get("content", "") or "")[:160] if isinstance(first, dict) else "",
            "last": str(last.get("content", "") or "")[:160] if isinstance(last, dict) else "",
        })
        return summary


# ---------------------------------------------------------------------------
# Legacy migration
# ---------------------------------------------------------------------------


def migrate_legacy_state(legacy: dict[str, Any], *, blend_path: str = "") -> Session:
    """Convert a legacy flat session dict (schema 0.1) into a v1 Session.

    The migration is intentionally lossy. Only fields whose meaning survives
    in the new architecture are carried over. Everything on the
    "Do Not Preserve" list (approval tokens, plan tokens, presented_plan_*,
    plan stages, fallback infrastructure, execution_policy) is discarded.
    """
    legacy = legacy or {}

    blend_path_value = str(legacy.get("blend_path") or blend_path or "")
    legacy_memory = legacy.get("session_memory") if isinstance(legacy.get("session_memory"), dict) else {}
    target_tree = str(legacy_memory.get("target_tree") or legacy.get("last_target_tree") or "") or None

    identity = Identity(
        session_id=str(legacy.get("session_id") or new_session_id()),
        schema_version=SCHEMA_VERSION,
        created_at=str(legacy.get("session_started_at") or legacy.get("updated_at") or utc_now_iso()),
        last_active_at=str(legacy.get("updated_at") or utc_now_iso()),
    )

    focus = Focus(
        blend_path=blend_path_value,
        object_name=None,
        modifier_name=None,
        tree_name=target_tree,
        focus_signature=compute_focus_signature(blend_path_value, None, None, target_tree),
    )

    baseline = _build_baseline_from_legacy(legacy)

    history = _build_history_from_legacy(legacy)

    execution_state = _build_execution_state_from_legacy(legacy, focus)

    ui_state = UIState(
        debug_mode=bool(legacy.get("debug_mode", False)),
        explicit_override_mode=bool(legacy.get("explicit_override_mode", False)),
        mcp_write_enabled=bool(legacy.get("mcp_write_enabled", False)),
        session_active=bool(legacy.get("agent_session_active", False)),  # Phase 9
    )
    operational_state = _build_operational_state_from_legacy(legacy)

    lifecycle = Lifecycle(continuity_token=new_continuity_token())
    prior_session_id = str(legacy.get("session_id") or "").strip()
    if prior_session_id:
        lifecycle.remember_prior_session(prior_session_id)
    last_goal = str(legacy_memory.get("last_goal") or "").strip()
    if last_goal:
        lifecycle.add_note(f"migrated_from_legacy:last_goal={last_goal[:200]}")

    # Explicitly record which approval/plan fields were discarded so callers
    # (e.g. Runtime._sync_v1_session) can emit a journal event on first load.
    # These fields are authoritative only in the legacy plan/approval flow and
    # have no meaning in draft-first sessions.
    _LEGACY_APPROVAL_KEYS = (
        "approval_token",
        "current_plan_id",
        "approval_status",
        "approval_required",
        "presented_plan_stages",
        "execution_approval_token",
        "runtime_phase",  # "awaiting_user_approval" maps to nothing in V1
    )
    _discarded = [
        k for k in _LEGACY_APPROVAL_KEYS
        if legacy.get(k) not in (None, "", False, [], {})
        and str(legacy.get(k) or "").lower() not in ("false", "none", "idle", "planning")
    ]
    if _discarded:
        lifecycle.add_note(f"legacy_approval_state_discarded:{','.join(_discarded)}")

    return Session(
        identity=identity,
        focus=focus,
        baseline_workspace=baseline,
        history=history,
        execution_state=execution_state,
        ui_state=ui_state,
        operational_state=operational_state,
        lifecycle=lifecycle,
    )


def _build_baseline_from_legacy(legacy: dict[str, Any]) -> BaselineWorkspace:
    """Pull whatever structural hints the legacy state still carries."""
    structural_summary: dict[str, Any] = {}
    last_gn = legacy.get("last_gn_summary")
    if isinstance(last_gn, dict) and last_gn:
        structural_summary["last_gn_summary"] = dict(last_gn)
    last_scene = legacy.get("last_scene_summary")
    if isinstance(last_scene, dict) and last_scene:
        structural_summary["last_scene_summary"] = dict(last_scene)

    structural_index = legacy.get("structural_index")
    subgraph_index: dict[str, Any] = {}
    if isinstance(structural_index, dict):
        for tree_name, entry in structural_index.items():
            if isinstance(entry, dict):
                subgraph_index[str(tree_name)] = dict(entry)

    legacy_memory = legacy.get("session_memory") if isinstance(legacy.get("session_memory"), dict) else {}
    known_parameters: dict[str, Any] = {}
    last_param_changes = legacy_memory.get("last_parameter_changes")
    if isinstance(last_param_changes, list):
        for change in last_param_changes:
            if not isinstance(change, dict):
                continue
            key = str(change.get("node") or change.get("name") or "").strip()
            if not key:
                continue
            known_parameters[key] = {
                "field": str(change.get("field") or ""),
                "value": change.get("value"),
                "source": "migrated_from_legacy",
            }

    open_questions: list[str] = []
    last_hypothesis = str(legacy_memory.get("last_hypothesis") or "").strip()
    if last_hypothesis:
        open_questions.append(f"hypothesis_to_revisit: {last_hypothesis[:200]}")

    has_any_signal = bool(structural_summary or subgraph_index or known_parameters)
    return BaselineWorkspace(
        tree_signature="",
        built_at="",
        built_from="",
        structural_summary=structural_summary,
        subgraph_index=subgraph_index,
        known_parameters=known_parameters,
        open_questions=open_questions,
        # Migrated baselines are stale by definition: we never re-read the
        # tree at migration time, so the runtime should rebuild before use.
        stale=True if has_any_signal else True,
    )


def _build_history_from_legacy(legacy: dict[str, Any]) -> History:
    raw_history = legacy.get("chat_history")
    if not isinstance(raw_history, list):
        return History()
    messages: list[HistoryMessage] = []
    for item in raw_history:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        if role not in {"user", "assistant", "system"}:
            continue
        text = str(item.get("text") or item.get("content") or "")
        if not text.strip():
            continue
        messages.append(
            HistoryMessage(
                role=role,
                content=text,
                ts=str(item.get("timestamp") or item.get("ts") or utc_now_iso()),
                turn_class="",
            )
        )
    history = History(messages=messages)
    # Apply the bound on the way in.
    if len(history.messages) > history.max_messages:
        history.messages = history.messages[-history.max_messages :]
    return history


def _build_execution_state_from_legacy(legacy: dict[str, Any], focus: Focus) -> ExecutionState:
    """Rebuild ``execution_state`` while discarding the legacy approval mess.

    Per REFATOR_PLAN.md §12, approval tokens, plan tokens, and per-stage
    approval state are not migrated. We only preserve a *failure* hint if
    the legacy state recorded one, so the new runtime can immediately surface
    the explain-and-stop view on resume.
    """
    last_failure_text = str(legacy.get("last_failure") or "").strip()
    last_failure: LastFailure | None = None
    if last_failure_text:
        last_failure = LastFailure(
            tool="",
            error=last_failure_text,
            cause="migrated_from_legacy",
            suggested_alternative="",
        )

    return ExecutionState(
        phase="idle",
        last_failure=last_failure,
    )


def _build_operational_state_from_legacy(legacy: dict[str, Any]) -> OperationalState:
    try:
        turn_counter = int(legacy.get("turn_counter") or 0)
    except Exception:
        turn_counter = 0
    return OperationalState(
        turn_counter=turn_counter,
        session_memory=dict(legacy.get("session_memory")) if isinstance(legacy.get("session_memory"), dict) else {},
        local_scope=dict(legacy.get("local_scope")) if isinstance(legacy.get("local_scope"), dict) else {},
        structural_index=(
            dict(legacy.get("structural_index")) if isinstance(legacy.get("structural_index"), dict) else {}
        ),
        tree_change_markers=(
            dict(legacy.get("tree_change_markers")) if isinstance(legacy.get("tree_change_markers"), dict) else {}
        ),
        recent_actions=[
            dict(item)
            for item in (legacy.get("recent_actions") or [])
            if isinstance(item, dict)
        ],
        risky_events=[
            dict(item)
            for item in (legacy.get("risky_events") or [])
            if isinstance(item, dict)
        ],
        last_scene_summary=(
            dict(legacy.get("last_scene_summary")) if isinstance(legacy.get("last_scene_summary"), dict) else {}
        ),
        last_gn_summary=(
            dict(legacy.get("last_gn_summary")) if isinstance(legacy.get("last_gn_summary"), dict) else {}
        ),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def _replace_with_retry(src: Path, dst: Path, *, attempts: int = 6, delay_s: float = 0.05) -> None:
    """Replace a session file, tolerating brief Windows/OneDrive file locks."""
    last_exc: OSError | None = None
    for attempt in range(max(1, attempts)):
        try:
            src.replace(dst)
            return
        except PermissionError as exc:
            last_exc = exc
            if attempt >= attempts - 1:
                raise
            time.sleep(delay_s * (attempt + 1))
    if last_exc is not None:
        raise last_exc
