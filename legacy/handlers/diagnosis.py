"""Handler: diagnosis.

The user wants to understand the tree, inspect a node, or see what changed.
Read tools are allowed (get_tree_structure, get_node_context, get_scene_summary,
capture_screenshot).  Mutation tools are blocked at the system-prompt level.

If the baseline is stale, a focused read is performed before answering.
"""

from __future__ import annotations

from . import HandlerResult, TurnContext
from ..prompt_builder import build_system_prompt


def handle(ctx: TurnContext) -> HandlerResult:
    # Pre-refresh baseline if stale and a tree is focused.
    if ctx.meta.needs_baseline_refresh:
        _do_quick_baseline_read(ctx)

    knowledge = ctx.retrieve_knowledge()
    system = build_system_prompt(ctx.session, "diagnosis", knowledge=knowledge)
    messages = ctx.build_messages()
    text = ctx.call_agent_loop(system, messages)
    return HandlerResult(response_text=text)


def _do_quick_baseline_read(ctx: TurnContext) -> None:
    """Perform a focused structural read to freshen the baseline."""
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
