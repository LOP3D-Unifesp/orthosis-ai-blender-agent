"""Validation helpers for the canonical biomodel source workflow."""

from __future__ import annotations

import ast
from dataclasses import dataclass

from .source_template import BIOMODEL_SOURCE_BLOCK, GENERATED_TREE_NAME, PARAMETERS


@dataclass(frozen=True)
class BiomodelSourceValidation:
    """Result of validating a complete ``GN_Biomodel_Source`` script."""

    valid: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "valid": self.valid,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


def _string_constants(tree: ast.AST) -> list[str]:
    values: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            values.append(node.value)
    return values


def _attribute_chain(node: ast.AST) -> list[str]:
    parts: list[str] = []
    current: ast.AST | None = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return list(reversed(parts))


def _is_bpy_data_node_groups(node: ast.AST) -> bool:
    return _attribute_chain(node) == ["bpy", "data", "node_groups"]


def _literal_string(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ""


def _targets_reference_biomodel(node: ast.AST) -> bool:
    if isinstance(node, ast.Subscript) and _is_bpy_data_node_groups(node.value):
        return _literal_string(node.slice) == "Biomodelo"
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "get" and _is_bpy_data_node_groups(func.value):
            return bool(node.args) and _literal_string(node.args[0]) == "Biomodelo"
    return False


def _mutates_reference_tree(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            if func.attr == "remove" and _is_bpy_data_node_groups(func.value):
                if node.args and _targets_reference_biomodel(node.args[0]):
                    return True
            if func.attr in {"clear", "new"} and _targets_reference_biomodel(func.value):
                return True
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Delete)):
            targets = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.Delete):
                targets = list(node.targets)
            else:
                targets = [node.target]
            if any(_targets_reference_biomodel(target) for target in targets):
                return True
    return False


def validate_biomodel_source(code: str) -> BiomodelSourceValidation:
    """Validate source-mode invariants without touching Blender state."""

    source = str(code or "")
    stripped = source.strip()
    errors: list[str] = []
    warnings: list[str] = []
    if not stripped:
        errors.append("empty_source")
        return BiomodelSourceValidation(False, tuple(errors), tuple(warnings))

    try:
        tree = ast.parse(stripped)
        compile(stripped, BIOMODEL_SOURCE_BLOCK, "exec")
    except SyntaxError as exc:
        errors.append(f"syntax_error:{exc.msg}")
        return BiomodelSourceValidation(False, tuple(errors), tuple(warnings))

    if BIOMODEL_SOURCE_BLOCK not in source:
        errors.append(f"missing_source_block_marker:{BIOMODEL_SOURCE_BLOCK}")
    if GENERATED_TREE_NAME not in source:
        errors.append(f"missing_generated_tree_name:{GENERATED_TREE_NAME}")
    if _mutates_reference_tree(tree):
        errors.append("mutates_reference_tree:Biomodelo")

    string_values = _string_constants(tree)
    parameter_names = [name for name, _identifier, _default, _role in PARAMETERS]
    missing_parameters = [name for name in parameter_names if name not in string_values]
    if missing_parameters:
        errors.append(f"missing_required_parameters:{len(missing_parameters)}")

    if "Geometry" not in string_values:
        warnings.append("geometry_output_not_explicitly_named")
    if "bpy.data.node_groups.remove(existing)" not in source:
        warnings.append("generated_tree_replacement_not_obvious")

    return BiomodelSourceValidation(
        valid=not errors,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


__all__ = ["BiomodelSourceValidation", "validate_biomodel_source"]
