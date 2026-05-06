"""Model routing policy for the draft-first product runtime."""

from __future__ import annotations

import re


LIGHT_MODEL: str = "claude-haiku-4-5"

_LIGHT_TURN_CLASSES = frozenset({
    "trivial_chat",
    "state_control",
})

_EXECUTION_DIAGNOSIS_RE = re.compile(
    r"\b("
    r"erro|falh|deu\s+errado|n[aã]o\s+(deu|funcionou|foi)|nada\s+aconteceu|"
    r"sem\s+efeito|ctrl\s*\+?\s*z|desfiz|revert|apagou|sumiu|"
    r"por\s+que|porque|o\s+que\s+.*errad|sliders?.*n[aã]o|"
    r"error|fail|failed|wrong|why|nothing\s+happened|no\s+effect|undo|reverted"
    r")\b",
    re.IGNORECASE,
)

_MAX_TOKENS_BY_CLASS = {
    "trivial_chat": 256,
    "context_inquiry": 4096,
    "draft_workspace": 6000,
    "execution_feedback": 4096,
    "state_control": 1024,
}


def select_model(turn_class: str, default_model: str, message: str = "") -> str:
    """Return the model identifier to use for a draft-first turn."""
    if turn_class == "execution_feedback" and _EXECUTION_DIAGNOSIS_RE.search(message or ""):
        return default_model
    if turn_class in _LIGHT_TURN_CLASSES:
        return LIGHT_MODEL
    return default_model


def select_max_tokens(turn_class: str, default: int = 4096) -> int:
    """Return the output ceiling for a draft-first turn."""
    return _MAX_TOKENS_BY_CLASS.get(turn_class, default)
