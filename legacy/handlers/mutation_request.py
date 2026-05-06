"""Handler: mutation_request.

The user asked for a change. Execute it directly — no staging, no confirmation.

Flow:
1. If baseline is stale, do a quick targeted read first.
2. Run the agent loop — the model calls make_plan then execute_code directly.
3. Mark baseline stale so the next read fetches fresh data.
4. Return the model's response.
"""

from __future__ import annotations

from . import HandlerResult, TurnContext
from ..prompt_builder import build_system_prompt


def handle(ctx: TurnContext) -> HandlerResult:
    if ctx.meta.needs_baseline_refresh:
        _do_quick_read(ctx)

    knowledge = ctx.retrieve_knowledge()
    system = build_system_prompt(ctx.session, "mutation_request", knowledge=knowledge)
    messages = ctx.build_messages()

    text = ctx.call_agent_loop(system, messages)

    # Mark baseline stale — a mutation was attempted, tree state may have changed.
    baseline = getattr(ctx.session, "baseline_workspace", None)
    if baseline is not None:
        baseline.stale = True

    return HandlerResult(
        response_text=text,
        phase_transition=None,
    )


def _do_quick_read(ctx: TurnContext) -> None:
    focus = getattr(ctx.session, "focus", None)
    tree_name = getattr(focus, "tree_name", "") if focus else ""
    if not tree_name:
        return
    try:
        import json
        result = ctx.execute_tool("get_node_context", {"name": tree_name})
        baseline = getattr(ctx.session, "baseline_workspace", None)
        if baseline and result:
            try:
                parsed = json.loads(result)
                baseline.structural_summary = parsed if isinstance(parsed, dict) else {"summary": str(result)[:500]}
            except (json.JSONDecodeError, ValueError, TypeError):
                baseline.structural_summary = {"summary": str(result)[:500]}
            baseline.stale = False
    except Exception:
        pass
