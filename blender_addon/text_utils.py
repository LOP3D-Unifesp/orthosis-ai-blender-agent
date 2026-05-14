"""Lightweight text-normalisation helpers shared across the addon.

These three primitives — ``message_words``, ``has_prefix``, ``has_phrase`` —
were duplicated byte-identically in five modules (model_policy, fast_path,
handler/draft_state, handler/feedback_classifier, handler/feedback_evidence).
This module is the single source of truth.

All helpers are pure: they normalise an input string the same way (NFKD,
lowercase, drop combining marks, replace non-alphanumerics with spaces) so
intent classifiers and fast-path matchers see the same tokens.

``clean_text`` returns the normalised string itself (used by ``fast_path`` to
do whole-phrase lookups in the greeting table). ``message_words`` returns the
split tokens (used everywhere else).

Underscore-prefixed aliases are exported for callers that historically used
private names; they are simple re-exports of the public functions.
"""

from __future__ import annotations

import unicodedata


def clean_text(value: str) -> str:
    """Return the canonical normalised form of *value* as a single string."""
    normalized = unicodedata.normalize("NFKD", str(value or "").lower())
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = "".join(ch if ch.isalnum() else " " for ch in normalized)
    return " ".join(normalized.split())


def message_words(message: str) -> list[str]:
    """Return *message* normalised and split into alphanumeric tokens."""
    normalized = unicodedata.normalize("NFKD", str(message or "").lower())
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = "".join(ch if ch.isalnum() else " " for ch in normalized)
    return normalized.split()


def has_prefix(words: list[str], *prefixes: str) -> bool:
    """True iff any *word* starts with any of *prefixes*."""
    return any(any(word.startswith(prefix) for prefix in prefixes) for word in words)


def has_phrase(words: list[str], *phrase_words: str) -> bool:
    """True iff *words* contains the contiguous subsequence *phrase_words*."""
    size = len(phrase_words)
    if size == 0 or len(words) < size:
        return False
    return any(
        tuple(words[index:index + size]) == phrase_words
        for index in range(len(words) - size + 1)
    )


# Underscore aliases: callers that used private names continue to work.
_clean_text = clean_text
_message_words = message_words
_has_prefix = has_prefix
_has_phrase = has_phrase


__all__ = [
    "clean_text",
    "message_words",
    "has_prefix",
    "has_phrase",
    "_clean_text",
    "_message_words",
    "_has_prefix",
    "_has_phrase",
]
