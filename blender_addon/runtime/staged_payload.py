"""Helpers for classifying and validating staged execute_code payloads."""

from __future__ import annotations

import re
from typing import Any


_PLACEHOLDER_PATTERNS = (
    re.compile(r"^\[\s*\d+\s*-\s*char script\s*\]$", re.IGNORECASE),
    re.compile(r"^\[[^\]]*(?:char script|script preview|script summary|script omitted|truncated)[^\]]*\]$", re.IGNORECASE),
)

_MUTATING_PATTERNS = (
    re.compile(r"\bbpy\.ops\.", re.IGNORECASE),
    re.compile(r"\b(?:nodes|links|interface|modifiers|objects|collections|node_groups)\.new\(", re.IGNORECASE),
    re.compile(r"\b(?:nodes|links|interface|modifiers|objects|collections|node_groups)\.remove\(", re.IGNORECASE),
    re.compile(r"\binterface\.new_socket\(", re.IGNORECASE),
    re.compile(r"\blinks\.new\(", re.IGNORECASE),
    re.compile(
        r"\.(?:default_value|name|label|location|parent|hide|mute|width|height|operation|data_type|"
        r"attribute_name|use_custom_color|is_active_output)\s*=",
        re.IGNORECASE,
    ),
)


def is_placeholder_script(code: str) -> bool:
    text = str(code or "").strip()
    if not text:
        return False
    return any(pattern.match(text) for pattern in _PLACEHOLDER_PATTERNS)


def describe_execute_code_script(code: str) -> dict[str, Any]:
    text = str(code or "")
    placeholder = is_placeholder_script(text)
    mutating = False if placeholder else _looks_mutating(text)
    classification = "mutating" if mutating else "read_only"
    return {
        "classification": classification,
        "classification_label": "mutating change" if mutating else "read-only diagnostic",
        "expected_visible_effect": "will change scene" if mutating else "no visible scene change",
        "edits_blender_data": bool(mutating),
        "script_behavior": (
            "actually edits Blender data"
            if mutating
            else "only prints/inspects Blender data"
        ),
        "has_placeholder": bool(placeholder),
        "script_length": len(text),
    }


def classify_staged_payload(tool_calls: list[dict[str, Any]], focus: Any = None) -> dict[str, Any]:
    has_mutation_tool = False
    has_execute_code = False
    has_placeholder = False
    script_lengths: list[int] = []

    for call in tool_calls or []:
        if not isinstance(call, dict):
            continue
        name = str(call.get("name") or "").strip()
        tool_input = call.get("input") if isinstance(call.get("input"), dict) else {}
        if name == "execute_code":
            has_execute_code = True
            code = str(tool_input.get("code") or tool_input.get("script") or "")
            code_info = describe_execute_code_script(code)
            script_lengths.append(int(code_info.get("script_length", len(code)) or 0))
            if bool(code_info.get("has_placeholder")):
                has_placeholder = True
            elif str(code_info.get("classification") or "") == "mutating":
                has_mutation_tool = True
        elif name and name != "make_plan":
            has_mutation_tool = True

    classification = "mutating" if has_mutation_tool else "read_only"
    return {
        "classification": classification,
        "classification_label": "mutating change" if has_mutation_tool else "read-only diagnostic",
        "expected_visible_effect": "will change scene" if has_mutation_tool else "no visible scene change",
        "edits_blender_data": bool(has_mutation_tool),
        "script_behavior": (
            "actually edits Blender data"
            if has_mutation_tool
            else "only prints/inspects Blender data"
        ),
        "has_execute_code": bool(has_execute_code),
        "has_placeholder": bool(has_placeholder),
        "target_summary": build_target_summary(focus),
        "script_lengths": list(script_lengths),
    }


def build_target_summary(focus: Any) -> dict[str, str]:
    if focus is None:
        return {
            "object": "(not set)",
            "modifier": "(not set)",
            "node_group": "(not set)",
        }
    object_name = str(getattr(focus, "object_name", "") or "").strip() or "(not set)"
    modifier_name = str(getattr(focus, "modifier_name", "") or "").strip() or "(not set)"
    tree_name = str(getattr(focus, "tree_name", "") or "").strip() or "(not set)"
    return {
        "object": object_name,
        "modifier": modifier_name,
        "node_group": tree_name,
    }


def guard_execute_code_payload(code: str) -> str | None:
    if is_placeholder_script(code):
        return (
            "Blocked execute_code: staged payload contains a placeholder/summary "
            "string instead of executable Python code."
        )
    return None


def _looks_mutating(code: str) -> bool:
    text = str(code or "")
    if not text.strip():
        return False
    return any(pattern.search(text) for pattern in _MUTATING_PATTERNS)
