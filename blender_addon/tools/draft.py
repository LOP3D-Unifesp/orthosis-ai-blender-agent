"""Script-draft tool helpers and dispatcher-facing entry points."""

from __future__ import annotations

import ast
import json
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Any

_DRAFT_MIN_LINES = 8
_DRAFT_MIN_CHARS = 300
_DRAFT_REVISION_RE = re.compile(r"^(?P<base>.+)__rev_(?P<version>\d{6})$")


def _is_placeholder_draft(code: str, description: str = "") -> bool:
    text = f"{description}\n{code}".lower()
    return (
        "aguardando" in text
        or "sessao de draft iniciada" in text
        or "sess\u00e3o de draft iniciada" in text
    )


def _infer_draft_revision_validity(code: str, description: str = "") -> str:
    text = str(code or "")
    if _is_placeholder_draft(text, description):
        return "quarantined"
    stripped = text.strip()
    if not stripped:
        return "broken"
    try:
        compile(stripped, "<script_draft_revision>", "exec")
    except SyntaxError:
        return "broken"
    line_count = len(stripped.splitlines())
    char_count = len(stripped)
    if line_count < _DRAFT_MIN_LINES or char_count < _DRAFT_MIN_CHARS:
        return "partial"
    return "valid"


def _draft_revision_reject_reason(code: str, description: str = "") -> str:
    text = str(code or "")
    if _is_placeholder_draft(text, description):
        return "placeholder_draft"
    stripped = text.strip()
    if not stripped:
        return "empty_script"
    try:
        compile(stripped, "<script_draft_revision>", "exec")
    except SyntaxError as exc:
        return f"syntax_error:{exc.msg}"
    line_count = len(stripped.splitlines())
    char_count = len(stripped)
    if line_count < _DRAFT_MIN_LINES:
        return f"too_few_lines:{line_count}<{_DRAFT_MIN_LINES}"
    if char_count < _DRAFT_MIN_CHARS:
        return f"too_few_chars:{char_count}<{_DRAFT_MIN_CHARS}"
    return ""


def _attribute_chain(node: ast.AST) -> list[str]:
    parts: list[str] = []
    current: ast.AST | None = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return list(reversed(parts))


def _is_nodes_expr(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "nodes"
    if isinstance(node, ast.Attribute):
        return node.attr == "nodes" or _is_nodes_expr(node.value)
    return False


def _has_geometry_nodes_operations(code: str) -> bool:
    try:
        parsed = ast.parse(str(code or ""))
    except SyntaxError:
        return False

    class GeometryNodesOperationVisitor(ast.NodeVisitor):
        found = False

        def visit_Attribute(self, node: ast.Attribute) -> Any:
            chain = _attribute_chain(node)
            if chain[-3:] == ["bpy", "data", "node_groups"]:
                self.found = True
                return
            if node.attr in {"nodes", "links", "interface"}:
                self.found = True
                return
            self.generic_visit(node)

        def visit_Subscript(self, node: ast.Subscript) -> Any:
            if _is_nodes_expr(node.value):
                self.found = True
                return
            if isinstance(node.value, ast.Name) and node.value.id == "modifiers":
                self.found = True
                return
            if isinstance(node.value, ast.Attribute) and node.value.attr == "modifiers":
                self.found = True
                return
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call) -> Any:
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in {"get", "new"} and _is_nodes_expr(func.value):
                self.found = True
                return
            self.generic_visit(node)

    visitor = GeometryNodesOperationVisitor()
    visitor.visit(parsed)
    return visitor.found


def _extract_referenced_node_names(code: str) -> list[str]:
    try:
        parsed = ast.parse(str(code or ""))
    except SyntaxError:
        return []

    names: list[str] = []

    def add_name(value: str) -> None:
        name = str(value or "").strip()
        if name and name not in names:
            names.append(name)

    class NodeReferenceVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.bindings: dict[str, list[str]] = {}

        def _resolve_strings(self, node: ast.AST) -> list[str]:
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                return [node.value]
            if isinstance(node, ast.Name):
                return list(self.bindings.get(node.id, []))
            if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
                values: list[str] = []
                for item in node.elts:
                    values.extend(self._resolve_strings(item))
                return values
            return []

        @staticmethod
        def _is_nodes_expr(node: ast.AST) -> bool:
            return _is_nodes_expr(node)

        def _bind_assignment(self, target: ast.AST, value: ast.AST) -> None:
            if isinstance(target, ast.Name):
                resolved = self._resolve_strings(value)
                if resolved:
                    self.bindings[target.id] = resolved

        def visit_Assign(self, node: ast.Assign) -> Any:
            for target in node.targets:
                self._bind_assignment(target, node.value)
            self.generic_visit(node)

        def visit_AnnAssign(self, node: ast.AnnAssign) -> Any:
            if node.value is not None:
                self._bind_assignment(node.target, node.value)
            self.generic_visit(node)

        def visit_For(self, node: ast.For) -> Any:
            previous: list[str] | None = None
            target_name = node.target.id if isinstance(node.target, ast.Name) else ""
            if target_name:
                previous = self.bindings.get(target_name)
                values = self._resolve_strings(node.iter)
                if values:
                    self.bindings[target_name] = values
            for item in node.body:
                self.visit(item)
            if target_name:
                if previous is None:
                    self.bindings.pop(target_name, None)
                else:
                    self.bindings[target_name] = previous
            for item in node.orelse:
                self.visit(item)

        def visit_Call(self, node: ast.Call) -> Any:
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "get"
                and self._is_nodes_expr(func.value)
                and node.args
            ):
                for value in self._resolve_strings(node.args[0]):
                    add_name(value)
            self.generic_visit(node)

        def visit_Subscript(self, node: ast.Subscript) -> Any:
            if self._is_nodes_expr(node.value):
                for value in self._resolve_strings(node.slice):
                    add_name(value)
            self.generic_visit(node)

    NodeReferenceVisitor().visit(parsed)
    return names


def _semantic_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower()


def _semantic_compact(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", _semantic_text(value))


def _coerce_str_list(value: Any, *, limit: int = 12) -> list[str]:
    raw_items = value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("["):
            try:
                raw_items = json.loads(stripped)
            except Exception:
                raw_items = [value]
        elif stripped:
            raw_items = [value]
        else:
            raw_items = []
    if not isinstance(raw_items, list):
        return []
    items: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = str(item or "").strip()
        key = _semantic_compact(text)
        if not text or not key or key in seen:
            continue
        seen.add(key)
        items.append(text)
        if len(items) >= limit:
            break
    return items


def _text_block_str_list(text_block: Any, key: str, *, limit: int = 12) -> list[str]:
    if text_block is None:
        return []
    try:
        value = text_block.get(key, [])
    except Exception:
        value = []
    return _coerce_str_list(value, limit=limit)


def _text_block_json_dict(text_block: Any, key: str) -> dict[str, Any]:
    if text_block is None:
        return {}
    try:
        value = text_block.get(key, {})
    except Exception:
        value = {}
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str):
        return {}
    text = value.strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except Exception:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _semantic_term_present(code: str, term: str) -> bool:
    text = _semantic_text(code)
    compact_text = _semantic_compact(code)
    term_text = _semantic_text(term).strip()
    term_compact = _semantic_compact(term)
    if not term_text or not term_compact:
        return False
    variants = {
        term_text,
        term_text.replace(" ", "_"),
        term_text.replace(" ", "-"),
        term_compact,
    }
    return any(
        variant and (variant in text or _semantic_compact(variant) in compact_text)
        for variant in variants
    )


def _matched_semantic_terms(code: str, expected_terms: list[str], *, limit: int = 8) -> list[str]:
    matches: list[str] = []
    seen: set[str] = set()
    for term in expected_terms:
        text = str(term or "").strip()
        key = _semantic_compact(text)
        if not text or not key or key in seen:
            continue
        if _semantic_term_present(code, text):
            seen.add(key)
            matches.append(text)
            if len(matches) >= limit:
                break
    return matches


def _draft_semantic_regression_reason(
    candidate_code: str,
    *,
    previous_code: str = "",
    previous_tree_name: str = "",
    candidate_tree_name: str = "",
    allow_tree_change: bool = False,
    allow_capability_regression: bool = False,
    expected_parameter_refs: list[str] | None = None,
    expected_focus_regions: list[str] | None = None,
) -> tuple[str, dict[str, list[str]]]:
    details = {
        "previous_live_node_refs": [],
        "candidate_live_node_refs": [],
        "previous_parameter_refs": [],
        "candidate_parameter_refs": [],
        "previous_focus_regions": [],
        "candidate_focus_regions": [],
    }
    previous = str(previous_code or "").strip()
    candidate = str(candidate_code or "").strip()
    if not previous or not candidate:
        return "", details

    prev_tree = str(previous_tree_name or "").strip()
    next_tree = str(candidate_tree_name or "").strip()
    if prev_tree and next_tree and prev_tree != next_tree and not allow_tree_change:
        return f"target_tree_changed:{prev_tree}->{next_tree}", details

    prev_live_refs = _extract_referenced_node_names(previous)
    details["previous_live_node_refs"] = prev_live_refs[:8]
    if prev_live_refs and not allow_capability_regression:
        next_live_refs = _extract_referenced_node_names(candidate)
        details["candidate_live_node_refs"] = next_live_refs[:8]
        if not next_live_refs:
            return "regression_lost_live_node_refs", details

        prev_ref_set = set(prev_live_refs)
        next_ref_set = set(next_live_refs)
        if not prev_ref_set.intersection(next_ref_set):
            return "regression_replaced_live_node_refs:" + ", ".join(prev_live_refs[:6]), details

    parameter_refs = _coerce_str_list(expected_parameter_refs or [], limit=12)
    if parameter_refs and not allow_capability_regression:
        prev_parameter_refs = _matched_semantic_terms(previous, parameter_refs)
        details["previous_parameter_refs"] = prev_parameter_refs[:8]
        if prev_parameter_refs:
            next_parameter_refs = _matched_semantic_terms(candidate, parameter_refs)
            details["candidate_parameter_refs"] = next_parameter_refs[:8]
            if not next_parameter_refs:
                return "regression_lost_expected_parameters:" + ", ".join(prev_parameter_refs[:6]), details
            if not set(prev_parameter_refs).intersection(set(next_parameter_refs)):
                return "regression_replaced_expected_parameters:" + ", ".join(prev_parameter_refs[:6]), details

    focus_regions = [
        region for region in _coerce_str_list(expected_focus_regions or [], limit=12)
        if not _is_generic_focus_region(region)
    ]
    if focus_regions and not allow_capability_regression:
        prev_focus_regions = _matched_semantic_terms(previous, focus_regions)
        details["previous_focus_regions"] = prev_focus_regions[:8]
        if prev_focus_regions:
            next_focus_regions = _matched_semantic_terms(candidate, focus_regions)
            details["candidate_focus_regions"] = next_focus_regions[:8]
            if not next_focus_regions:
                return "regression_lost_focus_regions:" + ", ".join(prev_focus_regions[:6]), details
            if not set(prev_focus_regions).intersection(set(next_focus_regions)):
                return "regression_replaced_focus_regions:" + ", ".join(prev_focus_regions[:6]), details

    prev_len = len(previous)
    next_len = len(candidate)
    if (
        prev_len >= 900
        and next_len < max(_DRAFT_MIN_CHARS, int(prev_len * 0.55))
        and not allow_capability_regression
    ):
        return f"regression_candidate_too_small_vs_existing:{next_len}<{int(prev_len * 0.55)}", details

    return "", details


def _is_generic_focus_region(region: str) -> bool:
    text = str(region or "").strip().lower()
    if not text:
        return True
    if text == "frame" or re.fullmatch(r"frame(?:\.\d+)?", text):
        return True
    if text in {
        "unknown_structural_region",
        "geometry_join_or_assembly_region",
    }:
        return True
    return False


def _iter_text_blocks():
    try:
        import bpy

        return list(bpy.data.texts)
    except Exception:
        return []


def _draft_revision_blocks(block_name: str) -> list[Any]:
    blocks: list[Any] = []
    prefix = f"{block_name}__rev_"
    for text in _iter_text_blocks():
        name = str(getattr(text, "name", "") or "")
        if not name.startswith(prefix):
            continue
        if str(text.get("_draft_base_block_name", "") or block_name) != block_name:
            continue
        blocks.append(text)
    return blocks


def _draft_block_version(text_block: Any) -> int:
    try:
        version = int(text_block.get("_draft_version", 0) or 0)
    except Exception:
        version = 0
    if version > 0:
        return version
    match = _DRAFT_REVISION_RE.match(str(getattr(text_block, "name", "") or ""))
    if match:
        try:
            return int(match.group("version"))
        except Exception:
            return 0
    return 0


def _draft_revision_validity(text_block: Any) -> str:
    try:
        explicit = str(text_block.get("_draft_revision_validity", "") or "").strip().lower()
    except Exception:
        explicit = ""
    if explicit in {"valid", "partial", "broken", "quarantined", "superseded"}:
        return explicit
    try:
        description = str(text_block.get("_draft_description", "") or "")
    except Exception:
        description = ""
    return _infer_draft_revision_validity(text_block.as_string(), description)


def _latest_draft_block(block_name: str) -> Any | None:
    import bpy

    main = bpy.data.texts.get(block_name)
    if main is not None:
        return main
    candidates = _draft_revision_blocks(block_name)
    if not candidates:
        return None
    return max(candidates, key=_draft_block_version)


def _best_draft_reasoning_block(block_name: str) -> tuple[Any | None, Any | None]:
    import bpy

    main = bpy.data.texts.get(block_name)
    if main is not None:
        return main, main
    candidates = _draft_revision_blocks(block_name)
    if not candidates:
        return None, None
    latest = max(candidates, key=_draft_block_version)
    usable = [
        block for block in candidates
        if _draft_revision_validity(block) in {"valid", "partial"}
    ]
    if not usable:
        return latest, latest
    valid = [block for block in usable if _draft_revision_validity(block) == "valid"]
    pool = valid or usable
    best = max(pool, key=_draft_block_version)
    return best, latest


def _draft_payload_from_block(text_block: Any, *, source: str = "text_block") -> dict:
    content = text_block.as_string()
    validity = _draft_revision_validity(text_block)
    return {
        "block_name": text_block.name,
        "content": content,
        "line_count": len(text_block.lines),
        "char_count": len(content),
        "version": _draft_block_version(text_block),
        "description": str(text_block.get("_draft_description", "") or ""),
        "tree_name": str(text_block.get("_draft_tree_name", "") or ""),
        "revision_created_at": str(text_block.get("_draft_revision_created_at", "") or ""),
        "revision_parent": int(text_block.get("_draft_revision_parent", 0) or 0),
        "revision_kind": str(text_block.get("_draft_revision_kind", "") or ""),
        "revision_changed_from_previous": str(text_block.get("_draft_revision_changed_from_previous", "") or ""),
        "current_revision_validity": validity,
        "revision_validity": validity,
        "last_valid_draft_revision": int(text_block.get("_draft_last_valid_revision", 0) or 0),
        "last_executed_revision": int(text_block.get("_draft_last_executed_revision", 0) or 0),
        "last_failed_revision": int(text_block.get("_draft_last_failed_revision", 0) or 0),
        "live_node_refs": _extract_referenced_node_names(content)[:8],
        "expected_parameter_refs": _text_block_str_list(text_block, "_draft_expected_parameter_refs", limit=12),
        "expected_focus_regions": _text_block_str_list(text_block, "_draft_expected_focus_regions", limit=12),
        "edit_mode": str(text_block.get("_draft_edit_mode", "") or ""),
        "goal_mode": str(text_block.get("_draft_goal_mode", "") or ""),
        "goal_guidance": _text_block_json_dict(text_block, "_draft_goal_guidance"),
        "draft_archive_path": str(text_block.get("_draft_archive_path", "") or ""),
        "source": source,
    }


def _draft_domain_reject_reason(code: str, *, tree_name: str = "") -> str:
    stripped = str(code or "").strip()
    if not stripped:
        return ""

    if tree_name:
        import bpy

        tree = bpy.data.node_groups.get(tree_name)
        if tree is None:
            return f"target_tree_missing:{tree_name}"

        if not _has_geometry_nodes_operations(stripped):
            return "no_geometry_nodes_operations_detected"

        referenced_nodes = _extract_referenced_node_names(stripped)
        if referenced_nodes:
            try:
                live_nodes = {node.name for node in tree.nodes}
            except Exception:
                live_nodes = set()
            missing = [name for name in referenced_nodes if name not in live_nodes]
            if missing:
                return f"missing_live_nodes:{', '.join(missing[:6])}"

    return ""


def _safe_draft_filename_part(value: str, *, fallback: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", ascii_text).strip("._")
    return safe[:80] or fallback


def _archive_script_draft(
    *,
    code: str,
    block_name: str,
    version: int,
    created_at: str,
    description: str,
    tree_name: str,
    session_id: str,
    project_root: str,
) -> tuple[str, str]:
    """Persist a full draft revision as a .py file for postmortems and reuse."""
    safe_session = _safe_draft_filename_part(session_id, fallback="unsessioned")
    safe_block = _safe_draft_filename_part(block_name, fallback="GN_Agent_Draft")
    try:
        root = Path(project_root).expanduser().resolve() if project_root else None
    except Exception:
        root = None
    if root is None:
        try:
            from ..project_paths import resolve_project_root

            root = resolve_project_root()
        except Exception as exc:
            return "", f"project_root_unavailable:{exc}"

    archive_dir = root / "runtime" / "draft_history" / safe_session
    filename = f"r{int(version):06d}_{safe_block}.py"
    target = archive_dir / filename
    tmp = archive_dir / f".{filename}.tmp"
    header = (
        "# GN Agent draft archive\n"
        f"# session_id: {session_id or 'unsessioned'}\n"
        f"# block_name: {block_name}\n"
        f"# revision: {int(version)}\n"
        f"# created_at: {created_at}\n"
        f"# tree_name: {tree_name}\n"
        f"# description: {description[:300]}\n\n"
    )
    try:
        archive_dir.mkdir(parents=True, exist_ok=True)
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(header)
            handle.write(code)
            if not code.endswith("\n"):
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
        return str(target), ""
    except Exception as exc:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        return "", str(exc)


def handle_write_script_draft(cmd: dict) -> dict:
    """Write a Python/bpy script to a Blender Text Editor block.

    The script is NOT executed. It is placed in bpy.data.texts so the user
    can review, modify, and run it manually from the Scripting workspace.

    Parameters:
        block_name : str — name of the text block (default "GN_Agent_Draft")
        code       : str — the complete Python script to write
        description: str — what this script does (for metadata)
        tree_name  : str — optional target GN tree name
    """
    import bpy

    from .handlers import execute_in_main_thread

    block_name = str(cmd.get("block_name") or "GN_Agent_Draft").strip()
    code = str(cmd.get("code") or "")
    description = str(cmd.get("description") or "").strip()
    tree_name = str(cmd.get("tree_name") or "").strip()
    allow_tree_change = bool(cmd.get("allow_tree_change", False))
    allow_capability_regression = bool(cmd.get("allow_capability_regression", False))
    edit_mode = str(cmd.get("edit_mode") or "").strip()
    goal_mode = str(cmd.get("goal_mode") or "").strip()
    goal_guidance = cmd.get("goal_guidance", {}) if isinstance(cmd.get("goal_guidance"), dict) else {}
    expected_parameter_refs = _coerce_str_list(cmd.get("expected_parameter_refs", []), limit=12)
    expected_focus_regions = _coerce_str_list(cmd.get("expected_focus_regions", []), limit=12)
    session_id = str(cmd.get("session_id") or "").strip()
    project_root = str(cmd.get("project_root") or "").strip()

    def _do():
        if not code.strip():
            return {"status": "error", "error": "Empty script — nothing to write."}

        existing_latest = _latest_draft_block(block_name)
        if (
            existing_latest is not None
            and _is_placeholder_draft(code, description)
            and not _is_placeholder_draft(
                existing_latest.as_string(),
                str(existing_latest.get("_draft_description", "") or ""),
            )
        ):
            payload = _draft_payload_from_block(existing_latest, source="revision_backup")
            payload["block_name"] = block_name
            payload["skipped_placeholder_write"] = True
            payload["edit_mode"] = edit_mode
            payload["goal_mode"] = goal_mode
            payload["goal_guidance"] = goal_guidance
            return {"status": "success", "result": payload}

        existing_version = _draft_block_version(existing_latest) if existing_latest is not None else 0
        next_version = existing_version + 1
        created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        inferred_validity = _infer_draft_revision_validity(code, description)
        requested_validity = str(cmd.get("revision_validity") or "").strip().lower()
        validity_rank = {"valid": 0, "partial": 1, "broken": 2, "quarantined": 3}
        if requested_validity in validity_rank and validity_rank[requested_validity] > validity_rank[inferred_validity]:
            revision_validity = requested_validity
        else:
            revision_validity = inferred_validity
        if revision_validity != "valid":
            reject_reason = _draft_revision_reject_reason(code, description) or revision_validity
            return {
                "status": "blocked",
                "error": (
                    "Draft write blocked: the candidate script is not a complete valid revision "
                    f"({reject_reason}). write_script_draft must receive the full corrected script."
                ),
                "result": {
                    "block_name": block_name,
                    "current_revision": existing_version,
                    "candidate_char_count": len(code),
                    "candidate_line_count": len(code.strip().splitlines()) if code.strip() else 0,
                    "candidate_revision_validity": revision_validity,
                    "reject_reason": reject_reason,
                    "edit_mode": edit_mode,
                    "goal_mode": goal_mode,
                    "goal_guidance": goal_guidance,
                },
            }
        domain_reject_reason = _draft_domain_reject_reason(code, tree_name=tree_name)
        if domain_reject_reason:
            return {
                "status": "blocked",
                "error": (
                    "Draft write blocked: the candidate script did not pass live Geometry Nodes validation "
                    f"({domain_reject_reason})."
                ),
                "result": {
                    "block_name": block_name,
                    "current_revision": existing_version,
                    "candidate_char_count": len(code),
                    "candidate_line_count": len(code.strip().splitlines()) if code.strip() else 0,
                    "candidate_revision_validity": revision_validity,
                    "reject_reason": domain_reject_reason,
                    "tree_name": tree_name,
                    "edit_mode": edit_mode,
                    "goal_mode": goal_mode,
                    "goal_guidance": goal_guidance,
                },
            }
        previous_tree_name = ""
        previous_code = ""
        previous_validity = ""
        previous_parameter_refs: list[str] = []
        previous_focus_regions: list[str] = []
        if existing_latest is not None:
            previous_code = str(existing_latest.as_string() or "")
            previous_tree_name = str(existing_latest.get("_draft_tree_name", "") or "")
            previous_validity = _draft_revision_validity(existing_latest)
            previous_parameter_refs = _text_block_str_list(existing_latest, "_draft_expected_parameter_refs", limit=12)
            previous_focus_regions = _text_block_str_list(existing_latest, "_draft_expected_focus_regions", limit=12)
        semantic_reject_reason = ""
        semantic_details: dict[str, list[str]] = {
            "previous_live_node_refs": [],
            "candidate_live_node_refs": [],
            "previous_parameter_refs": [],
            "candidate_parameter_refs": [],
            "previous_focus_regions": [],
            "candidate_focus_regions": [],
        }
        if previous_validity == "valid":
            semantic_reject_reason, semantic_details = _draft_semantic_regression_reason(
                code,
                previous_code=previous_code,
                previous_tree_name=previous_tree_name,
                candidate_tree_name=tree_name or previous_tree_name,
                allow_tree_change=allow_tree_change,
                allow_capability_regression=allow_capability_regression,
                expected_parameter_refs=expected_parameter_refs or previous_parameter_refs,
                expected_focus_regions=expected_focus_regions or previous_focus_regions,
            )
        if semantic_reject_reason:
            return {
                "status": "blocked",
                "error": (
                    "Draft write blocked: the candidate script regressed capabilities that the current living draft "
                    f"already had ({semantic_reject_reason})."
                ),
                "result": {
                    "block_name": block_name,
                    "current_revision": existing_version,
                    "candidate_char_count": len(code),
                    "candidate_line_count": len(code.strip().splitlines()) if code.strip() else 0,
                    "candidate_revision_validity": revision_validity,
                    "reject_reason": semantic_reject_reason,
                    "tree_name": tree_name or previous_tree_name,
                    "previous_tree_name": previous_tree_name,
                    "previous_live_node_refs": semantic_details.get("previous_live_node_refs", []),
                    "candidate_live_node_refs": semantic_details.get("candidate_live_node_refs", []),
                    "previous_parameter_refs": semantic_details.get("previous_parameter_refs", []),
                    "candidate_parameter_refs": semantic_details.get("candidate_parameter_refs", []),
                    "previous_focus_regions": semantic_details.get("previous_focus_regions", []),
                    "candidate_focus_regions": semantic_details.get("candidate_focus_regions", []),
                    "edit_mode": edit_mode,
                    "goal_mode": goal_mode,
                    "goal_guidance": goal_guidance,
                },
            }
        previous_best, _previous_latest = _best_draft_reasoning_block(block_name)
        previous_valid_revision = 0
        if previous_best is not None and _draft_revision_validity(previous_best) == "valid":
            previous_valid_revision = _draft_block_version(previous_best)
        last_valid_revision = next_version if revision_validity == "valid" else previous_valid_revision

        # Create or reuse the text block.
        text_block = bpy.data.texts.get(block_name)
        created = text_block is None
        if text_block is None:
            text_block = bpy.data.texts.new(block_name)
        else:
            text_block.clear()

        text_block.write(code)

        # Store metadata as custom properties on the text block.
        text_block["_draft_description"] = description[:500]
        text_block["_draft_tree_name"] = tree_name
        text_block["_draft_version"] = next_version
        text_block["_draft_revision_created_at"] = created_at
        text_block["_draft_revision_parent"] = existing_version
        text_block["_draft_revision_kind"] = str(cmd.get("revision_kind") or ("create" if existing_version <= 0 else "refine"))
        text_block["_draft_revision_changed_from_previous"] = str(cmd.get("revision_changed_from_previous") or "")[:500]
        text_block["_draft_revision_validity"] = revision_validity
        text_block["_draft_last_valid_revision"] = last_valid_revision
        text_block["_draft_last_executed_revision"] = int(cmd.get("last_executed_revision", 0) or 0)
        text_block["_draft_last_failed_revision"] = int(cmd.get("last_failed_revision", 0) or 0)
        text_block["_draft_expected_parameter_refs"] = json.dumps(expected_parameter_refs, ensure_ascii=False)
        text_block["_draft_expected_focus_regions"] = json.dumps(expected_focus_regions, ensure_ascii=False)
        text_block["_draft_edit_mode"] = edit_mode
        text_block["_draft_goal_mode"] = goal_mode
        text_block["_draft_goal_guidance"] = json.dumps(goal_guidance, ensure_ascii=False)
        draft_archive_path = ""
        draft_archive_error = ""
        if session_id or project_root:
            draft_archive_path, draft_archive_error = _archive_script_draft(
                code=code,
                block_name=text_block.name,
                version=next_version,
                created_at=created_at,
                description=description,
                tree_name=tree_name,
                session_id=session_id,
                project_root=project_root,
            )
        if draft_archive_path:
            text_block["_draft_archive_path"] = draft_archive_path

        return {
            "status": "success",
            "result": {
                "block_name": text_block.name,
                "created": created,
                "line_count": len(text_block.lines),
                "char_count": len(code),
                "version": next_version,
                "description": description[:200],
                "tree_name": tree_name,
                "revision_created_at": created_at,
                "revision_parent": existing_version,
                "revision_kind": str(text_block.get("_draft_revision_kind", "") or ""),
                "revision_changed_from_previous": str(text_block.get("_draft_revision_changed_from_previous", "") or ""),
                "current_revision_validity": revision_validity,
                "revision_validity": revision_validity,
                "last_valid_draft_revision": last_valid_revision,
                "last_executed_revision": int(cmd.get("last_executed_revision", 0) or 0),
                "last_failed_revision": int(cmd.get("last_failed_revision", 0) or 0),
                "expected_parameter_refs": expected_parameter_refs,
                "expected_focus_regions": expected_focus_regions,
                "edit_mode": edit_mode,
                "goal_mode": goal_mode,
                "goal_guidance": goal_guidance,
                "draft_archive_path": draft_archive_path,
                "draft_archive_error": draft_archive_error,
            },
        }

    return execute_in_main_thread(_do)

def handle_read_script_draft(cmd: dict) -> dict:
    """Read the current content of a Blender Text Editor block."""
    import bpy

    from .handlers import execute_in_main_thread

    block_name = str(cmd.get("block_name") or "GN_Agent_Draft").strip()

    def _do():
        requested_block = bpy.data.texts.get(block_name)
        latest_block = _latest_draft_block(block_name)
        text_block = requested_block or latest_block
        if text_block is None:
            available = [t.name for t in bpy.data.texts]
            return {
                "status": "error",
                "error": f"Text block '{block_name}' not found.",
                "available_text_blocks": available,
            }

        source = "text_block" if text_block is requested_block else "legacy_revision_fallback"
        payload = _draft_payload_from_block(text_block, source=source)
        payload["block_name"] = block_name
        if source == "legacy_revision_fallback":
            payload["legacy_block_name"] = text_block.name
            payload["legacy_fallback_used"] = True
        return {
            "status": "success",
            "result": payload,
        }

    return execute_in_main_thread(_do)


__all__ = [
    "_DRAFT_MIN_CHARS",
    "_DRAFT_MIN_LINES",
    "_DRAFT_REVISION_RE",
    "_archive_script_draft",
    "_attribute_chain",
    "_coerce_str_list",
    "_best_draft_reasoning_block",
    "_draft_block_version",
    "_draft_domain_reject_reason",
    "_draft_payload_from_block",
    "_draft_revision_blocks",
    "_draft_revision_validity",
    "_draft_semantic_regression_reason",
    "_draft_revision_reject_reason",
    "_extract_referenced_node_names",
    "_has_geometry_nodes_operations",
    "_infer_draft_revision_validity",
    "_iter_text_blocks",
    "_is_generic_focus_region",
    "_is_nodes_expr",
    "_is_placeholder_draft",
    "_latest_draft_block",
    "_matched_semantic_terms",
    "_safe_draft_filename_part",
    "_semantic_compact",
    "_semantic_term_present",
    "_semantic_text",
    "_text_block_json_dict",
    "_text_block_str_list",
    "handle_write_script_draft",
    "handle_read_script_draft",
]
