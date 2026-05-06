"""Handler: clarification.

Conversational turns — the user asks about session state, baseline content,
or a concept.  One API call (text only) with a compact prompt.  Read tools
are allowed if the question clearly concerns the live tree state.
"""

from __future__ import annotations

from . import HandlerResult, TurnContext
from ..prompt_builder import build_system_prompt


def handle(ctx: TurnContext) -> HandlerResult:
    knowledge = ctx.retrieve_knowledge()
    system = build_system_prompt(ctx.session, "clarification", knowledge=knowledge)
    messages = ctx.build_messages()

    text = ctx.call_agent_loop(system, messages)
    return HandlerResult(response_text=text)
