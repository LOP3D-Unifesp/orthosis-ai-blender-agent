"""Prompt builder facade for the slim workspace handler."""

from __future__ import annotations

from typing import Any

from ..runtime.prompt_builder import (
    build_post_failure_diagnosis_contract,
    build_system_prompt as _build_system_prompt,
)


def build_system_prompt(session: Any, goal_mode: str, *, knowledge: list[dict[str, Any]] | None = None) -> str:
    turn_class = "context_inquiry" if goal_mode == "inquiry" else "draft_workspace"
    return _build_system_prompt(session, turn_class, knowledge=knowledge)


__all__ = ["build_post_failure_diagnosis_contract", "build_system_prompt"]
