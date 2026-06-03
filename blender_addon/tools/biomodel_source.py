"""Tools for the biomodel-source migration workflow."""

from __future__ import annotations

from typing import Any

from ..biomodel import (
    BIOMODEL_SOURCE_BLOCK,
    GENERATED_TREE_NAME,
    SOURCE_TEMPLATE_VERSION,
    build_biomodel_source_template,
    validate_biomodel_source,
)
from . import draft


def _source_payload_from_block(text_block: Any, *, source: str = "text_block") -> dict[str, Any]:
    content = str(text_block.as_string() or "")
    validation = validate_biomodel_source(content).as_dict()
    try:
        version = int(text_block.get("_biomodel_source_version", 0) or 0)
    except Exception:
        version = 0
    return {
        "block_name": text_block.name,
        "source_block_name": text_block.name,
        "content": content,
        "line_count": len(text_block.lines),
        "char_count": len(content),
        "version": version,
        "description": str(text_block.get("_biomodel_source_description", "") or ""),
        "revision_created_at": str(text_block.get("_biomodel_source_revision_created_at", "") or ""),
        "revision_parent": int(text_block.get("_biomodel_source_revision_parent", 0) or 0),
        "revision_kind": str(text_block.get("_biomodel_source_revision_kind", "") or ""),
        "revision_changed_from_previous": str(
            text_block.get("_biomodel_source_revision_changed_from_previous", "") or ""
        ),
        "generated_tree_name": str(text_block.get("_biomodel_generated_tree_name", "") or GENERATED_TREE_NAME),
        "manual_execution_required": True,
        "validation": validation,
        "source": source,
    }


def handle_validate_biomodel_source(cmd: dict[str, Any]) -> dict[str, Any]:
    """Validate a complete biomodel source script without executing it."""

    code = str(cmd.get("code") or "")
    if not code and cmd.get("block_name"):
        read = handle_read_biomodel_source({"block_name": cmd.get("block_name")})
        if read.get("status") != "success":
            return read
        result = read.get("result", {}) if isinstance(read.get("result"), dict) else {}
        code = str(result.get("content") or "")
    validation = validate_biomodel_source(code)
    return {
        "status": "success" if validation.valid else "blocked",
        "result": {
            **validation.as_dict(),
            "source_block_name": str(cmd.get("block_name") or BIOMODEL_SOURCE_BLOCK).strip(),
            "generated_tree_name": GENERATED_TREE_NAME,
        },
    }


def handle_read_biomodel_source(cmd: dict[str, Any]) -> dict[str, Any]:
    """Read the canonical biomodel source Text block."""

    import bpy

    from .handlers import execute_in_main_thread

    block_name = str(cmd.get("block_name") or BIOMODEL_SOURCE_BLOCK).strip()

    def _do():
        text_block = bpy.data.texts.get(block_name)
        if text_block is None:
            available = [t.name for t in bpy.data.texts]
            return {
                "status": "error",
                "error": f"Text block '{block_name}' not found.",
                "available_text_blocks": available,
            }
        return {"status": "success", "result": _source_payload_from_block(text_block)}

    return execute_in_main_thread(_do)


def handle_write_biomodel_source(cmd: dict[str, Any]) -> dict[str, Any]:
    """Write a complete canonical biomodel source script to Text Editor.

    This is intentionally source-mode specific: it validates biomodel source
    invariants directly and does not route through ``write_script_draft`` or
    the legacy draft finalizer semantics.
    """

    import time

    import bpy

    from .handlers import execute_in_main_thread

    block_name = str(cmd.get("block_name") or BIOMODEL_SOURCE_BLOCK).strip()
    code = str(cmd.get("code") or "")
    description = str(cmd.get("description") or "").strip()

    def _do():
        validation = validate_biomodel_source(code)
        if not validation.valid:
            return {
                "status": "blocked",
                "error": "Biomodel source write blocked: source invariants failed.",
                "result": {
                    "block_name": block_name,
                    "source_block_name": block_name,
                    "candidate_char_count": len(code),
                    "candidate_line_count": len(code.strip().splitlines()) if code.strip() else 0,
                    "validation": validation.as_dict(),
                    "generated_tree_name": GENERATED_TREE_NAME,
                    "manual_execution_required": True,
                },
            }

        existing = bpy.data.texts.get(block_name)
        try:
            existing_version = int(existing.get("_biomodel_source_version", 0) or 0) if existing is not None else 0
        except Exception:
            existing_version = 0
        next_version = existing_version + 1
        created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        text_block = existing
        created = text_block is None
        if text_block is None:
            text_block = bpy.data.texts.new(block_name)
        else:
            text_block.clear()
        text_block.write(code)

        text_block["_biomodel_source_description"] = description[:500]
        text_block["_biomodel_source_version"] = next_version
        text_block["_biomodel_source_revision_created_at"] = created_at
        text_block["_biomodel_source_revision_parent"] = existing_version
        text_block["_biomodel_source_revision_kind"] = str(
            cmd.get("revision_kind") or ("create" if existing_version <= 0 else "refine")
        )
        text_block["_biomodel_source_revision_changed_from_previous"] = str(
            cmd.get("revision_changed_from_previous") or ""
        )[:500]
        text_block["_biomodel_generated_tree_name"] = GENERATED_TREE_NAME

        payload = _source_payload_from_block(text_block)
        payload["created"] = created
        return {"status": "success", "result": payload}

    return execute_in_main_thread(_do)


def handle_seed_biomodel_source(cmd: dict[str, Any]) -> dict[str, Any]:
    """Write the phase-1 canonical biomodel source template to Text Editor.

    The written script is not executed. It creates/replaces only the generated
    tree when the user manually runs it in Blender.
    """
    block_name = str(cmd.get("block_name") or BIOMODEL_SOURCE_BLOCK).strip()
    code = build_biomodel_source_template()
    write_input = {
        "block_name": block_name,
        "code": code,
        "description": (
            f"Seed canonical biomodel source template v{SOURCE_TEMPLATE_VERSION}; "
            f"manual execution generates {GENERATED_TREE_NAME}."
        ),
        "revision_kind": "create",
        "revision_changed_from_previous": "Seeded phase-1 biomodel source prototype.",
        "allow_tree_change": True,
        "allow_capability_regression": True,
        "edit_mode": "intentional_rebuild",
        "goal_mode": "biomodel_source",
        "goal_guidance": {
            "source_block": block_name,
            "generated_tree": GENERATED_TREE_NAME,
            "source_template_version": SOURCE_TEMPLATE_VERSION,
            "does_not_mutate_reference_tree": True,
        },
        "expected_parameter_refs": [
            "Comp Antebraço",
            "Raio Cotovelo",
            "Raio Punho",
            "Comp Metacarpo",
            "Largura Metacarpo",
            "Espessura Metacarpo",
        ],
        "expected_focus_regions": [
            "Antebraço",
            "Polegar",
            "Desvio e Ext/Flex Punho",
            "Metacarpos",
        ],
    }
    for key in ("session_id", "project_root"):
        if cmd.get(key):
            write_input[key] = cmd.get(key)
    result = draft.handle_write_script_draft(write_input)
    if result.get("status") == "success" and isinstance(result.get("result"), dict):
        result["result"]["source_block_name"] = block_name
        result["result"]["generated_tree_name"] = GENERATED_TREE_NAME
        result["result"]["source_template_version"] = SOURCE_TEMPLATE_VERSION
        result["result"]["manual_execution_required"] = True
    return result


__all__ = [
    "handle_read_biomodel_source",
    "handle_seed_biomodel_source",
    "handle_validate_biomodel_source",
    "handle_write_biomodel_source",
]
