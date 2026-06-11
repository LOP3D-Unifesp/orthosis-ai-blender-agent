"""Baseline workspace builder — structural summary management.

:class:`BaselineBuilder` wraps a :class:`~session.schema.BaselineWorkspace`
and provides:

* deterministic structural signatures (SHA-1 of the summary dict),
* staleness tracking (mark/probe),
* ``is_sufficient_for`` — content-aware probe used by handlers before
  deciding whether to re-read the tree.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .schema import BaselineWorkspace, utc_now_iso


def compute_tree_signature(structural_summary: dict[str, Any] | None) -> str:
    """Return a deterministic hex digest for a structural summary.

    The summary is serialised with ``sort_keys=True`` so equivalent summaries
    always produce the same signature regardless of dict ordering.
    """
    if not structural_summary:
        return ""
    try:
        raw = json.dumps(structural_summary, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        raw = str(structural_summary)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


class BaselineBuilder:
    """Build / refresh / probe a :class:`BaselineWorkspace`."""

    def __init__(self, baseline: BaselineWorkspace) -> None:
        self.baseline = baseline

    # ---- build / refresh -------------------------------------------------

    def rebuild_from_summary(
        self,
        structural_summary: dict[str, Any],
        *,
        built_from: str = "auto",
        semantic_layers: list[dict[str, Any]] | None = None,
        subgraph_index: dict[str, Any] | None = None,
        recipe_associations: list[dict[str, Any]] | None = None,
        known_parameters: dict[str, Any] | None = None,
        open_questions: list[str] | None = None,
    ) -> BaselineWorkspace:
        """Replace the baseline with a freshly built snapshot."""
        if built_from not in {"auto", "user_request", "post_mutation"}:
            raise ValueError(f"unknown built_from: {built_from!r}")
        signature = compute_tree_signature(structural_summary)
        self.baseline.tree_signature = signature
        self.baseline.built_at = utc_now_iso()
        self.baseline.built_from = built_from
        self.baseline.structural_summary = dict(structural_summary or {})
        if semantic_layers is not None:
            self.baseline.semantic_layers = [dict(item) for item in semantic_layers]
        if subgraph_index is not None:
            self.baseline.subgraph_index = dict(subgraph_index)
        if recipe_associations is not None:
            self.baseline.recipe_associations = [dict(item) for item in recipe_associations]
        if known_parameters is not None:
            self.baseline.known_parameters = dict(known_parameters)
        if open_questions is not None:
            self.baseline.open_questions = [str(q) for q in open_questions if str(q).strip()]
        self.baseline.stale = False
        return self.baseline

    def mark_stale(self) -> None:
        self.baseline.stale = True

    # ---- probes ----------------------------------------------------------

    def is_built(self) -> bool:
        return self.baseline.is_built()

    def is_stale(self) -> bool:
        return bool(self.baseline.stale) or not self.is_built()

    def matches_signature(self, structural_summary: dict[str, Any] | None) -> bool:
        """Return True if a freshly observed summary matches the stored signature."""
        if not self.is_built():
            return False
        return compute_tree_signature(structural_summary) == self.baseline.tree_signature

    def is_sufficient_for(self, *, requires: set[str] | None = None) -> bool:
        """Return True if the baseline is built, fresh, and contains all required blocks.

        ``requires`` is a set of key names the caller needs:
        ``"structural_summary"``, ``"subgraph_index"``, ``"semantic_layers"``,
        ``"known_parameters"``.
        """
        if self.is_stale():
            return False
        needed = requires or set()
        for key in needed:
            if key == "structural_summary" and not self.baseline.structural_summary:
                return False
            if key == "subgraph_index" and not self.baseline.subgraph_index:
                return False
            if key == "semantic_layers" and not self.baseline.semantic_layers:
                return False
            if key == "known_parameters" and not self.baseline.known_parameters:
                return False
        return True
