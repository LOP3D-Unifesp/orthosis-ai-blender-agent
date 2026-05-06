"""One-way import of runtime artifacts from older sibling project roots.

This module supports data recovery during the blend_IA_ort -> blend_IA_ort_v2
transition. Imported data is copied or merged into the current project root so
the running product only uses the v2 workspace after migration.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


def legacy_project_roots(project_root: Path) -> list[Path]:
    root = Path(project_root).resolve()
    candidates: list[Path] = []
    if root.name.endswith("_v2"):
        candidates.append(root.with_name(root.name[: -len("_v2")]))

    resolved: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            legacy = candidate.resolve()
        except Exception:
            continue
        key = str(legacy)
        if key in seen or legacy == root:
            continue
        seen.add(key)
        if (legacy / "runtime").exists():
            resolved.append(legacy)
    return resolved


def _normalized_path(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return Path(text).resolve().as_posix().lower()
    except Exception:
        return text.replace("\\", "/").lower()


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _session_metadata(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    if not payload:
        return {}

    if isinstance(payload.get("history"), dict):
        identity = payload.get("identity", {}) if isinstance(payload.get("identity"), dict) else {}
        focus = payload.get("focus", {}) if isinstance(payload.get("focus"), dict) else {}
        history = payload.get("history", {}) if isinstance(payload.get("history"), dict) else {}
        messages = history.get("messages", []) if isinstance(history.get("messages"), list) else []
        return {
            "kind": "v1",
            "blend_path": _normalized_path(str(focus.get("blend_path", "") or "")),
            "history_len": len(messages),
            "last_active_at": str(identity.get("last_active_at", "") or ""),
            "payload": payload,
        }

    messages = payload.get("chat_history", []) if isinstance(payload.get("chat_history"), list) else []
    return {
        "kind": "legacy",
        "blend_path": _normalized_path(str(payload.get("blend_path", "") or "")),
        "history_len": len(messages),
        "last_active_at": str(payload.get("updated_at") or payload.get("session_started_at") or ""),
        "payload": payload,
    }


def _should_replace_session(source_meta: dict[str, Any], dest_meta: dict[str, Any]) -> bool:
    source_ts = str(source_meta.get("last_active_at", "") or "")
    dest_ts = str(dest_meta.get("last_active_at", "") or "")
    if source_ts and dest_ts and source_ts != dest_ts:
        return source_ts > dest_ts
    source_len = int(source_meta.get("history_len", 0) or 0)
    dest_len = int(dest_meta.get("history_len", 0) or 0)
    if source_len != dest_len:
        return source_len > dest_len
    return False


def import_session_files(project_root: Path, blend_path: str = "") -> list[Path]:
    root = Path(project_root).resolve()
    target_blend = _normalized_path(blend_path)
    imported: list[Path] = []

    for legacy_root in legacy_project_roots(root):
        for subdir in ("sessions_v1", "sessions"):
            source_dir = legacy_root / "runtime" / subdir
            dest_dir = root / "runtime" / subdir
            if not source_dir.exists():
                continue
            dest_dir.mkdir(parents=True, exist_ok=True)
            for source in source_dir.glob("*.json"):
                meta = _session_metadata(source)
                if not meta:
                    continue
                if target_blend and meta.get("blend_path") != target_blend:
                    continue

                dest = dest_dir / source.name
                if not dest.exists():
                    shutil.copy2(source, dest)
                    imported.append(dest)
                    continue

                dest_meta = _session_metadata(dest)
                if _should_replace_session(meta, dest_meta):
                    shutil.copy2(source, dest)
                    imported.append(dest)

    return imported


def _jsonl_entries(path: Path) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.rstrip("\n")
                if not line.strip():
                    continue
                timestamp = ""
                try:
                    payload = json.loads(line)
                    if isinstance(payload, dict):
                        timestamp = str(payload.get("timestamp", "") or "")
                except Exception:
                    pass
                entries.append((timestamp, line))
    except Exception:
        return []
    return entries


def _normalized_jsonl_identity(line: str) -> str:
    try:
        payload = json.loads(line)
    except Exception:
        return line

    if not isinstance(payload, dict):
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    if "type" not in payload and "goal_id" in payload and "session_id" in payload and "outcome" in payload:
        stable_outcome = {
            "goal_id": payload.get("goal_id"),
            "session_id": payload.get("session_id"),
            "outcome": payload.get("outcome"),
            "notes": payload.get("notes", ""),
        }
        return "outcome:" + json.dumps(stable_outcome, ensure_ascii=False, sort_keys=True)

    return "json:" + json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _merge_jsonl(source: Path, dest: Path) -> bool:
    source_entries = _jsonl_entries(source)
    if not source_entries:
        return False

    merged: list[tuple[str, str]] = []
    seen: set[str] = set()
    for entries in (_jsonl_entries(dest), source_entries):
        for timestamp, line in entries:
            identity = _normalized_jsonl_identity(line)
            if identity in seen:
                continue
            seen.add(identity)
            merged.append((timestamp, line))

    merged.sort(key=lambda item: (item[0], item[1]))
    with dest.open("w", encoding="utf-8") as handle:
        for _, line in merged:
            handle.write(line + "\n")
    return True


def import_journal_files(project_root: Path) -> list[Path]:
    root = Path(project_root).resolve()
    dest_base = root / "runtime" / "journal"
    dest_sessions = dest_base / "sessions"
    dest_sessions.mkdir(parents=True, exist_ok=True)

    imported: list[Path] = []
    for legacy_root in legacy_project_roots(root):
        source_base = legacy_root / "runtime" / "journal"
        source_sessions = source_base / "sessions"
        if source_sessions.exists():
            for source in source_sessions.glob("*.jsonl"):
                dest = dest_sessions / source.name
                if dest.exists():
                    if _merge_jsonl(source, dest):
                        imported.append(dest)
                else:
                    shutil.copy2(source, dest)
                    imported.append(dest)

        source_outcomes = source_base / "outcomes.jsonl"
        dest_outcomes = dest_base / "outcomes.jsonl"
        if source_outcomes.exists():
            if dest_outcomes.exists():
                if _merge_jsonl(source_outcomes, dest_outcomes):
                    imported.append(dest_outcomes)
            else:
                shutil.copy2(source_outcomes, dest_outcomes)
                imported.append(dest_outcomes)

    return imported
