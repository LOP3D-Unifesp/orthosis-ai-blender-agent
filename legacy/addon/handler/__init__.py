"""Single workspace handler contract for the slim runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_KNOWLEDGE_BUDGET_BY_CLASS = {
    "trivial_chat": 0,
    "context_inquiry": 450,
    "draft_workspace": 800,
    "execution_feedback": 600,
    "state_control": 0,
}


@dataclass
class HandlerResult:
    response_text: str
    tool_calls_made: list[dict[str, Any]] = field(default_factory=list)
    phase_transition: str | None = None
    session_mutations: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class TurnContext:
    session: Any
    message: str
    meta: Any
    blend_path: str
    image_blocks: list[dict[str, Any]] = field(default_factory=list)
    attachment_text_blocks: list[dict[str, Any]] = field(default_factory=list)
    _runtime: Any = field(default=None, repr=False)
    knowledge_dir: Path = field(default_factory=Path)

    def call_agent_loop(
        self,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
        excluded_tools: "frozenset[str] | None" = None,
        max_rounds: int | None = None,
    ) -> str:
        if max_tokens is None:
            from ..model_policy import select_max_tokens

            turn_class = str(getattr(self.meta, "turn_class", ""))
            if hasattr(getattr(self.meta, "turn_class", None), "value"):
                turn_class = str(getattr(self.meta.turn_class, "value"))
            max_tokens = select_max_tokens(turn_class)
        return self._runtime._agent_loop(
            system,
            messages,
            max_tokens=max_tokens,
            excluded_tools=excluded_tools,
            max_rounds=max_rounds,
        )

    def request_text(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 1024,
    ) -> str:
        return self._runtime._request_text_response(
            system=system,
            messages=messages,
            max_tokens=max_tokens,
        )

    def execute_tool(self, name: str, tool_input: dict[str, Any]) -> str:
        return self._runtime._execute_tool(name, tool_input, 0)

    def log_event(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        try:
            self._runtime.journal.log_runtime_event(
                event_type=event_type,
                payload=payload or {},
            )
        except Exception:
            pass

    def build_messages(self) -> list[dict[str, Any]]:
        signals = set(getattr(self.meta, "signals", []) or [])
        if signals & {"factual_tree_inquiry_in_drafting", "answer_correction_in_drafting"}:
            messages = []
        else:
            messages = list(getattr(self._runtime, "_messages", []))
        content: list[Any] = []
        if self.attachment_text_blocks:
            content.extend(self.attachment_text_blocks)
        if self.image_blocks:
            content.extend(self.image_blocks)
        content.append({"type": "text", "text": self.message})
        messages.append({"role": "user", "content": content if len(content) > 1 else self.message})
        return messages

    @property
    def tools(self) -> list[dict[str, Any]]:
        return list(getattr(self._runtime, "tools", []))

    @property
    def model(self) -> str:
        return str(getattr(self._runtime, "model", "claude-sonnet-4-6"))

    @property
    def journal(self) -> Any:
        return getattr(self._runtime, "journal", None)

    def retrieve_knowledge(self, *, budget_tokens: int | None = None) -> list[dict[str, Any]]:
        from ..knowledge import KnowledgeRetriever

        corpus_root = self.knowledge_dir.parent
        if not corpus_root.is_dir():
            return []
        if budget_tokens is None:
            budget_tokens = _KNOWLEDGE_BUDGET_BY_CLASS.get(str(getattr(self.meta, "turn_class", "")), 600)
        if budget_tokens <= 0:
            return []
        retriever = KnowledgeRetriever(corpus_root)
        items = retriever.retrieve(
            session=self.session,
            turn_class=str(getattr(self.meta, "turn_class", "")),
            message=self.message,
            budget_tokens=budget_tokens,
        )
        return [{"title": item.title, "content": item.content} for item in items]


__all__ = ["HandlerResult", "TurnContext"]
