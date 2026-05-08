"""Model routing policy for the draft-first product runtime."""

from __future__ import annotations

import unicodedata


LIGHT_MODEL: str = "claude-haiku-4-5"

_LIGHT_TURN_CLASSES = frozenset({
    "trivial_chat",
    "state_control",
})

_MAX_TOKENS_BY_CLASS = {
    "trivial_chat": 256,
    "context_inquiry": 4096,
    "draft_workspace": 6000,
    "execution_feedback": 4096,
    "state_control": 1024,
}


def _message_words(message: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", str(message or "").lower())
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = "".join(ch if ch.isalnum() else " " for ch in normalized)
    return normalized.split()


def _has_prefix(words: list[str], *prefixes: str) -> bool:
    return any(any(word.startswith(prefix) for prefix in prefixes) for word in words)


def _has_phrase(words: list[str], *phrase_words: str) -> bool:
    size = len(phrase_words)
    if size == 0 or len(words) < size:
        return False
    return any(tuple(words[index:index + size]) == phrase_words for index in range(len(words) - size + 1))


def _is_execution_diagnosis_message(message: str) -> bool:
    words = _message_words(message)
    word_set = set(words)
    return (
        _has_prefix(words, "erro", "falh", "revert", "apagou", "sumiu")
        or _has_phrase(words, "deu", "errado")
        or ("nao" in word_set and bool({"deu", "funcionou", "foi"} & word_set))
        or _has_phrase(words, "nada", "aconteceu")
        or _has_phrase(words, "sem", "efeito")
        or _has_phrase(words, "ctrl", "z")
        or "desfiz" in word_set
        or _has_phrase(words, "por", "que")
        or "porque" in word_set
        or "why" in word_set
        or bool({"error", "fail", "failed", "wrong", "undo", "reverted"} & word_set)
        or _has_phrase(words, "nothing", "happened")
        or _has_phrase(words, "no", "effect")
        or (_has_prefix(words, "slider") and "nao" in word_set)
    )


def select_model(turn_class: str, default_model: str, message: str = "") -> str:
    """Return the model identifier to use for a draft-first turn."""
    if turn_class == "execution_feedback" and _is_execution_diagnosis_message(message):
        return default_model
    if turn_class in _LIGHT_TURN_CLASSES:
        return LIGHT_MODEL
    return default_model


def select_max_tokens(turn_class: str, default: int = 4096) -> int:
    """Return the output ceiling for a draft-first turn."""
    return _MAX_TOKENS_BY_CLASS.get(turn_class, default)
