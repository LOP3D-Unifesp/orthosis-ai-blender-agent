"""Handler: proposal.

The user asks "how would you fix X?" or "what's the smallest change to Y?".
The handler reads the relevant nodes, reasons about the best approach, and
presents a concrete proposal — but does NOT execute it.

No mutation tools.  No phase change (stays idle).  A proposal that the user
wants to execute will become a mutation_request in the next turn.
"""

from __future__ import annotations

from . import HandlerResult, TurnContext
from ..prompt_builder import build_system_prompt


def handle(ctx: TurnContext) -> HandlerResult:
    # Pre-refresh if stale so the proposal is grounded in real data.
    if ctx.meta.needs_baseline_refresh:
        _do_quick_read(ctx)

    knowledge = ctx.retrieve_knowledge()
    system = build_system_prompt(ctx.session, "proposal", knowledge=knowledge)
    messages = ctx.build_messages()
    text = ctx.call_agent_loop(system, messages)
    return HandlerResult(response_text=text)


def _do_quick_read(ctx: TurnContext) -> None:
    focus = getattr(ctx.session, "focus", None)
    tree_name = getattr(focus, "tree_name", "") if focus else ""
    if not tree_name:
        return
    try:
        import json
        result = ctx.execute_tool("get_tree_structure", {"tree_name": tree_name})
        baseline = getattr(ctx.session, "baseline_workspace", None)
        if baseline and result:
            # structural_summary must be dict[str, Any]; parse JSON or wrap raw string.
            try:
                parsed = json.loads(result)
                baseline.structural_summary = parsed if isinstance(parsed, dict) else {"summary": str(result)[:500]}
            except (json.JSONDecodeError, ValueError, TypeError):
                baseline.structural_summary = {"summary": str(result)[:500]}
            baseline.stale = False
    except Exception:
        pass
