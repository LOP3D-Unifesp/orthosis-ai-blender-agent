"""Runtime helpers shared by draft workspace handlers."""

from __future__ import annotations

from . import TurnContext


def _replace_last_assistant_message(runtime, text: str) -> None:
    messages = getattr(runtime, "_messages", None)
    if not isinstance(messages, list) or not messages:
        return
    for idx in range(len(messages) - 1, -1, -1):
        item = messages[idx]
        if isinstance(item, dict) and item.get("role") == "assistant":
            messages[idx] = {"role": "assistant", "content": text}
            return


def _with_draft_streaming_disabled(ctx: TurnContext, fn):
    runtime = ctx._runtime
    previous = getattr(runtime, "on_text_chunk", None)
    try:
        runtime.on_text_chunk = None
        return fn()
    finally:
        runtime.on_text_chunk = previous
