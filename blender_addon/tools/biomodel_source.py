"""Tools for the biomodel-source migration workflow."""

from __future__ import annotations

from typing import Any

from ..biomodel import (
    BIOMODEL_SOURCE_BLOCK,
    GENERATED_TREE_NAME,
    SOURCE_TEMPLATE_VERSION,
    build_biomodel_source_template,
)
from . import draft


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


__all__ = ["handle_seed_biomodel_source"]

