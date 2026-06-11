"""Small runtime-planning helpers that still have live callers."""

from __future__ import annotations

import re
import unicodedata
from typing import Any


FOCAL_READ_TOOLS = {
    "get_node_context",
    "get_selected_nodes_context",
    "get_active_frame_context",
    "get_local_subgraph_context",
    "get_changes_since_last_turn",
}


def _intent_text(text: str) -> str:
    """Lowercase and accent-fold user text for intent-only matching."""
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    asciiish = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", asciiish.lower()).strip()


def is_scene_wide_gn_inspection_request(message: str) -> bool:
    """Return True for read-only requests about all GN-bearing scene objects/trees."""
    text = _intent_text(message)
    if not text:
        return False

    has_scene_scope = any(
        token in text
        for token in (
            "cena",
            "scene",
            "objetos",
            "objects",
            "todos",
            "todas",
            "all gn",
            "scene-wide",
            "scene wide",
        )
    )
    has_gn_surface = any(
        token in text
        for token in (
            "gn",
            "geometry nodes",
            "geonodes",
            "arvore",
            "arvores",
            "rvore",
            "rvores",
            "tree",
            "trees",
            "node group",
            "node groups",
        )
    )
    has_read_intent = any(
        token in text
        for token in (
            "quais",
            "qual",
            "listar",
            "lista",
            "liste",
            "mostrar",
            "mostre",
            "ler",
            "leitura",
            "testar",
            "inspec",
            "ver",
            "verificar",
            "conferir",
            "read",
            "inspect",
            "list",
            "show",
            "which",
            "what",
        )
    )

    if re.search(r"\bquais?\s+(arvores|trees|objetos|objects)\b", text) and has_scene_scope:
        return True
    if re.search(r"\bobjetos?\s+(com|que\s+(recebem|tem|contem))\s+(gn|geometry nodes|geonodes)\b", text):
        return True
    if "leitura de objetos" in text and ("arvore" in text or "gn" in text or "geometry nodes" in text):
        return True
    return has_scene_scope and has_gn_surface and has_read_intent


def extract_tree_name(tool_input: dict[str, Any]) -> str:
    for key in ("tree_name", "target_tree"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def extract_node_name(tool_input: dict[str, Any]) -> str:
    for key in ("node_name", "node", "name", "from_node", "old_name", "object_name"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
