"""Classifiers for user feedback after running a drafted script."""

from __future__ import annotations

import unicodedata


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


def _contains_ordered_groups(words: list[str], *groups: set[str]) -> bool:
    position = 0
    for group in groups:
        while position < len(words) and words[position] not in group:
            position += 1
        if position >= len(words):
            return False
        position += 1
    return True


def _is_execution_diagnosis_request(message: str) -> bool:
    words = _message_words(message)
    word_set = set(words)
    return (
        _has_prefix(words, "erro", "falh", "revert", "apagou", "sumiu", "problem")
        or _has_phrase(words, "deu", "errado")
        or ("nao" in word_set and bool({"deu", "funcionou", "foi", "esta"} & word_set))
        or _has_phrase(words, "nada", "aconteceu")
        or _has_phrase(words, "sem", "efeito")
        or _has_phrase(words, "ctrl", "z")
        or _has_phrase(words, "control", "z")
        or "desfiz" in word_set
        or _has_phrase(words, "por", "que")
        or "porque" in word_set
        or "why" in word_set
        or "wrong" in word_set
        or "failed" in word_set
        or _has_phrase(words, "nothing", "happened")
        or _has_phrase(words, "no", "effect")
        or (_has_prefix(words, "slider") and "nao" in word_set)
    )


def _classify_execution_feedback(message: str) -> tuple[str, bool]:
    words = _message_words(message)
    word_set = set(words)

    reverted = (
        bool({"desfiz", "undo", "reverti", "revertido", "reverted"} & word_set)
        or _has_phrase(words, "ctrl", "z")
        or _has_phrase(words, "control", "z")
        or _has_phrase(words, "voltei", "atras")
    )
    if reverted:
        return "reverted_by_user", True

    if _has_phrase(words, "nada", "aconteceu") or _has_phrase(words, "sem", "efeito") or _has_phrase(words, "no", "effect"):
        return "executed_no_effect", False

    none_words = {"nenhum", "nenhuma", "none"}
    control_words = {"slider", "sliders", "controle", "controles"}
    response_prefixes = ("funcion", "mex", "move", "alter", "respond")
    if bool(none_words & word_set) and bool(control_words & word_set) and _has_prefix(words, *response_prefixes):
        return "executed_no_effect", False
    if bool(control_words & word_set) and "nao" in word_set and _has_prefix(words, *response_prefixes):
        return "executed_no_effect", False
    if _contains_ordered_groups(words, {"nao"}, control_words) and _has_prefix(words, *response_prefixes):
        return "executed_no_effect", False

    failed = (
        _has_phrase(words, "deu", "errado")
        or _has_phrase(words, "nao", "deu", "certo")
        or _has_phrase(words, "nao", "funcionou")
        or bool({"falhou", "erro", "failed", "wrong", "sumiu", "sumiram", "sumindo", "desapareceu", "desapareceram", "apagou"} & word_set)
    )
    if failed:
        return "executed_failed", False

    if _has_prefix(words, "parcial", "partial", "metade", "incomplet"):
        return "executed_partial_failure", False

    return "executed", False
