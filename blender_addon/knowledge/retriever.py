"""Knowledge retriever for Phase 6 of REFATOR_PLAN.md.

Replaces the keyword-regex selector in ``context_knowledge.select_knowledge``
with a scored, token-budgeted retriever driven by front-matter metadata.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .corpus import KnowledgeCorpus, KnowledgeItem


# Rough chars-per-token ratio used to estimate token counts without tiktoken.
_CHARS_PER_TOKEN: float = 4.0

_PRIORITY_WEIGHT = {"high": 2.0, "medium": 1.0, "low": 0.5}


class KnowledgeRetriever:
    """Score, rank, and budget-clip knowledge items for a single turn."""

    def __init__(self, corpus_dir: Path) -> None:
        self._corpus = KnowledgeCorpus(corpus_dir)

    def retrieve(
        self,
        *,
        session: Any,
        turn_class: str,
        message: str = "",
        budget_tokens: int = 1000,
    ) -> list[KnowledgeItem]:
        """Return the highest-scoring items that fit within *budget_tokens*.

        Items are scored then sorted descending; the budget is filled greedily.
        Items with score == 0 are excluded even if budget remains.
        """
        scored = [
            (item, self._score(item, session, turn_class, message))
            for item in self._corpus.items()
        ]
        # Only include items that matched at least something.
        scored = [(item, s) for item, s in scored if s > 0.0]
        scored.sort(key=lambda t: t[1], reverse=True)

        result: list[KnowledgeItem] = []
        tokens_used = 0
        for item, _score in scored:
            item_tokens = int(len(item.content) / _CHARS_PER_TOKEN) + 1
            if tokens_used + item_tokens > budget_tokens:
                continue
            result.append(item)
            tokens_used += item_tokens

        return result

    def _score(
        self,
        item: KnowledgeItem,
        session: Any,
        turn_class: str,
        message: str,
    ) -> float:
        score = 0.0

        # Turn-class match — strongest signal.
        if turn_class in item.applies_when:
            score += 10.0

        # Priority weight.
        score *= _PRIORITY_WEIGHT.get(item.priority, 1.0)

        # Topic keyword overlap with the user message.
        if message and item.topics:
            msg_lower = message.lower()
            overlap = sum(1 for t in item.topics if t in msg_lower)
            score += float(overlap) * 1.5

        # Category bonus when there is any topic overlap.
        if item.topics and message:
            msg_lower = message.lower()
            has_overlap = any(t in msg_lower for t in item.topics)
            if has_overlap:
                if item.category == "skills":
                    score += 5.0
                elif item.category == "recipes":
                    score += 3.0

        # Session focus tree name appears in the item content → bonus.
        focus = getattr(session, "focus", None)
        tree_name = getattr(focus, "tree_name", "") if focus else ""
        if tree_name and tree_name in item.content:
            score += 3.0

        return score
