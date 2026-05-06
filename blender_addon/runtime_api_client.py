"""API client helpers for Anthropic calls and response extraction."""

from __future__ import annotations

import time
from typing import Any, Callable


def extract_text(response: Any) -> str:
    texts = []
    for block in response.content:
        if hasattr(block, "text"):
            texts.append(block.text)
    return "\n".join(texts) if texts else ""


def is_transient_api_error(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    return (
        "rate" in name
        or "429" in msg
        or "overloaded" in name
        or "overloaded" in msg
        or "timeout" in name
        or "temporarily unavailable" in msg
    )


# ---------------------------------------------------------------------------
# Prompt-caching helpers (Anthropic ephemeral cache, TTL ~5 min)
#
# WHERE CACHE ACTUALLY HITS
#
# Intra-turn (within a single agent_loop call, rounds 2-N):
#   Both system prompt and tool schemas are identical on every round of the
#   same turn — cache hits from round 2 onwards, saving up to 90 % on those
#   blocks per additional round.
#
# Cross-turn (tool schemas only — reliable):
#   AGENT_TOOLS is a module-level constant, never mutated between turns.
#   The cache hits on tool schemas on virtually every turn after the first.
#   Typical saving: ~1000-1500 tokens per turn at 10 % of normal input price.
#
# Cross-turn (system prompt — NOT reliable):
#   build_system_prompt() produces dynamic content every turn: focused tree
#   name, baseline state, selected knowledge items, and execution-state hints
#   all change between turns.  Any difference in the string breaks the cache.
#   Do NOT rely on cross-turn system-prompt caching.
#
# COST MODEL
#   Cache write (first use / after TTL): 1.25x normal input price.
#   Cache read (subsequent uses):        0.10x normal input price.
#   Break-even: hit the cache at least once within the TTL to come out ahead.
#   Multi-round turns (≥2 rounds) always benefit; single-round turns on tools
#   pay 1.25x on first call but 0.10x on every call in the same session.
# ---------------------------------------------------------------------------

def _cached_system(system: str) -> list[dict]:
    """Return system content as a cache_control block list."""
    return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]


def _cached_tools(tools: list) -> list:
    """Add cache_control to the last tool so all tool defs are cached together.

    The Anthropic cache covers everything up to and including the breakpoint.
    Putting the marker on the last tool caches the entire tool list in one
    block.
    """
    if not tools:
        return tools
    tools = list(tools)  # shallow copy — don't mutate caller's list
    last = dict(tools[-1])  # copy the last tool dict
    last["cache_control"] = {"type": "ephemeral"}
    return tools[:-1] + [last]


def request_with_retry(
    runtime: Any,
    *,
    system: str,
    messages: list[dict[str, Any]],
    max_tokens: int = 4096,
    max_retries: int,
    retry_wait_seconds: list[int],
    is_transient_api_error_fn: Callable[[Exception], bool],
):
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return runtime.client.messages.create(
                model=runtime.model,
                max_tokens=max_tokens,
                system=_cached_system(system),
                tools=_cached_tools(runtime.tools),
                messages=messages,
            )
        except Exception as exc:
            last_exc = exc
            transient = is_transient_api_error_fn(exc)
            if not transient or attempt >= max_retries:
                runtime.journal.log_runtime_event(
                    event_type="api_call_failed",
                    payload={
                        "attempt": attempt + 1,
                        "error": str(exc),
                        "transient": transient,
                        "model": getattr(runtime, "model", ""),
                    },
                    status="error",
                )
                raise
            wait_seconds = retry_wait_seconds[min(attempt, len(retry_wait_seconds) - 1)]
            runtime.journal.log_runtime_event(
                event_type="retry",
                payload={
                    "attempt": attempt + 1,
                    "wait_seconds": wait_seconds,
                    "error": str(exc),
                    "model": getattr(runtime, "model", ""),
                },
                status="warning",
            )
            time.sleep(wait_seconds)
    raise last_exc  # pragma: no cover


def stream_with_retry(
    runtime: Any,
    *,
    system: str,
    messages: list[dict[str, Any]],
    max_tokens: int = 4096,
    max_retries: int,
    retry_wait_seconds: list[int],
    is_transient_api_error_fn: Callable[[Exception], bool],
    on_text_chunk: Callable[[str], None] | None = None,
):
    """Like request_with_retry but streams text via on_text_chunk.

    Returns the final Message object (same shape as messages.create),
    so callers can read .content, .stop_reason, .usage etc. normally.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            with runtime.client.messages.stream(
                model=runtime.model,
                max_tokens=max_tokens,
                system=_cached_system(system),
                tools=_cached_tools(runtime.tools),
                messages=messages,
            ) as stream:
                for text_chunk in stream.text_stream:
                    if on_text_chunk:
                        try:
                            on_text_chunk(text_chunk)
                        except Exception:
                            pass
                return stream.get_final_message()
        except Exception as exc:
            last_exc = exc
            transient = is_transient_api_error_fn(exc)
            if not transient or attempt >= max_retries:
                runtime.journal.log_runtime_event(
                    event_type="api_call_failed",
                    payload={
                        "attempt": attempt + 1,
                        "error": str(exc),
                        "transient": transient,
                        "model": getattr(runtime, "model", ""),
                        "mode": "streaming",
                    },
                    status="error",
                )
                raise
            wait_seconds = retry_wait_seconds[min(attempt, len(retry_wait_seconds) - 1)]
            runtime.journal.log_runtime_event(
                event_type="retry",
                payload={
                    "attempt": attempt + 1,
                    "wait_seconds": wait_seconds,
                    "error": str(exc),
                    "model": getattr(runtime, "model", ""),
                    "mode": "streaming",
                },
                status="warning",
            )
            time.sleep(wait_seconds)
    raise last_exc  # pragma: no cover


def request_text_with_retry(
    runtime: Any,
    *,
    system: str,
    messages: list[dict[str, Any]],
    max_tokens: int,
    max_retries: int,
    retry_wait_seconds: list[int],
    is_transient_api_error_fn: Callable[[Exception], bool],
):
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return runtime.client.messages.create(
                model=runtime.model,
                max_tokens=max_tokens,
                system=_cached_system(system),
                messages=messages,
            )
        except Exception as exc:
            last_exc = exc
            transient = is_transient_api_error_fn(exc)
            if not transient or attempt >= max_retries:
                runtime.journal.log_runtime_event(
                    event_type="api_call_failed",
                    payload={
                        "attempt": attempt + 1,
                        "error": str(exc),
                        "transient": transient,
                        "mode": "text_only",
                        "model": getattr(runtime, "model", ""),
                    },
                    status="error",
                )
                raise
            wait_seconds = retry_wait_seconds[min(attempt, len(retry_wait_seconds) - 1)]
            runtime.journal.log_runtime_event(
                event_type="retry",
                payload={
                    "attempt": attempt + 1,
                    "wait_seconds": wait_seconds,
                    "error": str(exc),
                    "mode": "text_only",
                    "model": getattr(runtime, "model", ""),
                },
                status="warning",
            )
            time.sleep(wait_seconds)
    raise last_exc  # pragma: no cover
